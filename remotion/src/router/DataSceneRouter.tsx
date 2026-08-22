import React from 'react';
import { getTemplateComponent } from '../templates/registry';
import { Theme } from '../types';

interface DataSceneRouterProps {
  template: string;
  props: Record<string, any>;
  theme?: Partial<Theme>;
  isGrouped?: boolean;
  durationInFrames: number;
}

export const DataSceneRouter: React.FC<DataSceneRouterProps> = ({
  template,
  props,
  theme,
  isGrouped = false,
  durationInFrames,
}) => {
  const layoutArchetype = props.layout_archetype || props.renderer_decision?.composition_pattern;
  const Component = getTemplateComponent(template, layoutArchetype);

  return (
    <Component
      {...props}
      theme={theme}
      isGrouped={isGrouped}
      durationInFrames={durationInFrames}
    />
  );
};
