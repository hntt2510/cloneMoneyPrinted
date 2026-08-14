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
};

export function getTemplateComponent(templateName: string): React.FC<any> {
  const normalized = (templateName || '').trim().toLowerCase();
  return templateRegistry[normalized] || CalloutTemplate;
}
