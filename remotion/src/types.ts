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
  kind: "number" | "comparison_item" | "chart_item" | "milestone" | "threshold" | "takeaway" | "phrase" | "setup" | "reveal" | "grow" | "split" | "highlight" | "resolve";
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

export interface ComparisonProps extends BaseTemplateProps {
  headline: string;
  items: ComparisonItem[];
  subtext?: string | null;
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
