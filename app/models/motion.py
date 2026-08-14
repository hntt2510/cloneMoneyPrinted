from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.schema import VideoAspect

if TYPE_CHECKING:
    from app.models.project import JobStatus, ProjectStatus
else:
    try:
        from app.models.project import JobStatus, ProjectStatus
    except ImportError:
        class JobStatus(str, Enum):
            planned = "planned"
            queued = "queued"
            processing = "processing"
            retrying = "retrying"
            ready = "ready"
            failed = "failed"

        class ProjectStatus(str, Enum):
            planned = "planned"
            processing = "processing"
            complete = "complete"
            failed = "failed"


class MotionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Template Prop Models ---

class NumberProps(MotionModel):
    headline: str
    value: str
    numeric_value: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    label: str | None = None
    subtext: str | None = None

    @field_validator("headline", "value")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("must not be empty")
        return val


class CounterProps(MotionModel):
    headline: str
    start_value: float = 0.0
    end_value: float
    display_value: str | None = None
    prefix: str | None = None
    suffix: str | None = None
    decimals: int = Field(default=0, ge=0, le=5)
    label: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class ComparisonItem(MotionModel):
    label: str
    value: str
    numeric_value: float | None = None
    highlight: bool = False

    @field_validator("label", "value")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("must not be empty")
        return val


class ComparisonProps(MotionModel):
    headline: str
    items: list[ComparisonItem] = Field(min_length=2)
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class TimelineItem(MotionModel):
    time_label: str
    title: str
    description: str | None = None
    is_active: bool = False

    @field_validator("time_label", "title")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("must not be empty")
        return val


class TimelineProps(MotionModel):
    headline: str
    milestones: list[TimelineItem] = Field(min_length=2)
    highlight_index: int | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class BarChartItem(MotionModel):
    label: str
    value: float
    display_value: str | None = None
    color: str | None = None

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("label must not be empty")
        return val


class BarChartProps(MotionModel):
    headline: str
    items: list[BarChartItem] = Field(min_length=2)
    unit: str | None = None
    baseline: float = 0.0

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class LineChartPoint(MotionModel):
    x_label: str
    y_value: float
    display_value: str | None = None

    @field_validator("x_label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("x_label must not be empty")
        return val


class LineChartProps(MotionModel):
    headline: str
    points: list[LineChartPoint] = Field(min_length=2)
    unit: str | None = None
    show_area: bool = True

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class ThresholdProps(MotionModel):
    headline: str
    current_value: float
    current_display: str | None = None
    threshold_value: float
    threshold_display: str | None = None
    threshold_label: str = "Threshold"
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class AgeMarkerItem(MotionModel):
    age: int = Field(ge=0, le=150)
    label: str | None = None
    highlight: bool = False


class AgeMarkerProps(MotionModel):
    headline: str
    markers: list[AgeMarkerItem] = Field(min_length=1)
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class CalloutProps(MotionModel):
    headline: str
    emphasis: str | None = None
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class TextProps(MotionModel):
    headline: str
    subheadline: str | None = None
    style_variant: str = "bold"

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


# --- Spec & Manifest Models ---

class MotionSceneSpec(MotionModel):
    scene_id: str
    order: int = Field(ge=1)
    visual_type: Literal["data", "text"]
    requested_template: str
    rendered_template: str
    fallback_reason: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    duration_frames: int = Field(ge=1)
    fps: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    visual_group_id: str | None = None


class MotionGroupSpec(MotionModel):
    group_id: str
    scene_ids: list[str] = Field(min_length=1)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    duration_frames: int = Field(ge=1)
    fps: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    scenes: list[MotionSceneSpec] = Field(min_length=1)


class RenderedMotionAsset(MotionModel):
    scene_id: str
    visual_type: Literal["data", "text"]
    requested_template: str
    rendered_template: str
    fallback_reason: str | None = None
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    duration_frames: int = Field(ge=1)
    fps: int = Field(ge=1)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    output_file: str
    visual_group_id: str | None = None
    group_master_file: str | None = None
    status: JobStatus = JobStatus.ready
    metadata: dict[str, Any] = Field(default_factory=dict)


class MotionManifest(MotionModel):
    schema_version: Literal["1.0"] = "1.0"
    project_title: str
    task_id: str
    status: ProjectStatus = ProjectStatus.complete
    assets: list[RenderedMotionAsset] = Field(default_factory=list)
    failed_scenes: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error: str | None = None
