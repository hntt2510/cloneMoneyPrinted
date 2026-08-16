from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import VisualPurpose, VisualType


class EditorPackageStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    failed = "failed"


class EditorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EditorSceneEntry(EditorModel):
    scene_id: str
    order: int
    planned_visual_type: VisualType
    resolved_visual_type: VisualType
    purpose: VisualPurpose | None = None
    start: float | None = None
    end: float | None = None
    start_frame: int
    end_frame: int
    duration_frames: int
    exported_file: str | None = None
    sha256: str | None = None
    source_stage: str | None = None
    fallback_from: VisualType | None = None
    fallback_reason: str | None = None
    provenance_reference: dict[str, Any] = Field(default_factory=dict)


class EditorSourceEntry(EditorModel):
    source_id: str
    kind: str
    title: str
    publisher: str | None = None
    trust: str | None = None
    license: str | None = None
    url: str | None = None
    local_file: str | None = None
    sha256: str | None = None
    used_in_scenes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EditManifest(EditorModel):
    schema_version: str = "1.0"
    project_title: str
    project_slug: str
    task_id: str
    source_project_fingerprint: str
    export_fingerprint: str
    package_status: EditorPackageStatus
    fps: int
    resolution: list[int]  # [width, height]
    aspect_ratio: str
    duration_frames: int
    duration_seconds: float
    narration_file: str | None = None
    narration_sha256: str | None = None
    subtitle_file: str | None = None
    subtitle_sha256: str | None = None
    missing_subtitle_reason: str | None = None
    scenes: list[EditorSceneEntry] = Field(default_factory=list)
    source_provenance: list[EditorSourceEntry] = Field(default_factory=list)
    missing_scenes: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    outputs: dict[str, Any] = Field(default_factory=dict)


class ExportResult(EditorModel):
    status: str
    task_id: str
    export_dir: str
    edit_manifest_file: str
    readme_file: str
    ready_scene_count: int
    missing_scene_count: int
    error: str | None = None
