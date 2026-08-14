from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence

import requests
from loguru import logger
from moviepy.video.io.VideoFileClip import VideoFileClip

from app.config import config
from app.models.project import (
    BrollCandidate,
    BrollPayload,
    JobStatus,
    ProjectSpec,
    SelectedBrollAsset,
    VisualCue,
)
from app.models.schema import VideoAspect
from app.services.material import _get_tls_verify
from app.services.stock_providers import search_stock_candidates
from app.utils import utils

STOPWORDS = {
    "a", "an", "the", "in", "on", "of", "and", "or", "for", "with", "at", "by",
    "to", "from", "is", "are", "was", "were", "be", "been", "that", "this",
    "it", "as", "into", "over", "after", "about",
}


class BrollAcquisitionError(Exception):
    """Raised when B-roll acquisition fails for a scene."""


class BrollSelectionContext:
    """Project-level memory tracking selected assets, URLs, queries, and providers

    to enforce strict uniqueness and diversity across scenes.
    """

    def __init__(self) -> None:
        self.selected_asset_ids: set[str] = set()
        self.selected_urls: set[str] = set()
        self.recent_queries: list[str] = []
        self.recent_providers: list[str] = []
        self.recent_tags: list[str] = []

    def _normalize_url_key(self, url: str) -> str:
        """Strip query parameters and trailing slashes for stable URL comparison."""
        return url.split("?")[0].rstrip("/").lower()

    def is_duplicate(self, candidate: BrollCandidate) -> bool:
        """Check if candidate has already been selected for another scene."""
        asset_key = f"{candidate.provider}:{candidate.provider_asset_id}"
        if asset_key in self.selected_asset_ids:
            return True
        dl_key = self._normalize_url_key(candidate.download_url)
        if dl_key in self.selected_urls:
            return True
        if candidate.source_url:
            src_key = self._normalize_url_key(candidate.source_url)
            if src_key in self.selected_urls:
                return True
        return False

    def record_selection(self, candidate: BrollCandidate, asset: SelectedBrollAsset) -> None:
        """Record newly selected asset in project-level diversity memory."""
        asset_key = f"{candidate.provider}:{candidate.provider_asset_id}"
        self.selected_asset_ids.add(asset_key)
        self.selected_urls.add(self._normalize_url_key(candidate.download_url))
        if candidate.source_url:
            self.selected_urls.add(self._normalize_url_key(candidate.source_url))
        self.recent_queries.append(candidate.query.lower())
        self.recent_providers.append(candidate.provider)
        if candidate.tags:
            self.recent_tags.extend(t.lower() for t in candidate.tags[:5])


def _extract_meaningful_tokens(text: str) -> list[str]:
    """Extract lowercase word tokens excluding stopwords."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 1]


def score_candidate(
    candidate: BrollCandidate,
    scene_duration: float,
    target_aspect: VideoAspect = VideoAspect.landscape,
    avoid_terms: list[str] | None = None,
    context: BrollSelectionContext | None = None,
) -> tuple[float, dict[str, float]]:
    """Score a BrollCandidate deterministically on a 0–100 scale.

    Weights:
    - Semantic relevance: 40
    - Visual quality: 20
    - Scene compatibility: 15
    - Duration suitability: 10
    - Aspect ratio: 10
    - Repetition penalty: 5 (deduction)
    """
    avoid_terms = avoid_terms or []

    # 1. Semantic Relevance (40 max)
    query_tokens = _extract_meaningful_tokens(candidate.query)
    meta_text = f"{candidate.title or ''} {candidate.description or ''} {' '.join(candidate.tags)}"
    meta_tokens = _extract_meaningful_tokens(meta_text)

    if meta_tokens and query_tokens:
        overlap_count = sum(1 for qt in query_tokens if qt in meta_tokens)
        overlap_ratio = overlap_count / max(1, len(query_tokens))
        semantic_score = round(15.0 + 25.0 * overlap_ratio, 2)
    elif query_tokens:
        # Neutral baseline when provider has no metadata tags/title (e.g. basic Pexels/Coverr)
        semantic_score = 20.0
    else:
        semantic_score = 20.0

    # 2. Visual Quality (20 max)
    w, h = candidate.width, candidate.height
    min_dim = min(w, h)
    if min_dim >= 2160:
        quality_score = 20.0
    elif min_dim >= 1080:
        quality_score = 18.0
    elif min_dim >= 720:
        quality_score = 14.0
    elif min_dim > 0:
        quality_score = 7.0
    else:
        quality_score = 10.0

    # 3. Scene Compatibility & Avoid Terms (15 max)
    compatibility_score = 15.0
    if avoid_terms and meta_tokens:
        for avoid in avoid_terms:
            avoid_tokens = _extract_meaningful_tokens(avoid)
            if any(at in meta_tokens for at in avoid_tokens):
                compatibility_score = 0.0
                break

    # 4. Duration Suitability (10 max)
    if candidate.duration < scene_duration:
        duration_score = 0.0
    elif candidate.duration <= scene_duration + 15.0:
        duration_score = 10.0
    elif candidate.duration <= 120.0:
        duration_score = 8.0
    else:
        duration_score = 5.0

    # 5. Aspect Ratio (10 max)
    is_target_portrait = VideoAspect(target_aspect) == VideoAspect.portrait
    is_candidate_portrait = candidate.height > candidate.width
    if is_target_portrait == is_candidate_portrait:
        aspect_score = 10.0
    else:
        aspect_score = 5.0

    # 6. Repetition Penalty (5 max deduction)
    repetition_penalty = 0.0
    if context:
        if context.recent_providers and context.recent_providers[-1] == candidate.provider:
            repetition_penalty += 1.0
        if candidate.query.lower() in context.recent_queries[-3:]:
            repetition_penalty += 2.0
    repetition_penalty = min(5.0, repetition_penalty)

    total_score = max(
        0.0,
        min(
            100.0,
            round(
                semantic_score
                + quality_score
                + compatibility_score
                + duration_score
                + aspect_score
                - repetition_penalty,
                2,
            ),
        ),
    )

    breakdown = {
        "semantic": semantic_score,
        "quality": quality_score,
        "compatibility": compatibility_score,
        "duration": duration_score,
        "aspect": aspect_score,
        "repetition_penalty": repetition_penalty,
        "total": total_score,
    }

    return total_score, breakdown


def _rank_candidate_sort_key(c: BrollCandidate) -> tuple:
    """Deterministic tie-breaker sort key for candidate ranking."""
    return (
        -c.score,
        -c.score_breakdown.get("semantic", 0.0),
        -c.score_breakdown.get("quality", 0.0),
        c.provider,
        c.id,
    )


def collect_and_rank_candidates(
    cue: VisualCue,
    project: ProjectSpec,
    context: BrollSelectionContext,
    target_pool_size: int = 10,
) -> list[BrollCandidate]:
    """Collect candidates across primary and fallback queries and rank deterministically."""
    scene_duration = max(0.1, (cue.end or 0.0) - (cue.start or 0.0))
    payload = BrollPayload.model_validate(cue.payload)
    queries = [payload.search_query] + [q for q in payload.fallback_queries if q != payload.search_query]
    providers = payload.source_priority or ["pexels", "pixabay", "coverr"]

    all_candidates: list[BrollCandidate] = []
    seen_ids: set[str] = set()

    for query_index, query in enumerate(queries):
        for provider in providers:
            try:
                candidates = search_stock_candidates(
                    provider=provider,
                    query=query,
                    minimum_duration=scene_duration,
                    aspect=project.project.aspect_ratio,
                    limit=15,
                )
            except Exception as exc:
                logger.warning(f"Error searching {provider} for query '{query}': {exc}")
                continue

            for c in candidates:
                if c.id in seen_ids or context.is_duplicate(c) or c.duration < scene_duration:
                    continue
                score, breakdown = score_candidate(
                    candidate=c,
                    scene_duration=scene_duration,
                    target_aspect=project.project.aspect_ratio,
                    avoid_terms=payload.avoid,
                    context=context,
                )
                c.score = score
                c.score_breakdown = breakdown
                all_candidates.append(c)
                seen_ids.add(c.id)

        # Early exit if primary query found enough good candidates
        if len(all_candidates) >= target_pool_size and query_index == 0:
            break

    # Sort deterministically
    all_candidates.sort(key=_rank_candidate_sort_key)
    return all_candidates


def download_candidate(candidate: BrollCandidate, destination_file: Path | str) -> Path:
    """Download single selected winner video file with integrity and timeout validation."""
    dest = Path(destination_file)
    dest.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
    }

    temp_dest = dest.with_suffix(".download.tmp")
    try:
        with requests.get(
            candidate.download_url,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 180),
            stream=True,
        ) as r:
            r.raise_for_status()
            with open(temp_dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

        if not temp_dest.exists() or temp_dest.stat().st_size == 0:
            raise ValueError(f"Downloaded file is missing or empty: {temp_dest}")

        # Validate that video decodes properly
        clip = VideoFileClip(str(temp_dest))
        duration = clip.duration
        fps = clip.fps
        clip.close()

        if duration <= 0 or fps <= 0:
            raise ValueError(f"Decoded video has invalid duration ({duration}) or fps ({fps})")

        if dest.exists():
            dest.unlink()
        temp_dest.replace(dest)
        return dest
    except Exception as exc:
        if temp_dest.exists():
            try:
                temp_dest.unlink()
            except Exception:
                pass
        raise ValueError(f"Failed to download candidate {candidate.id}: {exc}") from exc


def get_video_duration(video_path: Path | str) -> float:
    """Return accurate duration of a video file using VideoFileClip."""
    clip = VideoFileClip(str(video_path))
    duration = float(clip.duration)
    clip.close()
    return duration


def render_scene_clip(
    source_path: Path | str,
    destination_path: Path | str,
    scene_duration: float,
    target_width: int,
    target_height: int,
    fps: int = 30,
) -> tuple[float, float, float]:
    """Trim and center-crop video to exact target dimensions and duration without audio.

    Returns:
        (source_duration, trim_start, trim_end)
    """
    src = Path(source_path).resolve()
    dest = Path(destination_path).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    source_duration = get_video_duration(src)
    if source_duration < scene_duration:
        raise ValueError(
            f"Source video duration ({source_duration:.2f}s) is shorter than required scene duration ({scene_duration:.2f}s)"
        )

    # Center-biased trim
    trim_start = max(0.0, round((source_duration - scene_duration) / 2.0, 3))
    trim_end = round(trim_start + scene_duration, 3)

    ffmpeg_bin = utils.get_ffmpeg_binary()

    # Scale to cover target frame then center-crop, force constant frame rate, drop audio
    filter_complex = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height},"
        f"fps={fps}"
    )

    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{trim_start:.3f}",
        "-t",
        f"{scene_duration:.3f}",
        "-i",
        str(src),
        "-vf",
        filter_complex,
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dest),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(
            f"FFmpeg scene normalization failed (exit {result.returncode}): {result.stderr[:400]}"
        )

    # Validate output duration QA
    actual_duration = get_video_duration(dest)
    tolerance = max(1.0 / fps, 0.05)
    if abs(actual_duration - scene_duration) > tolerance + 0.05:
        logger.warning(
            f"Rendered clip duration ({actual_duration:.3f}s) deviates slightly from expected ({scene_duration:.3f}s)"
        )

    return source_duration, trim_start, trim_end


def acquire_broll_scene(
    cue: VisualCue,
    project: ProjectSpec,
    task_directory: Path | str,
    context: BrollSelectionContext,
) -> SelectedBrollAsset:
    """Acquire, download selected winner, and render exact scene clip for a B-roll VisualCue."""
    task_dir = Path(task_directory).resolve()
    scene_dir = task_dir / "broll" / cue.id
    scene_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = scene_dir / "metadata.json"
    rendered_path = scene_dir / "rendered.mp4"
    source_path = scene_dir / "source.mp4"

    # Lightweight resumability check
    if metadata_path.exists() and rendered_path.exists() and rendered_path.stat().st_size > 0:
        try:
            saved_data = json.loads(metadata_path.read_text(encoding="utf-8"))
            asset = SelectedBrollAsset.model_validate(saved_data)
            logger.info(f"Reusing existing rendered B-roll asset for scene {cue.id}")
            return asset
        except Exception:
            pass

    scene_duration = max(0.1, (cue.end or 0.0) - (cue.start or 0.0))
    aspect = project.project.aspect_ratio
    target_width, target_height = aspect.to_resolution()
    fps = project.project.fps or 30

    candidates = collect_and_rank_candidates(cue, project, context)
    if not candidates:
        raise BrollAcquisitionError(
            f"No valid B-roll candidates found across all providers/queries for scene {cue.id}"
        )

    attempts = 0
    last_error: Exception | None = None

    for candidate in candidates:
        attempts += 1
        try:
            logger.info(
                f"Attempting download winner for {cue.id}: {candidate.id} "
                f"(score={candidate.score:.1f}, provider={candidate.provider})"
            )
            download_candidate(candidate, source_path)

            source_duration, trim_start, trim_end = render_scene_clip(
                source_path=source_path,
                destination_path=rendered_path,
                scene_duration=scene_duration,
                target_width=target_width,
                target_height=target_height,
                fps=fps,
            )

            selected_asset = SelectedBrollAsset(
                scene_id=cue.id,
                provider=candidate.provider,
                provider_asset_id=candidate.provider_asset_id,
                query_used=candidate.query,
                candidate_id=candidate.id,
                source_url=candidate.source_url,
                download_url=candidate.download_url,
                source_duration=source_duration,
                trim_start=trim_start,
                trim_end=trim_end,
                scene_duration=scene_duration,
                width=target_width,
                height=target_height,
                score=candidate.score,
                score_breakdown=candidate.score_breakdown,
                source_file=str(source_path.resolve()),
                rendered_file=str(rendered_path.resolve()),
                license=candidate.license,
                author=candidate.author,
                status=JobStatus.ready,
                metadata={
                    "attempts": attempts,
                    "shortlist_count": len(candidates),
                    "candidate_metadata": candidate.metadata,
                },
            )

            # Persist per-scene metadata.json
            metadata_path.write_text(
                json.dumps(selected_asset.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            context.record_selection(candidate, selected_asset)
            logger.success(f"Acquired and rendered B-roll for {cue.id}: {rendered_path.name}")
            return selected_asset

        except Exception as exc:
            logger.warning(
                f"Candidate {candidate.id} failed for scene {cue.id} (attempt {attempts}): {exc}"
            )
            last_error = exc
            continue

    raise BrollAcquisitionError(
        f"All {len(candidates)} candidates failed for scene {cue.id}. Last error: {last_error}"
    )
