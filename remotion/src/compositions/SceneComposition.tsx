import React from 'react';
import { getTemplateComponent } from '../templates/registry';
import { SceneCompositionProps } from '../types';

export const SceneComposition: React.FC<SceneCompositionProps> = ({
  template,
  props,
  theme,
}) => {
  const Component = getTemplateComponent(template);
  return <Component {...(props || {})} theme={theme} />;
};
