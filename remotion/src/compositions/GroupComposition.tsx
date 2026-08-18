import React from 'react';
import { Sequence, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { BreakdownGroupMaster } from '../templates/BreakdownTemplate';
import { getTemplateComponent } from '../templates/registry';
import { GroupCompositionProps } from '../types';

export const GroupComposition: React.FC<GroupCompositionProps> = ({
  scenes = [],
  theme,
}) => {
  const { durationInFrames } = useVideoConfig();

  if (!scenes.length) {
    return null;
  }

  // Detect if this is a continuous breakdown group
  const isBreakdownGroup = scenes.some(
    (s) =>
      s.props?.layout_archetype === 'stacked_breakdown' ||
      s.template === 'breakdown' ||
      s.props?.layout_archetype === 'breakdown'
  ) || (scenes.length >= 2 && scenes.some((s) => {
    const text = `${s.props?.headline || ''} ${s.props?.eyebrow || ''} ${s.props?.label || ''}`;
    return /repair|deductible|insurance|breakdown/i.test(text);
  }));

  if (isBreakdownGroup) {
    return (
      <Layout theme={theme} isGrouped={true}>
        <BreakdownGroupMaster
          scenes={scenes}
          theme={theme}
          durationInFrames={durationInFrames}
        />
      </Layout>
    );
  }

  // Generic sequential group composition
  const baseStartFrame = scenes[0].start_frame;

  return (
    <Layout theme={theme}>
      {scenes.map((scene, index) => {
        const relativeStart = Math.max(0, scene.start_frame - baseStartFrame);
        const Component = getTemplateComponent(scene.template, scene.props?.layout_archetype);
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
