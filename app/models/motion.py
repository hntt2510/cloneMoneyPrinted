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


# --- Kinetic Timing Models ---

class KineticBeatKind(str, Enum):
    number = "number"
    comparison_item = "comparison_item"
    chart_item = "chart_item"
    milestone = "milestone"
    threshold = "threshold"
    takeaway = "takeaway"
    phrase = "phrase"
    setup = "setup"
    reveal = "reveal"
    grow = "grow"
    split = "split"
    highlight = "highlight"
    resolve = "resolve"
    segment = "segment"
    arc = "arc"
    delta = "delta"
    rank = "rank"
    before = "before"
    after = "after"
    draw = "draw"
    step = "step"


class KineticBeat(BaseModel):
    id: str
    start_frame: int
    end_frame: int
    kind: KineticBeatKind
    text: str
    emphasis: bool = False
    data_ref: str | None = None


class MotionAnimationPlan(BaseModel):
    scene_id: str
    beats: list[KineticBeat]
    enter_preset: str = "fade_in"
    exit_preset: str = "fade_out"
    final_hold_frames: int = 15
    timing_source: str = "auto"
    kinetic_timing_source: str = "auto"
    motion_engine_version: str = "3"


# --- Template Prop Models ---

class NumberProps(MotionModel):
    headline: str
    value: str
    numeric_value: float | None = None
    prefix: str | None = None
    suffix: str | None = None
    label: str | None = None
    subtext: str | None = None
    eyebrow: str | None = None
    context_label: str | None = None
    delta_direction: str | None = None
    delta_sentiment: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    delta_value: str | None = None
    delta_display: str | None = None

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
    eyebrow: str | None = None
    context_label: str | None = None

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


# --- G17 Semantic Data Visualization Models ---

class SemanticDataIntent(str, Enum):
    single_metric = "single_metric"
    part_to_whole = "part_to_whole"
    category_comparison = "category_comparison"
    ranked_categories = "ranked_categories"
    trend_over_time = "trend_over_time"
    change_over_time = "change_over_time"
    composition_over_time = "composition_over_time"
    threshold = "threshold"
    progress = "progress"
    breakdown = "breakdown"
    before_after = "before_after"
    sequence = "sequence"
    distribution = "distribution"
    positive_negative_change = "positive_negative_change"
    two_dimension_relationship = "two_dimension_relationship"
    takeaway = "takeaway"


class VisualGrammar(str, Enum):
    metric = "metric"
    comparison = "comparison"
    breakdown = "breakdown"
    bar = "bar"
    stacked_bar = "stacked_bar"
    line = "line"
    area = "area"
    pie = "pie"
    donut = "donut"
    threshold = "threshold"
    gauge = "gauge"
    timeline = "timeline"
    waterfall = "waterfall"
    ranked_list = "ranked_list"
    before_after = "before_after"
    kinetic_statement = "kinetic_statement"
    diagram = "diagram"
    data_grid = "data_grid"
    hybrid_broll = "hybrid_broll"


# --- G19 Adaptive Visual Renderer Models ---

class RendererFamily(str, Enum):
    standard_remotion = "standard_remotion"
    editorial_remotion = "editorial_remotion"
    d3_remotion = "d3_remotion"
    hybrid_broll_data = "hybrid_broll_data"
    diagram_remotion = "diagram_remotion"


class StorytellingTechnique(str, Enum):
    metric_punch = "metric_punch"
    metric_context = "metric_context"
    metric_delta = "metric_delta"
    progressive_breakdown = "progressive_breakdown"
    narrative_chart = "narrative_chart"
    focus_sequence = "focus_sequence"
    split_comparison = "split_comparison"
    threshold_story = "threshold_story"
    timeline_story = "timeline_story"
    ranked_reveal = "ranked_reveal"
    diagram_reveal = "diagram_reveal"
    data_grid = "data_grid"
    kinetic_statement = "kinetic_statement"
    hybrid_annotation = "hybrid_annotation"
    hybrid_metric = "hybrid_metric"
    hybrid_comparison = "hybrid_comparison"


class CompositionPattern(str, Enum):
    centered_hero = "centered_hero"
    split_screen = "split_screen"
    flow_diagram = "flow_diagram"
    data_grid_matrix = "data_grid_matrix"
    timeline_track = "timeline_track"
    threshold_gauge = "threshold_gauge"
    asset_left_data_right = "asset_left_data_right"
    asset_right_data_left = "asset_right_data_left"
    asset_fullbleed_overlay = "asset_fullbleed_overlay"
    asset_center_annotation = "asset_center_annotation"
    asset_background_metric = "asset_background_metric"


class MotionPattern(str, Enum):
    punch_in = "punch_in"
    focus_step = "focus_step"
    progressive_draw = "progressive_draw"
    stagger_cascade = "stagger_cascade"
    divider_reveal = "divider_reveal"
    camera_push = "camera_push"
    settled_hold = "settled_hold"


class FocusStrategy(str, Enum):
    all_visible = "all_visible"
    sequential_focus = "sequential_focus"
    spotlight_active = "spotlight_active"
    dim_inactive = "dim_inactive"
    zoom_active = "zoom_active"


class BackgroundTreatment(str, Enum):
    radial_light = "radial_light"
    soft_grid = "soft_grid"
    gradient_field = "gradient_field"
    spotlight = "spotlight"
    subtle_texture = "subtle_texture"
    asset_blur = "asset_blur"
    neutral_flat = "neutral_flat"


class InformationDensity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class RendererDecision(MotionModel):
    renderer_family: RendererFamily
    storytelling_technique: StorytellingTechnique
    composition_pattern: CompositionPattern
    motion_pattern: MotionPattern
    focus_strategy: FocusStrategy = FocusStrategy.all_visible
    background_treatment: BackgroundTreatment = BackgroundTreatment.radial_light
    density: InformationDensity = InformationDensity.medium
    camera_motion: str = "subtle_push"
    asset_mode: str = "none"
    asset_path: str | None = None
    asset_confidence: float | None = None
    asset_origin: str = "none"
    asset_score_source: str | None = None
    reason: str = ""


class DiagramNode(MotionModel):
    id: str
    label: str
    icon: str | None = None
    sublabel: str | None = None
    highlight: bool = False


class DiagramEdge(MotionModel):
    from_node: str
    to_node: str
    label: str | None = None
    style: str = "solid"


class DiagramProps(MotionModel):
    headline: str
    nodes: list[DiagramNode] = Field(min_length=2, max_length=6)
    edges: list[DiagramEdge] = Field(default_factory=list)
    eyebrow: str | None = None
    flow_direction: str = "horizontal"
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class DataGridItem(MotionModel):
    label: str
    value: str
    numeric_value: float | None = None
    unit: str | None = None
    status: str | None = None
    subtext: str | None = None
    highlight: bool = False


class DataGridProps(MotionModel):
    headline: str
    items: list[DataGridItem] = Field(min_length=3, max_length=6)
    columns: int = 2
    eyebrow: str | None = None
    subtext: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class HybridAssetProps(MotionModel):
    headline: str
    asset_path: str
    data_panel: dict[str, Any] = Field(default_factory=dict)
    layout: str = "asset_left_data_right"
    eyebrow: str | None = None
    asset_mode: str = "video"
    asset_origin: str | None = None
    asset_confidence: float | None = None
    subtext: str | None = None

    @field_validator("headline", "asset_path")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("must not be empty")
        return val


class PieSliceItem(MotionModel):
    label: str
    value: float
    display_value: str | None = None
    percentage: float | None = None
    highlight: bool = False
    color: str | None = None

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("label must not be empty")
        return val


class PieProps(MotionModel):
    headline: str
    items: list[PieSliceItem] = Field(min_length=2, max_length=8)
    total: float | None = None
    focus_label: str | None = None
    subtext: str | None = None
    variant: str = "donut_center_stat"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


DonutProps = PieProps


class GaugeProps(MotionModel):
    headline: str
    current_value: float
    max_value: float = 100.0
    min_value: float = 0.0
    display_value: str | None = None
    unit: str | None = None
    label: str | None = None
    subtext: str | None = None
    variant: str = "radial_gauge"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class WaterfallStep(MotionModel):
    label: str
    delta: float
    display_value: str | None = None
    is_total: bool = False

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("label must not be empty")
        return val


class WaterfallProps(MotionModel):
    headline: str
    start_value: float
    start_label: str = "Starting"
    steps: list[WaterfallStep] = Field(min_length=1)
    end_value: float
    end_label: str = "Final"
    unit: str | None = None
    variant: str = "waterfall_steps"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class RankedListItem(MotionModel):
    rank: int = Field(ge=1)
    label: str
    value: float | None = None
    display_value: str | None = None
    highlight: bool = False

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("label must not be empty")
        return val


class RankedListProps(MotionModel):
    headline: str
    items: list[RankedListItem] = Field(min_length=2, max_length=7)
    subtext: str | None = None
    variant: str = "ranked_horizontal_bars"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class AreaChartProps(MotionModel):
    headline: str
    points: list[LineChartPoint] = Field(min_length=2)
    unit: str | None = None
    variant: str = "area_trend"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class BeforeAfterProps(MotionModel):
    headline: str
    before_label: str = "Before"
    before_value: str
    before_numeric: float | None = None
    after_label: str = "After"
    after_value: str
    after_numeric: float | None = None
    delta_display: str | None = None
    subtext: str | None = None
    variant: str = "split_screen"
    eyebrow: str | None = None

    @field_validator("headline", "before_value", "after_value")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("must not be empty")
        return val


class StackedBarSegment(MotionModel):
    label: str
    value: float
    display_value: str | None = None
    highlight: bool = False
    color: str | None = None

    @field_validator("label")
    @classmethod
    def require_label(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("label must not be empty")
        return val


class StackedBarProps(MotionModel):
    headline: str
    total: float
    total_display: str | None = None
    segments: list[StackedBarSegment] = Field(min_length=2)
    variant: str = "stacked_bar_reveal"
    eyebrow: str | None = None

    @field_validator("headline")
    @classmethod
    def require_headline(cls, value: str) -> str:
        val = value.strip()
        if not val:
            raise ValueError("headline must not be empty")
        return val


class DataVisualizationSpec(MotionModel):
    intent: SemanticDataIntent
    grammar: VisualGrammar
    variant: str
    headline: str
    eyebrow: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)
    grounded_values: list[float] = Field(default_factory=list)
    grounded_labels: list[str] = Field(default_factory=list)
    source_cue_ids: list[str] = Field(default_factory=list)
    provenance: str = "narration_extracted"
    confidence: float = 1.0


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
    animation_plan: MotionAnimationPlan | None = None
    layout_archetype: str = "default"
    storyboard_actions: list[str] = Field(default_factory=list)
    motion_style: str = "standard"
    motion_copy: dict[str, Any] = Field(default_factory=dict)
    data_intent: SemanticDataIntent | None = None
    visual_grammar: VisualGrammar | None = None
    grounded_facts: list[dict[str, Any]] = Field(default_factory=list)
    renderer_decision: RendererDecision | None = None


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
