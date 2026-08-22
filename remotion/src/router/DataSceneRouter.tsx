import React from 'react';
import { AreaChartTemplate } from '../templates/AreaChartTemplate';
import { BarChartTemplate } from '../templates/BarChartTemplate';
import { BreakdownTemplate } from '../templates/BreakdownTemplate';
import { ComparisonTemplate } from '../templates/ComparisonTemplate';
import { DataGridTemplate } from '../templates/DataGridTemplate';
import { DiagramTemplate } from '../templates/DiagramTemplate';
import { GaugeTemplate } from '../templates/GaugeTemplate';
import { HybridBrollTemplate } from '../templates/HybridBrollTemplate';
import { LineChartTemplate } from '../templates/LineChartTemplate';
import { MetricPunchTemplate } from '../templates/MetricPunchTemplate';
import { PieTemplate } from '../templates/PieTemplate';
import { RankedListTemplate } from '../templates/RankedListTemplate';
import { ThresholdTemplate } from '../templates/ThresholdTemplate';
import { TimelineTemplate } from '../templates/TimelineTemplate';
import { WaterfallTemplate } from '../templates/WaterfallTemplate';
import { getTemplateComponent } from '../templates/registry';
import { Theme } from '../types';

export function resolveDataComponent(
  template: string,
  props: Record<string, any>
): React.FC<any> {
  const decision = props.renderer_decision;
  const family = decision?.renderer_family;
  const technique = decision?.storytelling_technique;
  const pattern = decision?.composition_pattern;
  const layout = props.layout_archetype || pattern;
  const tpl = (template || '').trim().toLowerCase();

  // 1. Decision-first routing by RendererFamily and StorytellingTechnique
  if (family === 'diagram_remotion' || technique === 'diagram_reveal' || tpl === 'diagram') {
    return DiagramTemplate;
  }

  if (technique === 'data_grid' || pattern === 'data_grid_matrix' || tpl === 'data_grid') {
    return DataGridTemplate;
  }

  if (
    family === 'hybrid_broll_data' ||
    technique === 'hybrid_metric' ||
    technique === 'hybrid_comparison' ||
    technique === 'hybrid_annotation' ||
    tpl === 'hybrid_broll'
  ) {
    return HybridBrollTemplate;
  }

  if (family === 'editorial_remotion') {
    if (technique === 'metric_punch' || technique === 'metric_context' || technique === 'metric_delta') {
      return MetricPunchTemplate;
    }
    if (technique === 'split_comparison') {
      return ComparisonTemplate;
    }
    if (technique === 'threshold_story') {
      return ThresholdTemplate;
    }
    if (technique === 'timeline_story') {
      return TimelineTemplate;
    }
    if (technique === 'progressive_breakdown') {
      return BreakdownTemplate;
    }
    if (technique === 'ranked_reveal') {
      return RankedListTemplate;
    }
  }

  if (family === 'd3_remotion') {
    if (tpl === 'pie' || tpl === 'donut' || (technique === 'narrative_chart' && (tpl === 'pie' || tpl === 'donut'))) {
      return PieTemplate;
    }
    if (tpl === 'bar_chart' || technique === 'focus_sequence') {
      return BarChartTemplate;
    }
    if (tpl === 'line_chart') {
      return LineChartTemplate;
    }
    if (tpl === 'area' || tpl === 'area_chart') {
      return AreaChartTemplate;
    }
    if (tpl === 'gauge') {
      return GaugeTemplate;
    }
    if (tpl === 'waterfall') {
      return WaterfallTemplate;
    }
  }

  // 2. Semantic template & layout archetype fallback
  return getTemplateComponent(template, layout);
}

interface DataSceneRouterProps {
  template: string;
  props: Record<string, any>;
  theme?: Partial<Theme>;
  isGrouped?: boolean;
  durationInFrames?: number;
  [key: string]: any;
}

export const DataSceneRouter: React.FC<DataSceneRouterProps> = ({
  template,
  props,
  theme,
  isGrouped = false,
  durationInFrames,
  ...rest
}) => {
  const Component = resolveDataComponent(template, props || {});

  return (
    <Component
      {...(props || {})}
      {...rest}
      theme={theme}
      isGrouped={isGrouped}
      durationInFrames={durationInFrames}
    />
  );
};
