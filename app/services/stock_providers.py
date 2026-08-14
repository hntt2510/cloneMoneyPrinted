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


class StockSearchResult:
    """Encapsulates stock provider query results distinguishing empty results from provider errors."""

    def __init__(
        self,
        provider: str,
        query: str,
        candidates: list[BrollCandidate] | None = None,
        error: str | None = None,
    ) -> None:
        self.provider = provider
        self.query = query
        self.candidates = candidates or []
        self.error = error

    @property
    def is_success(self) -> bool:
        return self.error is None


def _sanitize_error_message(message: str) -> str:
    """Remove potential API keys, authorization tokens, and credentials from log and error messages."""
    first_line = message.strip().split("\n")[0]
    sanitized = re.sub(r"(?:Bearer\s+|key=)[A-Za-z0-9_\-\.]{8,}", "[REDACTED]", first_line)
    sanitized = re.sub(r"(?:api_key=)[A-Za-z0-9_\-\.]{8,}", "api_key=[REDACTED]", sanitized)
    return sanitized.strip()


def search_pexels_candidates_detailed(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> StockSearchResult:
    """Search Pexels API and return rich StockSearchResult."""
    aspect_enum = VideoAspect(aspect)
    orientation = "portrait" if aspect_enum == VideoAspect.portrait else "landscape"

    try:
        api_key = get_api_key("pexels_api_keys")
    except Exception as exc:
        err = f"pexels: {_sanitize_error_message(str(exc))}"
        logger.warning(f"Pexels API key unavailable: {_sanitize_error_message(str(exc))}")
        return StockSearchResult(provider="pexels", query=query, candidates=[], error=err)

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
            err = f"pexels: HTTP {r.status_code}"
            logger.warning(f"Pexels search returned HTTP status {r.status_code}")
            return StockSearchResult(provider="pexels", query=query, candidates=[], error=err)
        response = r.json()
    except Exception as e:
        err = f"pexels: {_sanitize_error_message(str(e))}"
        logger.warning(f"Pexels search failed for query '{query}': {err}")
        return StockSearchResult(provider="pexels", query=query, candidates=[], error=err)

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
                source_url=v.get("url") or None,
                duration=duration,
                width=width,
                height=height,
                fps=fps,
                title=None,
                description=None,
                tags=[],
                author=author,
                license=v.get("license") or None,
                metadata={"quality": best_file.get("quality")},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Pexels video item: {exc}")
            continue

    return StockSearchResult(provider="pexels", query=query, candidates=candidates, error=None)


def search_pixabay_candidates_detailed(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> StockSearchResult:
    """Search Pixabay API and return rich StockSearchResult."""
    try:
        api_key = get_api_key("pixabay_api_keys")
    except Exception as exc:
        err = f"pixabay: {_sanitize_error_message(str(exc))}"
        logger.warning(f"Pixabay API key unavailable: {_sanitize_error_message(str(exc))}")
        return StockSearchResult(provider="pixabay", query=query, candidates=[], error=err)

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
            err = f"pixabay: HTTP {r.status_code}"
            logger.warning(f"Pixabay search returned HTTP status {r.status_code}")
            return StockSearchResult(provider="pixabay", query=query, candidates=[], error=err)
        response = r.json()
    except Exception as e:
        err = f"pixabay: {_sanitize_error_message(str(e))}"
        logger.warning(f"Pixabay search failed for query '{query}': {err}")
        return StockSearchResult(provider="pixabay", query=query, candidates=[], error=err)

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
                source_url=hit.get("pageURL") or hit.get("url") or None,
                duration=duration,
                width=width,
                height=height,
                tags=tags,
                author=hit.get("user"),
                license=hit.get("license") or None,
                metadata={},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Pixabay hit: {exc}")
            continue

    return StockSearchResult(provider="pixabay", query=query, candidates=candidates, error=None)


def search_coverr_candidates_detailed(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> StockSearchResult:
    """Search Coverr API and return rich StockSearchResult."""
    try:
        api_key = get_api_key("coverr_api_keys")
    except Exception as exc:
        err = f"coverr: {_sanitize_error_message(str(exc))}"
        logger.warning(f"Coverr API key unavailable: {_sanitize_error_message(str(exc))}")
        return StockSearchResult(provider="coverr", query=query, candidates=[], error=err)

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
            err = f"coverr: HTTP {r.status_code}"
            logger.warning(f"Coverr search returned HTTP status {r.status_code}")
            return StockSearchResult(provider="coverr", query=query, candidates=[], error=err)
        response = r.json()
    except Exception as e:
        err = f"coverr: {_sanitize_error_message(str(e))}"
        logger.warning(f"Coverr search failed for query '{query}': {err}")
        return StockSearchResult(provider="coverr", query=query, candidates=[], error=err)

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

            source_url = hit.get("pageURL") or hit.get("url") or None
            license_val = hit.get("license") or None

            candidate = BrollCandidate(
                id=f"coverr-{hit_id}",
                provider="coverr",
                provider_asset_id=hit_id,
                query=query,
                download_url=download_url,
                source_url=source_url,
                duration=duration,
                width=width,
                height=height,
                title=title,
                description=description,
                tags=tags,
                author=author,
                license=license_val,
                metadata={},
            )
            candidates.append(candidate)
        except Exception as exc:
            logger.debug(f"Skipping malformed Coverr hit: {exc}")
            continue

    return StockSearchResult(provider="coverr", query=query, candidates=candidates, error=None)


def search_stock_candidates_detailed(
    provider: str,
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> StockSearchResult:
    """Dispatch provider candidate search with strict whitelisting returning detailed StockSearchResult."""
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
        return search_pexels_candidates_detailed(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )
    if provider_clean == "pixabay":
        return search_pixabay_candidates_detailed(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )
    if provider_clean == "coverr":
        return search_coverr_candidates_detailed(
            query=query, minimum_duration=minimum_duration, aspect=aspect, limit=limit
        )

    return StockSearchResult(provider=provider_clean, query=query, candidates=[], error="Unknown provider")


def search_stock_candidates(
    provider: str,
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    """Dispatch provider candidate search and return candidate list."""
    res = search_stock_candidates_detailed(
        provider=provider,
        query=query,
        minimum_duration=minimum_duration,
        aspect=aspect,
        limit=limit,
    )
    return res.candidates


def search_pexels_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    return search_pexels_candidates_detailed(query, minimum_duration, aspect, limit).candidates


def search_pixabay_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    return search_pixabay_candidates_detailed(query, minimum_duration, aspect, limit).candidates


def search_coverr_candidates(
    query: str,
    minimum_duration: float = 0.0,
    aspect: VideoAspect = VideoAspect.landscape,
    limit: int = 20,
) -> list[BrollCandidate]:
    return search_coverr_candidates_detailed(query, minimum_duration, aspect, limit).candidates
