import React from 'react';
import { AgeMarkerTemplate } from './AgeMarkerTemplate';
import { AreaChartTemplate } from './AreaChartTemplate';
import { BarChartTemplate } from './BarChartTemplate';
import { BeforeAfterTemplate } from './BeforeAfterTemplate';
import { BreakdownTemplate } from './BreakdownTemplate';
import { CalloutTemplate } from './CalloutTemplate';
import { ComparisonTemplate } from './ComparisonTemplate';
import { CounterTemplate } from './CounterTemplate';
import { DataGridTemplate } from './DataGridTemplate';
import { DiagramTemplate } from './DiagramTemplate';
import { GaugeTemplate } from './GaugeTemplate';
import { HybridBrollTemplate } from './HybridBrollTemplate';
import { LineChartTemplate } from './LineChartTemplate';
import { MetricPunchTemplate } from './MetricPunchTemplate';
import { NumberTemplate } from './NumberTemplate';
import { PieTemplate } from './PieTemplate';
import { RankedListTemplate } from './RankedListTemplate';
import { StackedBarTemplate } from './StackedBarTemplate';
import { TextTemplate } from './TextTemplate';
import { ThresholdTemplate } from './ThresholdTemplate';
import { TimelineTemplate } from './TimelineTemplate';
import { WaterfallTemplate } from './WaterfallTemplate';

export const templateRegistry: Record<string, React.FC<any>> = {
  number: MetricPunchTemplate,
  metric_punch: MetricPunchTemplate,
  counter: CounterTemplate,
  comparison: ComparisonTemplate,
  timeline: TimelineTemplate,
  bar_chart: BarChartTemplate,
  line_chart: LineChartTemplate,
  threshold: ThresholdTemplate,
  age_marker: AgeMarkerTemplate,
  callout: CalloutTemplate,
  text: TextTemplate,
  breakdown: BreakdownTemplate,
  pie: PieTemplate,
  donut: PieTemplate,
  gauge: GaugeTemplate,
  waterfall: WaterfallTemplate,
  ranked_list: RankedListTemplate,
  area: AreaChartTemplate,
  area_chart: AreaChartTemplate,
  before_after: BeforeAfterTemplate,
  stacked_bar: StackedBarTemplate,
  diagram: DiagramTemplate,
  data_grid: DataGridTemplate,
  hybrid_broll: HybridBrollTemplate,
};

export function getTemplateComponent(templateName: string, layoutArchetype?: string): React.FC<any> {
  const normalizedTpl = (templateName || '').trim().toLowerCase();
  const normalizedLayout = (layoutArchetype || '').trim().toLowerCase();

  // Layout-first resolution for editorial components
  if (normalizedTpl === 'diagram' || normalizedLayout === 'flow_diagram' || normalizedLayout === 'diagram_reveal') {
    return DiagramTemplate;
  }
  if (normalizedTpl === 'data_grid' || normalizedLayout === 'data_grid_matrix' || normalizedLayout === 'data_grid') {
    return DataGridTemplate;
  }
  if (normalizedTpl === 'hybrid_broll' || normalizedLayout.startsWith('asset_') || normalizedLayout === 'hybrid_metric') {
    return HybridBrollTemplate;
  }
  if (normalizedLayout === 'metric_punch' || normalizedLayout === 'metric_context' || normalizedLayout === 'metric_hero') {
    return MetricPunchTemplate;
  }
  if (normalizedLayout === 'stacked_breakdown' || normalizedLayout === 'breakdown' || normalizedTpl === 'breakdown') {
    return BreakdownTemplate;
  }
  if (
    normalizedTpl === 'pie' ||
    normalizedTpl === 'donut' ||
    normalizedLayout === 'donut_center_stat' ||
    normalizedLayout === 'donut_reveal' ||
    normalizedLayout === 'pie_focus' ||
    normalizedLayout === 'segmented_ring'
  ) {
    return PieTemplate;
  }
  if (
    normalizedTpl === 'gauge' ||
    normalizedLayout === 'radial_gauge' ||
    normalizedLayout === 'progress_ring' ||
    normalizedLayout === 'linear_meter'
  ) {
    return GaugeTemplate;
  }
  if (
    normalizedTpl === 'waterfall' ||
    normalizedLayout === 'waterfall_steps' ||
    normalizedLayout === 'waterfall_variance'
  ) {
    return WaterfallTemplate;
  }
  if (
    normalizedTpl === 'ranked_list' ||
    normalizedLayout === 'ranked_horizontal_bars' ||
    normalizedLayout === 'leaderboard_reveal'
  ) {
    return RankedListTemplate;
  }
  if (
    normalizedTpl === 'area' ||
    normalizedTpl === 'area_chart' ||
    normalizedLayout === 'area_trend' ||
    normalizedLayout === 'stacked_area'
  ) {
    return AreaChartTemplate;
  }
  if (
    normalizedTpl === 'before_after' ||
    normalizedLayout === 'split_screen' ||
    normalizedLayout === 'value_shift' ||
    normalizedLayout === 'side_by_side'
  ) {
    return BeforeAfterTemplate;
  }
  if (
    normalizedTpl === 'stacked_bar' ||
    normalizedLayout === 'stacked_bar_reveal' ||
    normalizedLayout === 'stacked_bar_composition'
  ) {
    return StackedBarTemplate;
  }
  if (normalizedLayout === 'split_compare') {
    return ComparisonTemplate;
  }
  if (normalizedLayout === 'bar_chart_v2' || normalizedTpl === 'bar_chart') {
    return BarChartTemplate;
  }
  if (normalizedLayout === 'line_chart_v2' || normalizedTpl === 'line_chart') {
    return LineChartTemplate;
  }
  if (normalizedLayout === 'threshold_v2' || normalizedTpl === 'threshold') {
    return ThresholdTemplate;
  }
  if (normalizedLayout === 'timeline_v2' || normalizedTpl === 'timeline') {
    return TimelineTemplate;
  }
  if (normalizedLayout === 'kinetic_statement' || normalizedTpl === 'text') {
    return TextTemplate;
  }
  if (normalizedLayout === 'statement_reveal' || normalizedTpl === 'callout') {
    return CalloutTemplate;
  }

  return templateRegistry[normalizedTpl] || MetricPunchTemplate;
}
