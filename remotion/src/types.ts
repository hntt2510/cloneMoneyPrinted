export interface Theme {
  background: string;
  surface: string;
  surfaceBorder: string;
  primary: string;
  accent: string;
  positive: string;
  negative: string;
  warning: string;
  text: string;
  muted: string;
  border: string;
}

export interface KineticBeat {
  id: string;
  start_frame: number;
  end_frame: number;
  kind:
    | "number"
    | "comparison_item"
    | "chart_item"
    | "milestone"
    | "threshold"
    | "takeaway"
    | "phrase"
    | "setup"
    | "reveal"
    | "grow"
    | "split"
    | "highlight"
    | "resolve"
    | "segment"
    | "arc"
    | "delta"
    | "rank"
    | "before"
    | "after"
    | "draw"
    | "step";
  text: string;
  emphasis?: boolean;
  data_ref?: string | null;
}

export interface MotionAnimationPlan {
  scene_id: string;
  beats: KineticBeat[];
  enter_preset?: string;
  exit_preset?: string;
  final_hold_frames?: number;
  timing_source?: string;
  kinetic_timing_source?: string;
  motion_engine_version?: string;
}

export type RendererFamily =
  | "standard_remotion"
  | "editorial_remotion"
  | "d3_remotion"
  | "hybrid_broll_data"
  | "diagram_remotion";

export type StorytellingTechnique =
  | "metric_punch"
  | "metric_context"
  | "metric_delta"
  | "progressive_breakdown"
  | "narrative_chart"
  | "focus_sequence"
  | "split_comparison"
  | "threshold_story"
  | "timeline_story"
  | "ranked_reveal"
  | "diagram_reveal"
  | "data_grid"
  | "kinetic_statement"
  | "hybrid_annotation"
  | "hybrid_metric"
  | "hybrid_comparison";

export type CompositionPattern =
  | "centered_hero"
  | "split_screen"
  | "flow_diagram"
  | "data_grid_matrix"
  | "timeline_track"
  | "threshold_gauge"
  | "asset_left_data_right"
  | "asset_right_data_left"
  | "asset_fullbleed_overlay"
  | "asset_center_annotation"
  | "asset_background_metric";

export type MotionPattern =
  | "punch_in"
  | "focus_step"
  | "progressive_draw"
  | "stagger_cascade"
  | "divider_reveal"
  | "camera_push"
  | "settled_hold";

export type FocusStrategy =
  | "all_visible"
  | "sequential_focus"
  | "spotlight_active"
  | "dim_inactive"
  | "zoom_active";

export type BackgroundTreatment =
  | "radial_light"
  | "soft_grid"
  | "gradient_field"
  | "spotlight"
  | "subtle_texture"
  | "asset_blur"
  | "neutral_flat";

export type InformationDensity = "low" | "medium" | "high";

export interface RendererDecision {
  renderer_family: RendererFamily;
  storytelling_technique: StorytellingTechnique;
  composition_pattern: CompositionPattern;
  motion_pattern: MotionPattern;
  focus_strategy?: FocusStrategy;
  background_treatment?: BackgroundTreatment;
  density?: InformationDensity;
  camera_motion?: string;
  asset_mode?: string;
  asset_path?: string | null;
  asset_confidence?: number;
  asset_origin?: string;
  reason?: string;
}

export interface BaseTemplateProps {
  theme?: Partial<Theme>;
  isGrouped?: boolean;
  isFirstInGroup?: boolean;
  groupSceneIndex?: number;
  animation_plan?: MotionAnimationPlan | null;
  layout_archetype?: string | null;
  storyboard_actions?: string[] | null;
  motion_style?: 'subtle' | 'standard' | 'energetic';
  motion_copy?: Record<string, string | null> | null;
  eyebrow?: string | null;
  renderer_decision?: RendererDecision | null;
}

export interface NumberProps extends BaseTemplateProps {
  headline: string;
  value: string;
  numeric_value?: number | null;
  prefix?: string | null;
  suffix?: string | null;
  label?: string | null;
  subtext?: string | null;
  eyebrow?: string | null;
  context_label?: string | null;
  delta_direction?: 'positive' | 'negative' | 'neutral' | string;
  before_value?: string | null;
  after_value?: string | null;
  delta_value?: string | null;
  delta_display?: string | null;
}

export interface CounterProps extends BaseTemplateProps {
  headline: string;
  start_value: number;
  end_value: number;
  display_value?: string | null;
  prefix?: string | null;
  suffix?: string | null;
  decimals?: number;
  label?: string | null;
  eyebrow?: string | null;
  context_label?: string | null;
}

export interface ComparisonItem {
  label: string;
  value: string;
  numeric_value?: number | null;
  highlight?: boolean;
}

export interface BreakdownTotal {
  label: string;
  value: string;
  numeric_value: number;
}

export interface BreakdownPart {
  label: string;
  value: string;
  numeric_value: number;
  highlight?: boolean;
}

export interface ComparisonProps extends BaseTemplateProps {
  headline: string;
  items: ComparisonItem[];
  subtext?: string | null;
  total?: BreakdownTotal;
  parts?: BreakdownPart[];
}

export interface TimelineItem {
  time_label: string;
  title: string;
  description?: string | null;
  is_active?: boolean;
}

export interface TimelineProps extends BaseTemplateProps {
  headline: string;
  milestones: TimelineItem[];
  highlight_index?: number | null;
}

export interface BarChartItem {
  label: string;
  value: number;
  display_value?: string | null;
  color?: string | null;
}

export interface BarChartProps extends BaseTemplateProps {
  headline: string;
  items: BarChartItem[];
  unit?: string | null;
  baseline?: number;
}

export interface LineChartPoint {
  x_label: string;
  y_value: number;
  display_value?: string | null;
}

export interface LineChartProps extends BaseTemplateProps {
  headline: string;
  points: LineChartPoint[];
  unit?: string | null;
  show_area?: boolean;
}

export interface ThresholdProps extends BaseTemplateProps {
  headline: string;
  current_value: number;
  current_display?: string | null;
  threshold_value: number;
  threshold_display?: string | null;
  threshold_label?: string;
  subtext?: string | null;
}

export interface AgeMarkerItem {
  age: number;
  label?: string | null;
  highlight?: boolean;
}

export interface AgeMarkerProps extends BaseTemplateProps {
  headline: string;
  markers: AgeMarkerItem[];
  subtext?: string | null;
}

export interface CalloutProps extends BaseTemplateProps {
  headline: string;
  emphasis?: string | null;
  subtext?: string | null;
}

export interface TextProps extends BaseTemplateProps {
  headline: string;
  subheadline?: string | null;
  style_variant?: string;
}

export interface PieSliceItem {
  label: string;
  value: number;
  display_value?: string | null;
  percentage?: number | null;
  highlight?: boolean;
  color?: string | null;
}

export interface PieProps extends BaseTemplateProps {
  headline: string;
  items: PieSliceItem[];
  total?: number | null;
  focus_label?: string | null;
  subtext?: string | null;
  variant?: "donut_reveal" | "donut_center_stat" | "pie_focus" | "segmented_ring" | string;
  eyebrow?: string | null;
}

export interface GaugeProps extends BaseTemplateProps {
  headline: string;
  current_value: number;
  max_value?: number;
  min_value?: number;
  display_value?: string | null;
  unit?: string | null;
  label?: string | null;
  subtext?: string | null;
  variant?: "radial_gauge" | "progress_ring" | "linear_meter" | string;
  eyebrow?: string | null;
}

export interface WaterfallStep {
  label: string;
  delta: number;
  display_value?: string | null;
  is_total?: boolean;
}

export interface WaterfallProps extends BaseTemplateProps {
  headline: string;
  start_value: number;
  start_label?: string;
  steps: WaterfallStep[];
  end_value: number;
  end_label?: string;
  unit?: string | null;
  variant?: "waterfall_steps" | "waterfall_variance" | string;
  eyebrow?: string | null;
}

export interface RankedListItem {
  rank: number;
  label: string;
  value?: number | null;
  display_value?: string | null;
  highlight?: boolean;
}

export interface RankedListProps extends BaseTemplateProps {
  headline: string;
  items: RankedListItem[];
  subtext?: string | null;
  variant?: "ranked_horizontal_bars" | "leaderboard_reveal" | string;
  eyebrow?: string | null;
}

export interface AreaChartProps extends BaseTemplateProps {
  headline: string;
  points: LineChartPoint[];
  unit?: string | null;
  variant?: "area_trend" | "stacked_area" | string;
  eyebrow?: string | null;
}

export interface BeforeAfterProps extends BaseTemplateProps {
  headline: string;
  before_label?: string;
  before_value: string;
  before_numeric?: number | null;
  after_label?: string;
  after_value: string;
  after_numeric?: number | null;
  delta_display?: string | null;
  subtext?: string | null;
  variant?: "split_screen" | "value_shift" | "side_by_side" | string;
  eyebrow?: string | null;
}

export interface StackedBarSegment {
  label: string;
  value: number;
  display_value?: string | null;
  highlight?: boolean;
  color?: string | null;
}

export interface StackedBarProps extends BaseTemplateProps {
  headline: string;
  total: number;
  total_display?: string | null;
  segments: StackedBarSegment[];
  variant?: "stacked_bar_reveal" | "stacked_bar_composition" | string;
  eyebrow?: string | null;
}

export interface DiagramNode {
  id: string;
  label: string;
  icon?: string | null;
  sublabel?: string | null;
  highlight?: boolean;
}

export interface DiagramEdge {
  from_node: string;
  to_node: string;
  label?: string | null;
  style?: string;
}

export interface DiagramProps extends BaseTemplateProps {
  headline: string;
  nodes: DiagramNode[];
  edges?: DiagramEdge[];
  eyebrow?: string | null;
  flow_direction?: "horizontal" | "vertical";
  subtext?: string | null;
}

export interface DataGridItem {
  label: string;
  value: string;
  numeric_value?: number | null;
  unit?: string | null;
  status?: string | null;
  subtext?: string | null;
  highlight?: boolean;
}

export interface DataGridProps extends BaseTemplateProps {
  headline: string;
  items: DataGridItem[];
  columns?: number;
  eyebrow?: string | null;
  subtext?: string | null;
}

export interface HybridAssetProps extends BaseTemplateProps {
  headline: string;
  asset_path: string;
  data_panel: Record<string, any>;
  layout?: "asset_left_data_right" | "asset_right_data_left" | "asset_fullbleed_overlay" | "asset_center_annotation" | "asset_background_metric" | string;
  eyebrow?: string | null;
  asset_mode?: "video" | "image" | string;
  asset_origin?: "user_provided" | "stock_search" | string | null;
  asset_confidence?: number | null;
  subtext?: string | null;
}

export interface SceneCompositionProps {
  scene_id: string;
  visual_type: "data" | "text";
  template: string;
  props: Record<string, any>;
  duration_in_frames: number;
  fps: number;
  width: number;
  height: number;
  theme?: Partial<Theme>;
}

export interface GroupScene {
  scene_id: string;
  visual_type: "data" | "text";
  template: string;
  props: Record<string, any>;
  start_frame: number;
  end_frame: number;
  duration_frames: number;
  animation_plan?: MotionAnimationPlan | null;
  group_scene_index?: number;
}

export interface GroupCompositionProps {
  group_id: string;
  duration_in_frames: number;
  fps: number;
  width: number;
  height: number;
  scenes: GroupScene[];
  theme?: Partial<Theme>;
}
