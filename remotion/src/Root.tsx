import React from 'react';
import { Composition } from 'remotion';
import { GroupComposition } from './compositions/GroupComposition';
import { SceneComposition } from './compositions/SceneComposition';
import { GroupCompositionProps, SceneCompositionProps } from './types';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition<any, any>
        id="Scene"
        component={SceneComposition}
        durationInFrames={150}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={
          {
            scene_id: 'default',
            visual_type: 'data',
            template: 'callout',
            props: { headline: 'Preview' },
            duration_in_frames: 150,
            fps: 30,
            width: 1920,
            height: 1080,
          } as SceneCompositionProps
        }
        calculateMetadata={({ props }) => {
          return {
            durationInFrames: Math.max(1, Number(props.duration_in_frames) || 150),
            fps: Number(props.fps) || 30,
            width: Number(props.width) || 1920,
            height: Number(props.height) || 1080,
          };
        }}
      />
      <Composition<any, any>
        id="Group"
        component={GroupComposition}
        durationInFrames={300}
        fps={30}
        width={1920}
        height={1080}
        defaultProps={
          {
            group_id: 'default_group',
            duration_in_frames: 300,
            fps: 30,
            width: 1920,
            height: 1080,
            scenes: [],
          } as GroupCompositionProps
        }
        calculateMetadata={({ props }) => {
          return {
            durationInFrames: Math.max(1, Number(props.duration_in_frames) || 300),
            fps: Number(props.fps) || 30,
            width: Number(props.width) || 1920,
            height: Number(props.height) || 1080,
          };
        }}
      />
    </>
  );
};
