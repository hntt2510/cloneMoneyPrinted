import React from 'react';
import { DataSceneRouter } from '../router/DataSceneRouter';
import { TextTemplate } from '../templates/TextTemplate';
import { SceneCompositionProps } from '../types';

export const SceneComposition: React.FC<SceneCompositionProps> = ({
  template,
  props,
  theme,
}) => {
  const tpl = (template || '').trim().toLowerCase();
  if (tpl === 'text') {
    return <TextTemplate headline="" {...(props || {})} theme={theme} />;
  }

  return (
    <DataSceneRouter
      template={template}
      props={props || {}}
      theme={theme}
    />
  );
};
