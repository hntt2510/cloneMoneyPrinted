from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoSource,
    VideoTransitionMode,
)


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectMetadata(ProjectModel):
    title: str
    language: str = "en-US"
    aspect_ratio: VideoAspect = VideoAspect.landscape
    fps: int = Field(default=30, ge=1, le=120)

    @field_validator("title", "language")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ScriptSpec(ProjectModel):
    subject: str
    script: str = ""
    search_terms: list[str] = Field(default_factory=list)

    @field_validator("subject")
    @classmethod
    def require_subject(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("script")
    @classmethod
    def normalize_script(cls, value: str) -> str:
        return value.strip()

    @field_validator("search_terms")
    @classmethod
    def normalize_terms(cls, value: list[str]) -> list[str]:
        return [term.strip() for term in value if term.strip()]


class NarrationMode(str, Enum):
    tts = "tts"
    file = "file"


class NarrationSpec(ProjectModel):
    mode: NarrationMode = NarrationMode.tts
    file: str | None = None
    timing_file: str | None = None
    voice_name: str = ""
    voice_rate: float = Field(default=1.0, ge=0)
    voice_volume: float = Field(default=1.0, ge=0)

    @field_validator("file", "timing_file", "voice_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_file_mode(self) -> NarrationSpec:
        if self.mode == NarrationMode.file and not self.file:
            raise ValueError("file is required when narration mode is file")
        return self


class ProductionConfig(ProjectModel):
    video_source: VideoSource = VideoSource.pexels
    video_style_preset: Literal[
        "auto",
        "stock_clean",
        "cinematic_vlog",
        "real_life_documentary",
        "minimal_business",
        "shorts_fast",
    ] = "auto"
    video_clip_duration: int = Field(default=5, ge=1)
    match_materials_to_script: bool = True
    match_local_clips_to_script_timing: bool = False
    local_materials: list[str] = Field(default_factory=list)
    subtitle_enabled: bool = True
    reference_mode_enabled: bool = False
    reference_image_sources: list[str] = Field(
        default_factory=lambda: ["pexels", "pixabay", "wikimedia"]
    )
    reference_image_count: int = Field(default=8, ge=1, le=20)
    reference_effect_preset: Literal["old_paper_explained"] = "old_paper_explained"
    video_count: int = Field(default=1, ge=1)
    video_concat_mode: VideoConcatMode = VideoConcatMode.sequential
    video_transition_mode: VideoTransitionMode | None = None
    n_threads: int = Field(default=2, ge=1)

    @field_validator("local_materials")
    @classmethod
    def normalize_materials(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @field_validator("reference_image_sources")
    @classmethod
    def validate_reference_sources(cls, value: list[str]) -> list[str]:
        supported = {"pexels", "pixabay", "wikimedia"}
        normalized = [item.strip().lower() for item in value]
        invalid = [item for item in normalized if item not in supported]
        if invalid:
            raise ValueError(
                "reference_image_sources must contain only pexels, pixabay, or wikimedia"
            )
        return normalized

    @model_validator(mode="after")
    def validate_local_materials(self) -> ProductionConfig:
        if self.video_source == VideoSource.local and not self.local_materials:
            raise ValueError("local_materials is required when video_source is local")
        return self


class VisualType(str, Enum):
    broll = "broll"
    data = "data"
    document = "document"
    text = "text"


class VisualPurpose(str, Enum):
    context = "context"
    emotion = "emotion"
    example = "example"
    evidence = "evidence"
    explain = "explain"
    compare = "compare"
    emphasis = "emphasis"
    transition = "transition"


class DataTemplate(str, Enum):
    number = "number"
    counter = "counter"
    comparison = "comparison"
    timeline = "timeline"
    bar_chart = "bar_chart"
    line_chart = "line_chart"
    threshold = "threshold"
    age_marker = "age_marker"
    callout = "callout"


class JobStatus(str, Enum):
    planned = "planned"
    queued = "queued"
    processing = "processing"
    retrying = "retrying"
    ready = "ready"
    failed = "failed"


class BrollPayload(ProjectModel):
    search_query: str
    fallback_queries: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    source_priority: list[Literal["pexels", "pixabay", "coverr"]] = Field(
        default_factory=lambda: ["pexels", "pixabay", "coverr"]
    )

    @field_validator("search_query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("search_query must not be empty")
        if len(value) > 160:
            raise ValueError("search_query is too long")
        return value

    @field_validator("fallback_queries", "avoid")
    @classmethod
    def normalize_query_lists(cls, value: list[str]) -> list[str]:
        return [" ".join(item.split()).strip() for item in value if item.strip()]


class DataPayload(ProjectModel):
    template: DataTemplate
    headline: str
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("headline")
    @classmethod
    def validate_headline(cls, value: str) -> str:
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("headline must not be empty")
        if len(value) > 120:
            raise ValueError("headline is too long")
        return value


class DocumentPayload(ProjectModel):
    search_query: str
    source_hint: str
    highlight_target: str | None = None
    evidence_required: bool = True

    @field_validator("search_query", "source_hint", "highlight_target")
    @classmethod
    def validate_document_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("document intent text must not be empty")
        return value


class TextPayload(ProjectModel):
    headline: str
    subheadline: str | None = None

    @field_validator("headline", "subheadline")
    @classmethod
    def validate_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split()).strip()
        if not value:
            raise ValueError("text payload must not be empty")
        if len(value) > 120:
            raise ValueError("text payload is too long")
        return value


class VisualCue(ProjectModel):
    id: str
    order: int = Field(ge=1)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    narration: str = ""
    visual_type: VisualType
    purpose: VisualPurpose
    status: JobStatus = JobStatus.planned
    notes: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    visual_group_id: str | None = None

    @field_validator("id")
    @classmethod
    def require_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_timing(self) -> VisualCue:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        if self.visual_group_id is not None:
            self.visual_group_id = self.visual_group_id.strip()
            if not self.visual_group_id:
                raise ValueError("visual_group_id must not be empty")
        payload_models = {
            VisualType.broll: BrollPayload,
            VisualType.data: DataPayload,
            VisualType.document: DocumentPayload,
            VisualType.text: TextPayload,
        }
        payload_model = payload_models[self.visual_type].model_validate(self.payload)
        self.payload = payload_model.model_dump(mode="json")
        return self


class AssetJob(ProjectModel):
    id: str
    scene_id: str
    kind: str
    provider: str | None = None
    query: str | None = None
    source: str | None = None
    output: str | None = None
    status: JobStatus = JobStatus.planned
    attempts: int = Field(default=0, ge=0)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RenderJob(ProjectModel):
    id: str
    scene_id: str
    input_asset: str | None = None
    output: str | None = None
    duration: float | None = Field(default=None, ge=0)
    status: JobStatus = JobStatus.planned
    attempts: int = Field(default=0, ge=0)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimelineCue(ProjectModel):
    id: str
    order: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    narration: str

    @field_validator("id", "narration")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @model_validator(mode="after")
    def validate_timing(self) -> TimelineCue:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class TimelinePlan(ProjectModel):
    schema_version: Literal["1.0"]
    project_title: str
    audio_file: str
    timing_file: str
    duration: float = Field(ge=0)
    cues: list[TimelineCue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_cues(self) -> TimelinePlan:
        ids = [cue.id for cue in self.cues]
        orders = [cue.order for cue in self.cues]
        if len(ids) != len(set(ids)):
            raise ValueError("timeline cue ids must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("timeline cue orders must be unique")
        previous_end = 0.0
        for cue in sorted(self.cues, key=lambda item: item.order):
            if cue.start < previous_end:
                raise ValueError("timeline cues must not overlap")
            previous_end = cue.end
        return self


class VisualPlan(ProjectModel):
    schema_version: Literal["1.0"]
    project_title: str
    cues: list[VisualCue] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_visuals(self) -> VisualPlan:
        ids = [cue.id for cue in self.cues]
        orders = [cue.order for cue in self.cues]
        if len(ids) != len(set(ids)) or len(orders) != len(set(orders)):
            raise ValueError("visual cue ids and orders must be unique")
        groups: dict[str, list[int]] = {}
        for cue in sorted(self.cues, key=lambda item: item.order):
            if cue.visual_group_id:
                groups.setdefault(cue.visual_group_id, []).append(cue.order)
        for group_orders in groups.values():
            if group_orders != list(range(min(group_orders), max(group_orders) + 1)):
                raise ValueError("visual groups must refer to contiguous cues")
        return self


class ProjectSpec(ProjectModel):
    schema_version: Literal["1.0"]
    project: ProjectMetadata
    script: ScriptSpec
    narration: NarrationSpec
    production: ProductionConfig = Field(default_factory=ProductionConfig)
    timeline_cues: list[TimelineCue] = Field(default_factory=list)
    visual_cues: list[VisualCue] = Field(default_factory=list)
    asset_jobs: list[AssetJob] = Field(default_factory=list)
    render_jobs: list[RenderJob] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeline(self) -> ProjectSpec:
        ids = [cue.id for cue in self.timeline_cues]
        orders = [cue.order for cue in self.timeline_cues]
        if len(ids) != len(set(ids)):
            raise ValueError("timeline cue ids must be unique")
        if len(orders) != len(set(orders)):
            raise ValueError("timeline cue orders must be unique")
        previous_end = 0.0
        for cue in sorted(self.timeline_cues, key=lambda item: item.order):
            if cue.start < previous_end:
                raise ValueError("timeline cues must not overlap")
            previous_end = cue.end
        if self.visual_cues:
            visual_ids = [cue.id for cue in self.visual_cues]
            visual_orders = [cue.order for cue in self.visual_cues]
            if len(visual_ids) != len(set(visual_ids)):
                raise ValueError("visual cue ids must be unique")
            if len(visual_orders) != len(set(visual_orders)):
                raise ValueError("visual cue orders must be unique")
            timeline_by_id = {cue.id: cue for cue in self.timeline_cues}
            if set(visual_ids) != set(timeline_by_id):
                raise ValueError("visual cues must correspond one-to-one with timeline cues")
            for visual in self.visual_cues:
                timeline = timeline_by_id[visual.id]
                if (
                    visual.order != timeline.order
                    or visual.start != timeline.start
                    or visual.end != timeline.end
                    or visual.narration != timeline.narration
                ):
                    raise ValueError("visual cue timing and narration must match timeline")
            groups: dict[str, list[int]] = {}
            for visual in sorted(self.visual_cues, key=lambda item: item.order):
                if visual.visual_group_id:
                    groups.setdefault(visual.visual_group_id, []).append(visual.order)
            for orders_for_group in groups.values():
                if orders_for_group != list(range(min(orders_for_group), max(orders_for_group) + 1)):
                    raise ValueError("visual groups must refer to contiguous cues")
        return self


class ProjectStatus(str, Enum):
    processing = "processing"
    complete = "complete"
    failed = "failed"


class ProjectManifest(ProjectModel):
    schema_version: Literal["1.0"]
    project_title: str
    project_file: str
    task_id: str
    status: ProjectStatus
    fps: int
    aspect_ratio: VideoAspect
    created_at: datetime
    updated_at: datetime
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
