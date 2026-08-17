import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { CalloutProps, Theme } from '../types';

export const CalloutTemplate: React.FC<CalloutProps> = ({
  headline,
  emphasis,
  subtext,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
  animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;

  let empStart = isContinuous ? 0 : 5;
  let subStart = isContinuous ? 0 : 15;

  if (animation_plan?.beats) {
    const tBeats = animation_plan.beats.filter(b => b.kind === 'takeaway');
    if (tBeats.length > 0) {
      empStart = tBeats[0].start_frame;
      subStart = tBeats.length > 1 ? tBeats[1].start_frame : empStart + 10;
    }
  }

  const empSpr = spring({
    frame: Math.max(0, frame - empStart),
    fps,
    config: { damping: 13, stiffness: 90, mass: 0.85 },
  });
  
  const subSpr = spring({
    frame: Math.max(0, frame - subStart),
    fps,
    config: { damping: 13, stiffness: 90, mass: 0.85 },
  });

  const empScale = isContinuous ? 1 : interpolate(empSpr, [0, 1], [0.9, 1]);
  const empOpacity = isContinuous ? 1 : interpolate(empSpr, [0, 1], [0, 1]);
  const subOpacity = isContinuous ? 1 : interpolate(subSpr, [0, 1], [0, 1]);

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header headline={headline} theme={theme} isGrouped={isGrouped} isFirstInGroup={isFirstInGroup} />
      <Card
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{
          width: isPortrait ? '92%' : '75%',
          padding: `${Math.round(height * 0.04)}px ${Math.round(width * 0.04)}px`,
        }}
      >
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
          }}
        >
          {emphasis && (
            <div
              style={{
                opacity: empOpacity,
                transform: `scale(${empScale})`,
                backgroundColor: `${theme.primary}20`,
                border: `2px solid ${theme.accent}`,
                borderRadius: 16,
                padding: '18px 36px',
                fontSize: Math.min(56, Math.max(24, Math.round(isPortrait ? width * 0.075 : width * 0.042))),
                fontWeight: 900,
                color: theme.accent,
                letterSpacing: '-0.02em',
                lineHeight: 1.2,
                boxShadow: `0 8px 32px ${theme.primary}25`,
                wordBreak: 'break-word',
              }}
            >
              {emphasis}
            </div>
          )}
          {subtext && (
            <div
              style={{
                opacity: subOpacity,
                marginTop: emphasis ? 20 : 0,
                fontSize: Math.min(32, Math.max(16, Math.round(isPortrait ? width * 0.045 : width * 0.024))),
                fontWeight: 500,
                color: theme.muted,
                lineHeight: 1.4,
                maxWidth: '90%',
              }}
            >
              {subtext}
            </div>
          )}
        </div>
      </Card>
    </Layout>
  );
};
