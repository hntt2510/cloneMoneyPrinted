from __future__ import annotations

from typing import Any, Literal
from pydantic import ValidationError

from app.models.project import (
    NarrationMode,
    NarrationSpec,
    ProductionConfig,
    ProjectMetadata,
    ProjectSpec,
    ScriptSpec,
)
from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoSource,
    VideoTransitionMode,
)


def _resolve_aspect_ratio(value: str | VideoAspect) -> VideoAspect:
    if isinstance(value, VideoAspect):
        return value
    val_str = str(value).strip().lower()
    if val_str in ("16:9", "landscape", "横屏"):
        return VideoAspect.landscape
    if val_str in ("9:16", "portrait", "竖屏"):
        return VideoAspect.portrait
    if val_str in ("1:1", "square", "方屏"):
        return VideoAspect.square
    # Fallback to direct constructor or landscape
    try:
        return VideoAspect(str(value).strip())
    except ValueError:
        return VideoAspect.landscape


def _resolve_narration_mode(value: str | NarrationMode) -> NarrationMode:
    if isinstance(value, NarrationMode):
        return value
    val_str = str(value).strip().lower()
    if val_str in ("tts", "synthesized", "synthetic", "auto"):
        return NarrationMode.tts
    if val_str in ("file", "custom", "audio_file"):
        return NarrationMode.file
    try:
        return NarrationMode(val_str)
    except ValueError:
        return NarrationMode.tts


def _resolve_video_source(value: str | VideoSource) -> VideoSource:
    if isinstance(value, VideoSource):
        return value
    val_str = str(value).strip().lower()
    try:
        return VideoSource(val_str)
    except ValueError:
        return VideoSource.pexels


def _resolve_concat_mode(value: str | VideoConcatMode) -> VideoConcatMode:
    if isinstance(value, VideoConcatMode):
        return value
    val_str = str(value).strip().lower()
    try:
        return VideoConcatMode(val_str)
    except ValueError:
        return VideoConcatMode.random


def _resolve_transition_mode(value: str | VideoTransitionMode | None) -> VideoTransitionMode | None:
    if value is None:
        return None
    if isinstance(value, VideoTransitionMode):
        return value
    val_str = str(value).strip().lower()
    if val_str in ("none", "null", "", "no"):
        return None
    for mode in VideoTransitionMode:
        if mode.value and mode.value.lower() == val_str:
            return mode
        if mode.name.lower() == val_str:
            return mode
    return None


def build_project_spec_from_ui(
    *,
    title: str | None = None,
    subject: str,
    script: str | None = None,
    language: str = "en-US",
    aspect_ratio: str = "16:9",
    fps: int = 30,
    video_style_preset: str = "auto",
    narration_mode: str = "synthesized",
    voice_name: str = "en-US-JennyNeural-Female",
    voice_rate: float = 1.0,
    voice_volume: float = 1.0,
    subtitle_enabled: bool = True,
    video_source: str = "pexels",
    n_threads: int = 4,
    custom_audio_file: str | None = None,
    custom_timing_file: str | None = None,
    local_materials: list[str] | None = None,
    search_terms: list[str] | None = None,
    video_clip_duration: int = 5,
    match_materials_to_script: bool = False,
    match_local_clips_to_script_timing: bool = False,
    video_count: int = 1,
    video_concat_mode: str = "random",
    video_transition_mode: str = "none",
    reference_mode_enabled: bool = False,
    reference_image_sources: list[str] | None = None,
    reference_image_count: int = 1,
    reference_effect_preset: str = "none",
) -> ProjectSpec:
    """Build and validate a ProjectSpec instance from UI form inputs."""
    # Resolve title
    resolved_title = (title.strip() if title and title.strip() else subject.strip()) or "Untitled Project"

    # Resolve enums
    resolved_aspect = _resolve_aspect_ratio(aspect_ratio)
    resolved_narration_mode = _resolve_narration_mode(narration_mode)
    resolved_video_source = _resolve_video_source(video_source)
    resolved_concat_mode = _resolve_concat_mode(video_concat_mode)
    resolved_transition_mode = _resolve_transition_mode(video_transition_mode)

    # Normalize lists
    if isinstance(search_terms, str):
        resolved_search_terms = [t.strip() for t in search_terms.split(",") if t.strip()]
    else:
        resolved_search_terms = [t.strip() for t in (search_terms or []) if t and t.strip()]
    resolved_local_materials = [m.strip() for m in (local_materials or []) if m and m.strip()]
    resolved_ref_sources = [s.strip().lower() for s in (reference_image_sources or ["pexels", "pixabay", "wikimedia"]) if s and s.strip()]

    # Normalize reference effect preset (only old_paper_explained is currently supported in schema)
    resolved_ref_preset = "old_paper_explained"

    # Validate video_style_preset Literal
    valid_presets = (
        "auto",
        "stock_clean",
        "cinematic_vlog",
        "real_life_documentary",
        "minimal_business",
        "shorts_fast",
    )
    resolved_style_preset = video_style_preset if video_style_preset in valid_presets else "auto"

    project_meta = ProjectMetadata(
        title=resolved_title,
        language=language or "en-US",
        aspect_ratio=resolved_aspect,
        fps=fps,
    )

    script_spec = ScriptSpec(
        subject=subject,
        script=script or "",
        search_terms=resolved_search_terms,
    )

    narration_spec = NarrationSpec(
        mode=resolved_narration_mode,
        file=custom_audio_file.strip() if custom_audio_file and custom_audio_file.strip() else None,
        timing_file=custom_timing_file.strip() if custom_timing_file and custom_timing_file.strip() else None,
        voice_name=voice_name or "",
        voice_rate=voice_rate,
        voice_volume=voice_volume,
    )

    production_config = ProductionConfig(
        video_source=resolved_video_source,
        video_style_preset=resolved_style_preset,  # type: ignore[arg-type]
        video_clip_duration=video_clip_duration,
        match_materials_to_script=match_materials_to_script,
        match_local_clips_to_script_timing=match_local_clips_to_script_timing,
        local_materials=resolved_local_materials,
        subtitle_enabled=subtitle_enabled,
        reference_mode_enabled=reference_mode_enabled,
        reference_image_sources=resolved_ref_sources,
        reference_image_count=max(1, min(20, reference_image_count)),
        reference_effect_preset=resolved_ref_preset,  # type: ignore[arg-type]
        video_count=max(1, video_count),
        video_concat_mode=resolved_concat_mode,
        video_transition_mode=resolved_transition_mode,
        n_threads=max(1, n_threads),
    )

    return ProjectSpec(
        schema_version="1.0",
        project=project_meta,
        script=script_spec,
        narration=narration_spec,
        production=production_config,
        timeline_cues=[],
        visual_cues=[],
        asset_jobs=[],
        render_jobs=[],
    )
