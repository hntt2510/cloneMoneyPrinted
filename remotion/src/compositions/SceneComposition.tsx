import React from 'react';
import { getTemplateComponent } from '../templates/registry';
import { SceneCompositionProps } from '../types';

export const SceneComposition: React.FC<SceneCompositionProps> = ({
  template,
  props,
  theme,
}) => {
  const layoutArchetype = props?.layout_archetype;
  const Component = getTemplateComponent(template, layoutArchetype);
  return <Component {...(props || {})} theme={theme} />;
};
