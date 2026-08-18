import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { MaskReveal, SlideIn } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { CalloutProps } from '../types';

export const CalloutTemplate: React.FC<CalloutProps> = ({
  headline, emphasis, subtext, theme: customTheme, isGrouped = false,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  // Statement reveal V2: No giant Card
  // Small eyebrow (headline) -> Emphasis phrase -> Subtext -> optional accent line
  
  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="accent_band" theme={theme} subtle_motion />
      
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '0 10%',
        textAlign: 'center',
      }}>
        {/* Eyebrow (Headline) */}
        {frame >= 0 && (
          <SlideIn startFrame={0} distance={15} direction="up">
            <div style={{
              fontSize: isPortrait ? 24 : 32, fontWeight: 700, color: theme.muted, textTransform: 'uppercase',
              letterSpacing: '0.1em', marginBottom: 24,
            }}>
              {headline}
            </div>
          </SlideIn>
        )}
        
        {/* Emphasis */}
        {emphasis && frame >= 15 && (
          <SlideIn startFrame={15} distance={20} direction="up">
            <MaskReveal startFrame={15} endFrame={25}>
              <div style={{
                fontSize: isPortrait ? 64 : 96, fontWeight: 900, color: theme.accent,
                lineHeight: 1.1, textShadow: `0 8px 32px ${theme.primary}50`,
                marginBottom: 32,
              }}>
                {emphasis}
              </div>
            </MaskReveal>
          </SlideIn>
        )}
        
        {/* Subtext */}
        {subtext && frame >= 30 && (
          <SlideIn startFrame={30} distance={15} direction="up">
            <div style={{
              fontSize: isPortrait ? 32 : 40, fontWeight: 500, color: theme.text,
              lineHeight: 1.4,
            }}>
              {subtext}
            </div>
          </SlideIn>
        )}
      </div>
    </Layout>
  );
};
