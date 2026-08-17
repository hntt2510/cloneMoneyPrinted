from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models.project import NarrationMode, ProjectSpec
from app.models.schema import MaterialInfo, VideoParams


SUPPORTED_PROJECT_SCHEMA_VERSION = "1.0"


class ProjectSpecError(ValueError):
    """An actionable project-file or project-preflight error."""


def _project_path(project_path: str | os.PathLike[str]) -> Path:
    return Path(project_path).expanduser().resolve()


def load_project_spec(project_path: str | os.PathLike[str]) -> ProjectSpec:
    source = _project_path(project_path)
    try:
        with source.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    except FileNotFoundError as exc:
        raise ProjectSpecError(f"Project file not found: {source}") from exc
    except OSError as exc:
        raise ProjectSpecError(f"Unable to read project file {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectSpecError(
            f"Invalid JSON in project file {source}: {exc.msg} (line {exc.lineno}, column {exc.colno})"
        ) from exc

    if not isinstance(raw, dict):
        raise ProjectSpecError("Project file must contain a JSON object")

    version = raw.get("schema_version")
    if version != SUPPORTED_PROJECT_SCHEMA_VERSION:
        if version is None:
            raise ProjectSpecError("Project file is missing required schema_version")
        raise ProjectSpecError(f"Unsupported project schema version: {version}")

    try:
        return ProjectSpec.model_validate(raw)
    except ValidationError as exc:
        raise ProjectSpecError(f"Invalid project file: {exc}") from exc


def project_to_dict(project: ProjectSpec) -> dict[str, Any]:
    return project.model_dump(mode="json")


def validate_project_spec(value: ProjectSpec | dict[str, Any]) -> ProjectSpec:
    """Validate an already-loaded project object or JSON-compatible mapping."""
    if isinstance(value, ProjectSpec):
        return value
    try:
        return ProjectSpec.model_validate(value)
    except ValidationError as exc:
        raise ProjectSpecError(f"Invalid project file: {exc}") from exc


def serialize_project_spec(project: ProjectSpec) -> str:
    return json.dumps(project_to_dict(project), ensure_ascii=False, indent=2) + "\n"


def save_project_spec(project: ProjectSpec, destination: str | os.PathLike[str]) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialize_project_spec(project), encoding="utf-8")
    return target


def resolve_project_path(project_dir: str | os.PathLike[str], value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(project_dir) / path
    return str(path.resolve())


def _normalized_terms(value: list[str]) -> list[str]:
    return [term.strip() for term in value if term.strip()]


def project_to_video_params(
    project: ProjectSpec,
    project_dir: str | os.PathLike[str],
) -> VideoParams:
    narration = project.narration
    production = project.production
    custom_audio_file = None
    if narration.mode == NarrationMode.file:
        custom_audio_file = resolve_project_path(project_dir, narration.file or "")

    video_materials = None
    if production.video_source.value == "local":
        video_materials = [
            MaterialInfo(
                provider="local",
                url=resolve_project_path(project_dir, item),
                duration=0,
            )
            for item in production.local_materials
        ]

    return VideoParams(
        video_subject=project.script.subject,
        video_script=project.script.script,
        video_terms=_normalized_terms(project.script.search_terms),
        video_language=project.project.language,
        video_aspect=project.project.aspect_ratio,
        video_source=production.video_source,
        video_style_preset=production.video_style_preset,
        video_clip_duration=production.video_clip_duration,
        match_materials_to_script=production.match_materials_to_script,
        match_local_clips_to_script_timing=production.match_local_clips_to_script_timing,
        video_materials=video_materials,
        subtitle_enabled=production.subtitle_enabled,
        reference_mode_enabled=production.reference_mode_enabled,
        reference_image_sources=production.reference_image_sources,
        reference_image_count=production.reference_image_count,
        reference_effect_preset=production.reference_effect_preset,
        video_count=production.video_count,
        video_concat_mode=production.video_concat_mode,
        video_transition_mode=production.video_transition_mode,
        n_threads=production.n_threads,
        voice_name=narration.voice_name,
        voice_rate=narration.voice_rate,
        voice_volume=narration.voice_volume,
        custom_audio_file=custom_audio_file,
    )


def preflight_project(
    project: ProjectSpec,
    project_dir: str | os.PathLike[str],
) -> None:
    paths: list[tuple[str, str]] = []
    if project.narration.mode == NarrationMode.file:
        paths.append(("narration file", project.narration.file or ""))
    if project.narration.timing_file:
        paths.append(("narration timing file", project.narration.timing_file))
    if project.production.video_source.value == "local":
        paths.extend(
            ("local material", item) for item in project.production.local_materials
        )

    for label, value in paths:
        resolved = resolve_project_path(project_dir, value)
        if not os.path.exists(resolved):
            raise ProjectSpecError(f"Resolved {label} does not exist: {resolved}")
        if not os.path.isfile(resolved):
            raise ProjectSpecError(f"Resolved {label} is not a file: {resolved}")

    # Canonical preflight for external narration audio + timing SRT
    if (
        project.narration.mode == NarrationMode.file
        and project.narration.timing_file
        and str(project.narration.timing_file).lower().endswith(".srt")
        and project.narration.file
    ):
        audio_resolved = resolve_project_path(project_dir, project.narration.file)
        timing_resolved = resolve_project_path(project_dir, project.narration.timing_file)
        from app.services.external_narration_preflight import preflight_external_narration
        preflight = preflight_external_narration(
            audio_path=audio_resolved,
            srt_path=timing_resolved,
            script=project.script.script,
        )
        if not preflight.is_valid:
            raise ProjectSpecError(f"External narration preflight failed: {'; '.join(preflight.errors)}")


def json_safe(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    return value
