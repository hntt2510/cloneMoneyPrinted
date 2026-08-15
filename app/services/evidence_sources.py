from __future__ import annotations

import hashlib
import html
import io
import ipaddress
import mimetypes
import os
import re
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from loguru import logger
from PIL import Image

from app.config import config
from app.models.evidence import (
    EvidenceSource,
    EvidenceSourceKind,
    EvidenceSourceRegistry,
    EvidenceSourceTrust,
)
from app.services import material


class SSRFValidationError(ValueError):
    """Raised when a URL targets a private, loopback, or forbidden address."""


SENSITIVE_EXACT_KEYS = frozenset({
    "token",
    "access_token",
    "auth",
    "authorization",
    "key",
    "apikey",
    "api_key",
    "secret",
    "sig",
    "signature",
    "password",
    "code",
    "credential",
    "x-amz-signature",
    "x-amz-security-token",
    "x-amz-credential",
    "sp",
    "sv",
    "se",
    "sr",
})


def sanitize_secret_url(url: str | None) -> str | None:
    """Strip authentication credentials, API tokens, and signatures from URLs for safe persistence."""
    if not url:
        return url

    try:
        parsed = urlparse(url)
        if not parsed.query:
            if "@" in parsed.netloc:
                clean_netloc = parsed.netloc.split("@")[-1]
                return urlunparse(parsed._replace(netloc=clean_netloc))
            return url

        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        sanitized_pairs = []
        for k, v in query_pairs:
            lower_k = k.lower()
            if lower_k in SENSITIVE_EXACT_KEYS or lower_k.endswith(("_token", "_key", "_secret", "_sig", "_signature")):
                sanitized_pairs.append((k, "[REDACTED]"))
            else:
                sanitized_pairs.append((k, v))

        clean_netloc = parsed.netloc
        if "@" in clean_netloc:
            clean_netloc = clean_netloc.split("@")[-1]

        clean_query = urlencode(sanitized_pairs)
        return urlunparse(parsed._replace(netloc=clean_netloc, query=clean_query))
    except Exception:
        return url


def is_ip_private_or_restricted(ip_str: str) -> bool:
    """Check if an IP string is loopback, private, link-local, multicast, or reserved."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        )
    except ValueError:
        return False


def is_safe_remote_url(url: str) -> tuple[bool, str | None]:
    """Validate that a URL is http/https and does not resolve to loopback, private, or metadata IPs."""
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL"

    try:
        parsed = urlparse(url.strip())
    except Exception as exc:
        return False, f"URL parse error: {exc}"

    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return False, f"Unsupported URL scheme: '{scheme}'. Only HTTP and HTTPS are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "Missing hostname in URL"

    lower_host = hostname.lower()
    if lower_host in ("localhost", "0.0.0.0", "127.0.0.1", "::1", "169.254.169.254", "metadata.google.internal"):
        return False, f"Forbidden local/metadata host: '{hostname}'"

    # Check if host is direct IP
    try:
        if is_ip_private_or_restricted(lower_host):
            return False, f"Private or restricted IP address forbidden: '{hostname}'"
    except Exception:
        pass

    # Resolve host via DNS
    try:
        addr_info = socket.getaddrinfo(hostname, parsed.port or (443 if scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        for entry in addr_info:
            sockaddr = entry[4]
            resolved_ip = sockaddr[0]
            if is_ip_private_or_restricted(resolved_ip):
                return False, f"Hostname '{hostname}' resolved to restricted IP '{resolved_ip}'"
    except socket.gaierror as gai_err:
        return False, f"DNS resolution failed for '{hostname}': {gai_err}"
    except Exception as exc:
        return False, f"Network validation error for '{hostname}': {exc}"

    return True, None


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hash of a file on disk."""
    hasher = hashlib.sha256()
    path = Path(file_path)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def detect_file_mime(file_path: Path | str, header_bytes: bytes | None = None) -> str:
    """Detect file MIME type from magic bytes and file extension."""
    path = Path(file_path)
    if header_bytes is None and path.exists():
        try:
            with open(path, "rb") as f:
                header_bytes = f.read(1024)
        except Exception:
            header_bytes = b""

    hdr = header_bytes or b""

    # PDF magic
    if hdr.startswith(b"%PDF-"):
        return "application/pdf"

    # Image magics
    if hdr.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if hdr.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if hdr.startswith(b"GIF87a") or hdr.startswith(b"GIF89a"):
        return "image/gif"
    if hdr.startswith(b"RIFF") and b"WEBP" in hdr[:16]:
        return "image/webp"

    # HTML detection
    lower_hdr = hdr.lower()
    if b"<!doctype html" in lower_hdr or b"<html" in lower_hdr or b"<body" in lower_hdr or b"<head" in lower_hdr:
        return "text/html"

    # Fallback to extension
    ext_guess, _ = mimetypes.guess_type(str(path))
    return ext_guess or "application/octet-stream"


class SSRFSafeSession(requests.Session):
    """Requests Session that validates all redirect locations against SSRF rules."""

    def rebuild_auth(self, prepared_request, response):
        super().rebuild_auth(prepared_request, response)
        # Validate target redirect URL
        redirect_url = prepared_request.url
        is_safe, reason = is_safe_remote_url(redirect_url)
        if not is_safe:
            raise SSRFValidationError(f"Redirect target blocked by SSRF policy: {reason}")


def download_evidence_file(
    url: str,
    dest_path: Path | str,
    max_bytes: int = 104857600,  # 100 MB default limit
    timeout: tuple[int, int] = (15, 30),
) -> tuple[str, str]:
    """Safely stream-download a remote evidence file with SSRF checks, size limits, and SHA-256 calculation."""
    is_safe, reason = is_safe_remote_url(url)
    if not is_safe:
        raise SSRFValidationError(f"Remote URL blocked by SSRF policy: {reason}")

    dest = Path(dest_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    session = SSRFSafeSession()
    headers = {
        "User-Agent": "MoneyPrinterTurbo/1.3 (Evidence Acquisition Engine; +https://github.com/hntt2510/cloneMoneyPrinted)",
        "Accept": "*/*",
    }

    try:
        with session.get(
            url,
            headers=headers,
            proxies=config.proxy,
            verify=material._get_tls_verify(),
            timeout=timeout,
            stream=True,
            allow_redirects=True,
        ) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"HTTP {response.status_code} error downloading from {sanitize_secret_url(url)}")

            content_length_hdr = response.headers.get("Content-Length")
            if content_length_hdr:
                try:
                    content_length = int(content_length_hdr)
                    if content_length > max_bytes:
                        raise ValueError(
                            f"Remote file size ({content_length} bytes) exceeds maximum limit of {max_bytes} bytes"
                        )
                except (ValueError, TypeError):
                    pass

            hasher = hashlib.sha256()
            bytes_downloaded = 0
            header_sample = bytearray()

            with open(dest, "wb") as f:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    bytes_downloaded += len(chunk)
                    if bytes_downloaded > max_bytes:
                        dest.unlink(missing_ok=True)
                        raise ValueError(f"Downloaded stream exceeded maximum limit of {max_bytes} bytes")
                    if len(header_sample) < 1024:
                        header_sample.extend(chunk[: 1024 - len(header_sample)])
                    hasher.update(chunk)
                    f.write(chunk)

            if bytes_downloaded == 0:
                dest.unlink(missing_ok=True)
                raise ValueError("Downloaded file is empty (0 bytes)")

            sha256_hex = hasher.hexdigest()
            mime_type = detect_file_mime(dest, bytes(header_sample))
            return sha256_hex, mime_type

    except Exception as exc:
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass
        raise exc


# --- Static Webpage Text Extraction ---

class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._title_parts: list[str] = []
        self._in_title = False
        self._in_ignored_tag = False
        self._ignored_tags = {"script", "style", "noscript", "svg", "header", "footer", "nav"}
        self.meta_site_name: str | None = None
        self.meta_description: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._in_ignored_tag = True
        elif tag_lower == "title":
            self._in_title = True
        elif tag_lower == "meta":
            attr_dict = {k.lower(): (v or "").strip() for k, v in attrs}
            prop = attr_dict.get("property", "").lower()
            name = attr_dict.get("name", "").lower()
            content = attr_dict.get("content", "").strip()

            if (prop in ("og:site_name", "og:publisher") or name == "publisher") and content:
                self.meta_site_name = content
            elif (prop in ("og:description", "twitter:description") or name == "description") and content:
                self.meta_description = content

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()
        if tag_lower in self._ignored_tags:
            self._in_ignored_tag = False
        elif tag_lower == "title":
            self._in_title = False
        elif tag_lower in ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "article", "section"):
            self._text_parts.append("\n")

    def handle_data(self, data: str):
        if self._in_ignored_tag:
            return
        clean = data.strip()
        if not clean:
            return
        if self._in_title:
            self._title_parts.append(clean)
        else:
            self._text_parts.append(clean + " ")

    def get_title(self) -> str:
        return html.unescape(" ".join(self._title_parts)).strip()

    def get_text(self) -> str:
        raw = "".join(self._text_parts)
        # Collapse whitespace lines
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines()]
        clean_lines = [l for l in lines if l]
        return html.unescape("\n".join(clean_lines))


def extract_webpage_content(
    html_content: str,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Parse static HTML content to extract page title, publisher/domain, and clean visible text."""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(html_content)
    except Exception as exc:
        logger.warning(f"HTMLParser error: {exc}; proceeding with fallback parsing.")

    title = parser.get_title()
    text = parser.get_text()
    publisher = parser.meta_site_name

    if not publisher and source_url:
        try:
            parsed = urlparse(source_url)
            publisher = parsed.netloc.replace("www.", "")
        except Exception:
            pass

    if not title and source_url:
        title = publisher or "Web Document"

    return {
        "title": title,
        "publisher": publisher,
        "description": parser.meta_description,
        "text": text,
    }


# --- Wikimedia Commons Evidence Adapter ---

def search_wikimedia_evidence(
    search_query: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Query Wikimedia Commons API for factual/evidence images with license and artist provenance."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": search_query,
        "gsrnamespace": 6,  # File namespace
        "gsrlimit": max(1, min(15, limit)),
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": 1920,
    }
    headers = {
        "User-Agent": "MoneyPrinterTurbo/1.3 (Evidence Acquisition Engine; +https://github.com/hntt2510/cloneMoneyPrinted)",
    }

    try:
        resp = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params=params,
            headers=headers,
            proxies=config.proxy,
            verify=material._get_tls_verify(),
            timeout=(15, 30),
        )
        if resp.status_code != 200:
            logger.warning(f"Wikimedia API returned status {resp.status_code}")
            return []

        data = resp.json()
        pages = (data.get("query") or {}).get("pages") or {}
        results = []

        for page in pages.values():
            image_info = (page.get("imageinfo") or [{}])[0]
            metadata = image_info.get("extmetadata") or {}
            thumb_url = image_info.get("thumburl") or image_info.get("url")
            if not thumb_url:
                continue

            license_name = (
                (metadata.get("LicenseShortName") or {}).get("value", "")
                or (metadata.get("License") or {}).get("value", "")
            )
            license_clean = html.unescape(re.sub(r"<[^>]+>", "", license_name)).strip() or None

            author_raw = (metadata.get("Artist") or {}).get("value", "")
            author_clean = html.unescape(re.sub(r"<[^>]+>", "", author_raw)).strip() or None

            title_raw = (
                (metadata.get("ObjectName") or {}).get("value", "")
                or page.get("title", search_query)
            )
            title_clean = html.unescape(re.sub(r"<[^>]+>", "", title_raw)).strip()
            if title_clean.lower().startswith("file:"):
                title_clean = title_clean[5:].strip()

            categories_raw = (metadata.get("Categories") or {}).get("value", "")
            categories = [c.strip() for c in categories_raw.split("|") if c.strip()]

            results.append({
                "provider": "wikimedia",
                "image_url": thumb_url,
                "source_url": image_info.get("descriptionurl", ""),
                "author": author_clean,
                "license": license_clean,
                "title": title_clean,
                "width": image_info.get("width"),
                "height": image_info.get("height"),
                "categories": categories,
            })

        return results

    except Exception as exc:
        logger.warning(f"Wikimedia search failed for '{search_query}': {exc}")
        return []
