import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { MaskReveal, SlideIn, ScalePop } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { TextProps } from '../types';

export const TextTemplate: React.FC<TextProps> = ({
  headline, theme: customTheme, isGrouped = false, animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const beats = animation_plan?.beats ?? [{ id: '1', start_frame: 0, end_frame: 90, kind: 'phrase', text: headline, emphasis: true }];
  
  // Kinetic statement V2 Layout:
  // Render each beat sequentially as it appears. Emphasized phrases get larger font/accent color.
  
  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="radial_light" theme={theme} subtle_motion />
      
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '10%',
        gap: 16,
      }}>
        {beats.map((beat, idx) => {
          if (frame < beat.start_frame) return null;
          
          const isEmphasis = beat.emphasis;
          const fontSize = isPortrait ? (isEmphasis ? 64 : 36) : (isEmphasis ? 84 : 48);
          const color = isEmphasis ? theme.accent : theme.text;
          const fontWeight = isEmphasis ? 900 : 600;
          
          return (
            <SlideIn key={idx} startFrame={beat.start_frame} distance={20}>
              <MaskReveal startFrame={beat.start_frame} endFrame={beat.start_frame + 10}>
                {isEmphasis ? (
                  <ScalePop startFrame={beat.start_frame} boost={0.05}>
                    <div style={{ fontSize, color, fontWeight, textAlign: 'center', lineHeight: 1.1 }}>
                      {beat.text}
                    </div>
                  </ScalePop>
                ) : (
                  <div style={{ fontSize, color, fontWeight, textAlign: 'center', lineHeight: 1.2 }}>
                    {beat.text}
                  </div>
                )}
              </MaskReveal>
            </SlideIn>
          );
        })}
      </div>
    </Layout>
  );
};
