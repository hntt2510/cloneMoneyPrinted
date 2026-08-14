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

export interface NumberProps {
  headline: string;
  value: string;
  numeric_value?: number | null;
  prefix?: string | null;
  suffix?: string | null;
  label?: string | null;
  subtext?: string | null;
}

export interface CounterProps {
  headline: string;
  start_value: number;
  end_value: number;
  display_value?: string | null;
  prefix?: string | null;
  suffix?: string | null;
  decimals?: number;
  label?: string | null;
}

export interface ComparisonItem {
  label: string;
  value: string;
  numeric_value?: number | null;
  highlight?: boolean;
}

export interface ComparisonProps {
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

export interface TimelineProps {
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

export interface BarChartProps {
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

export interface LineChartProps {
  headline: string;
  points: LineChartPoint[];
  unit?: string | null;
  show_area?: boolean;
}

export interface ThresholdProps {
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

export interface AgeMarkerProps {
  headline: string;
  markers: AgeMarkerItem[];
  subtext?: string | null;
}

export interface CalloutProps {
  headline: string;
  emphasis?: string | null;
  subtext?: string | null;
}

export interface TextProps {
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
