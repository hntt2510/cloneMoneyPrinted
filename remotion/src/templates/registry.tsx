import React from 'react';
import { AgeMarkerTemplate } from './AgeMarkerTemplate';
import { BarChartTemplate } from './BarChartTemplate';
import { CalloutTemplate } from './CalloutTemplate';
import { ComparisonTemplate } from './ComparisonTemplate';
import { CounterTemplate } from './CounterTemplate';
import { LineChartTemplate } from './LineChartTemplate';
import { NumberTemplate } from './NumberTemplate';
import { TextTemplate } from './TextTemplate';
import { ThresholdTemplate } from './ThresholdTemplate';
import { TimelineTemplate } from './TimelineTemplate';
import { BreakdownTemplate } from './BreakdownTemplate';

export const templateRegistry: Record<string, React.FC<any>> = {
  number: NumberTemplate,
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
};

export function getTemplateComponent(templateName: string, layoutArchetype?: string): React.FC<any> {
  const normalizedTpl = (templateName || '').trim().toLowerCase();
  const normalizedLayout = (layoutArchetype || '').trim().toLowerCase();

  // Layout-first resolution for editorial components
  if (normalizedLayout === 'stacked_breakdown' || normalizedLayout === 'breakdown' || normalizedTpl === 'breakdown') {
    return BreakdownTemplate;
  }
  if (normalizedLayout === 'split_compare') {
    return ComparisonTemplate;
  }
  if (normalizedLayout === 'metric_hero') {
    return NumberTemplate;
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

  return templateRegistry[normalizedTpl] || CalloutTemplate;
}
