from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlencode

import requests
from loguru import logger

from app.config import config
from app.models.project import BrollCandidate
from app.models.schema import VideoAspect
from app.services.material import _get_tls_verify, get_api_key

SUPPORTED_PROVIDERS = {"pexels", "pixabay", "coverr"}
FORBIDDEN_PROVIDERS = {"douyin", "bilibili", "xiaohongshu", "youtube", "tiktok"}


def _sanitize_error_message(message: str) -> str:
    """Remove potential API keys, authorization tokens, and credentials from log messages."""
    # Redact Authorization header values or query key params if present in exception strings
    sanitized = re.sub(r"(?:Bearer\s+|key=)[A-Za-z0-9_\-\.]{8,}", "[REDACTED]", message)
    return sanitized


def search_pexels_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    """Search Pexels API and return rich normalized BrollCandidate list."""
    aspect_enum = VideoAspect(aspect)
    orientation = "portrait" if aspect_enum == VideoAspect.portrait else "landscape"

    try:
        api_key = get_api_key("pexels_api_keys")
    except Exception as exc:
        logger.warning(f"Pexels API key unavailable: {_sanitize_error_message(str(exc))}")
        return []

    headers = {
        "Authorization": api_key,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        ),
    }
    params = {"query": query, "per_page": min(limit, 50), "orientation": orientation}
    query_url = f"https://api.pexels.com/videos/search?{urlencode(params)}"
    logger.info(f"searching Pexels candidates for query '{query}', orientation={orientation}")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(15, 30),
        )
        if r.status_code != 200:
            logger.warning(f"Pexels search returned HTTP status {r.status_code}")
            return []
        response = r.json()
    except Exception as e:
        logger.warning(
            f"Pexels search failed for query '{query}': {_sanitize_error_message(str(e))}"
        )
        return []

    videos = response.get("videos", []) if isinstance(response, dict) else []
    candidates: list[BrollCandidate] = []

    for v in videos:
        try:
            duration = float(v.get("duration") or 0)
            if minimum_duration > 0 and duration < minimum_duration:
                continue

            video_files = v.get("video_files") or []
            if not video_files:
                continue

            # Pick the best MP4 video file by resolution (prefer full HD or highest resolution)
            valid_files = [
                f
                for f in video_files
                if f.get("link")
                and (
                    f.get("file_type") == "video/mp4"
                    or str(f.get("link")).split("?")[0].endswith(".mp4")
                    or "mp4" in str(f.get("file_type", "")).lower()
                )
            ]
            if not valid_files:
                valid_files = [f for f in video_files if f.get("link")]
            if not valid_files:
                continue

            # Sort by area (width * height) descending
            def _file_sort_key(f: dict[str, Any]) -> int:
                w = int(f.get("width") or 0)
                h = int(f.get("height") or 0)
                return w * h

            best_file = max(valid_files, key=_file_sort_key)
            download_url = best_file.get("link")
            width = int(best_file.get("width") or v.get("width") or 1920)
            height = int(best_file.get("height") or v.get("height") or 1080)
            fps = float(best_file["fps"]) if best_file.get("fps") is not None else None

            v_id = str(v.get("id") or "")
            if not v_id or not download_url:
                continue

            user_obj = v.get("user")
            author = user_obj.get("name") if isinstance(user_obj, dict) else None

            candidate = BrollCandidate(
                id=f"pexels-{v_id}",
                provider="pexels",
                provider_asset_id=v_id,
                query=query,
                download_url=download_url,
                source_url=v.get("url"),
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                title=None,
                description=None,
                tags=[],
                author=author,
                license="Pexels License",
                metadata={"quality": best_file.get("quality")},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Pexels video item: {exc}")
            continue

    return candidates


def search_pixabay_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    """Search Pixabay API and return rich normalized BrollCandidate list."""
    try:
        api_key = get_api_key("pixabay_api_keys")
    except Exception as exc:
        logger.warning(f"Pixabay API key unavailable: {_sanitize_error_message(str(exc))}")
        return []

    params = {
        "q": query,
        "video_type": "all",
        "per_page": min(limit, 50),
        "key": api_key,
    }
    query_url = f"https://pixabay.com/api/videos/?{urlencode(params)}"
    logger.info(f"searching Pixabay candidates for query '{query}'")

    try:
        r = requests.get(
            query_url,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(15, 30),
        )
        if r.status_code != 200:
            logger.warning(f"Pixabay search returned HTTP status {r.status_code}")
            return []
        response = r.json()
    except Exception as e:
        logger.warning(
            f"Pixabay search failed for query '{query}': {_sanitize_error_message(str(e))}"
        )
        return []

    hits = response.get("hits", []) if isinstance(response, dict) else []
    candidates: list[BrollCandidate] = []

    for hit in hits:
        try:
            duration = float(hit.get("duration") or 0)
            if minimum_duration > 0 and duration < minimum_duration:
                continue

            hit_id = str(hit.get("id") or "")
            videos_dict = hit.get("videos") or {}
            if not hit_id or not isinstance(videos_dict, dict) or not videos_dict:
                continue

            # Preferred rendition order: large, medium, small, tiny
            rendition = None
            for key in ("large", "medium", "small", "tiny"):
                candidate_variant = videos_dict.get(key)
                if isinstance(candidate_variant, dict) and candidate_variant.get("url"):
                    rendition = candidate_variant
                    break

            if not rendition:
                continue

            download_url = rendition.get("url")
            width = int(rendition.get("width") or 1920)
            height = int(rendition.get("height") or 1080)

            raw_tags = str(hit.get("tags") or "")
            tags = [t.strip() for t in raw_tags.split(",") if t.strip()]

            candidate = BrollCandidate(
                id=f"pixabay-{hit_id}",
                provider="pixabay",
                provider_asset_id=hit_id,
                query=query,
                download_url=download_url,
                source_url=hit.get("pageURL"),
                duration=duration,
                width=width,
                height=height,
                tags=tags,
                author=hit.get("user"),
                license="Pixabay License",
                metadata={},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Pixabay hit: {exc}")
            continue

    return candidates


def search_coverr_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    """Search Coverr API and return rich normalized BrollCandidate list."""
    try:
        api_key = get_api_key("coverr_api_keys")
    except Exception as exc:
        logger.warning(f"Coverr API key unavailable: {_sanitize_error_message(str(exc))}")
        return []

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {
        "query": query,
        "page_size": min(limit, 50),
        "urls": "true",
        "sort": "popular",
    }
    query_url = f"https://api.coverr.co/videos?{urlencode(params)}"
    logger.info(f"searching Coverr candidates for query '{query}'")

    try:
        r = requests.get(
            query_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(15, 30),
        )
        if r.status_code != 200:
            logger.warning(f"Coverr search returned HTTP status {r.status_code}")
            return []
        response = r.json()
    except Exception as e:
        logger.warning(
            f"Coverr search failed for query '{query}': {_sanitize_error_message(str(e))}"
        )
        return []

    hits = response.get("hits", []) if isinstance(response, dict) else []
    candidates: list[BrollCandidate] = []

    for hit in hits:
        try:
            raw_dur = hit.get("duration") or 0
            duration = float(raw_dur)
            if minimum_duration > 0 and duration < minimum_duration:
                continue

            hit_id = str(hit.get("id") or "")
            urls_obj = hit.get("urls") or {}
            download_url = urls_obj.get("mp4_download") or urls_obj.get("mp4")

            if not hit_id or not download_url:
                continue

            title = hit.get("title")
            description = hit.get("description")
            raw_tags = hit.get("tags") or []
            if isinstance(raw_tags, str):
                tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
            elif isinstance(raw_tags, list):
                tags = [str(t).strip() for t in raw_tags if str(t).strip()]
            else:
                tags = []

            author_obj = hit.get("author") or hit.get("user")
            if isinstance(author_obj, dict):
                author = author_obj.get("name")
            elif isinstance(author_obj, str):
                author = author_obj
            else:
                author = None

            width = int(hit.get("width") or 1920)
            height = int(hit.get("height") or 1080)

            candidate = BrollCandidate(
                id=f"coverr-{hit_id}",
                provider="coverr",
                provider_asset_id=hit_id,
                query=query,
                download_url=download_url,
                source_url=f"https://coverr.co/videos/{hit_id}",
                duration=duration,
                width=width,
                height=height,
                title=title,
                description=description,
                tags=tags,
                author=author,
                license="Coverr License",
                metadata={},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Coverr hit: {exc}")
            continue

    return candidates


def search_stock_candidates(
    provider: str,
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    """Dispatch provider candidate search with strict whitelisting and validation."""
    provider_clean = str(provider).strip().lower()
    if provider_clean in FORBIDDEN_PROVIDERS:
        raise ValueError(
            f"Forbidden video source: {provider_clean}. Only stock providers are allowed."
        )
    if provider_clean not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported video source: {provider_clean}. Supported: {SUPPORTED_PROVIDERS}"
        )

    if provider_clean == "pexels":
        return search_pexels_candidates(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )
    if provider_clean == "pixabay":
        return search_pixabay_candidates(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )
    if provider_clean == "coverr":
        return search_coverr_candidates(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )

    return []
