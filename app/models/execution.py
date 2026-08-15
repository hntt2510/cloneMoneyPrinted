from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import VisualPurpose, VisualType


class ExecutionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionStageStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    complete = "complete"
    failed = "failed"
    skipped = "skipped"


class StageExecutionRecord(ExecutionModel):
    name: str
    status: ExecutionStageStatus
    started_at: str | None = None
    completed_at: str | None = None
    input_file: str | None = None
    output_file: str | None = None
    manifest_file: str | None = None
    ready_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SceneExecutionRecord(ExecutionModel):
    scene_id: str
    order: int
    planned_visual_type: VisualType
    resolved_visual_type: VisualType
    purpose: VisualPurpose | None = None
    start: float
    end: float
    start_frame: int
    end_frame: int
    duration_frames: int
    status: str  # "ready" | "failed" | "skipped"
    output_file: str | None = None
    source_stage: str | None = None
    asset_job_id: str | None = None
    render_job_id: str | None = None
    fallback_from: VisualType | None = None
    fallback_reason: str | None = None
    attempts: int = 1
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionManifest(ExecutionModel):
    schema_version: str = "1.0"
    project_title: str
    task_id: str
    source_project_file: str
    source_project_fingerprint: str
    source_registry_sha256: str | None = None
    status: ExecutionStageStatus
    progress_percent: int = Field(default=0, ge=0, le=100)
    stages: list[StageExecutionRecord] = Field(default_factory=list)
    scenes: list[SceneExecutionRecord] = Field(default_factory=list)
    ready_scene_count: int = 0
    failed_scene_count: int = 0
    created_at: str
    updated_at: str
    error: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
