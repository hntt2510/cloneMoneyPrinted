import React from 'react';
import { Sequence } from 'remotion';
import { Layout } from '../components/Layout';
import { getTemplateComponent } from '../templates/registry';
import { GroupCompositionProps } from '../types';

export const GroupComposition: React.FC<GroupCompositionProps> = ({
  scenes = [],
  theme,
}) => {
  if (!scenes.length) {
    return null;
  }

  const baseStartFrame = scenes[0].start_frame;

  return (
    <Layout theme={theme}>
      {scenes.map((scene, index) => {
        const relativeStart = Math.max(0, scene.start_frame - baseStartFrame);
        const Component = getTemplateComponent(scene.template);
        const isFirstInGroup = index === 0;

        return (
          <Sequence
            key={scene.scene_id}
            from={relativeStart}
            durationInFrames={scene.duration_frames}
            layout="none"
          >
            <Component
              {...(scene.props || {})}
              theme={theme}
              isGrouped={true}
              isFirstInGroup={isFirstInGroup}
              groupSceneIndex={index}
            />
          </Sequence>
        );
      })}
    </Layout>
  );
};
