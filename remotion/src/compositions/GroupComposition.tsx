import React from 'react';
import { Sequence, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { BreakdownGroupMaster, resolveBreakdownData } from '../templates/BreakdownTemplate';
import { ComparisonGroupMaster } from '../templates/ComparisonTemplate';
import { ThresholdGroupMaster } from '../templates/ThresholdTemplate';
import { TimelineGroupMaster } from '../templates/TimelineTemplate';
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

  // 1. Detect if this is an explicit breakdown group with valid grounded data
  const hasBreakdownArchetype = scenes.some(
    (s) =>
      s.props?.layout_archetype === 'stacked_breakdown' ||
      s.template === 'breakdown' ||
      s.props?.layout_archetype === 'breakdown'
  );

  const breakdownData = hasBreakdownArchetype
    ? resolveBreakdownData({ scenes, ...(scenes[0]?.props || {}) })
    : null;

  if (hasBreakdownArchetype && breakdownData) {
    return (
      <Layout theme={theme} isGrouped={true}>
        <BreakdownGroupMaster
          scenes={scenes}
          theme={theme}
          durationInFrames={durationInFrames}
          breakdownData={breakdownData}
        />
      </Layout>
    );
  }

  // 2. Detect if this is a multi-cue threshold group
  const isThresholdGroup =
    scenes.length >= 2 &&
    scenes.every(
      (s) =>
        s.template === 'threshold' ||
        s.props?.layout_archetype === 'threshold_v2' ||
        s.props?.layout_archetype === 'threshold'
    );

  if (isThresholdGroup) {
    return (
      <Layout theme={theme} isGrouped={true}>
        <ThresholdGroupMaster
          scenes={scenes}
          theme={theme}
          durationInFrames={durationInFrames}
        />
      </Layout>
    );
  }

  // 3. Detect if this is a multi-cue comparison group
  const isComparisonGroup =
    scenes.length >= 2 &&
    scenes.every(
      (s) =>
        s.template === 'comparison' ||
        s.props?.layout_archetype === 'split_compare' ||
        s.props?.layout_archetype === 'comparison'
    );

  if (isComparisonGroup) {
    return (
      <Layout theme={theme} isGrouped={true}>
        <ComparisonGroupMaster
          scenes={scenes}
          theme={theme}
          durationInFrames={durationInFrames}
        />
      </Layout>
    );
  }

  // 4. Detect if this is a multi-cue timeline group
  const isTimelineGroup =
    scenes.length >= 2 &&
    scenes.every(
      (s) =>
        s.template === 'timeline' ||
        s.props?.layout_archetype === 'timeline_v2' ||
        s.props?.layout_archetype === 'timeline'
    );

  if (isTimelineGroup) {
    return (
      <Layout theme={theme} isGrouped={true}>
        <TimelineGroupMaster
          scenes={scenes}
          theme={theme}
          durationInFrames={durationInFrames}
        />
      </Layout>
    );
  }

  // 5. Generic sequential group composition
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
              animation_plan={scene.animation_plan || scene.props?.animation_plan}
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
