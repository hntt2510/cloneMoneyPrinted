import React from 'react';
import { Sequence } from 'remotion';
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
    <>
      {scenes.map((scene) => {
        const relativeStart = Math.max(0, scene.start_frame - baseStartFrame);
        const Component = getTemplateComponent(scene.template);

        return (
          <Sequence
            key={scene.scene_id}
            from={relativeStart}
            durationInFrames={scene.duration_frames}
          >
            <Component {...(scene.props || {})} theme={theme} />
          </Sequence>
        );
      })}
    </>
  );
};
