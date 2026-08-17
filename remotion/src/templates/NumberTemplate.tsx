import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { NumberProps, Theme } from '../types';

export const NumberTemplate: React.FC<NumberProps> = ({
  headline,
  value,
  prefix,
  suffix,
  label,
  subtext,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
  animation_plan,
  numeric_value,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;

  const spr = spring({
    frame: Math.max(0, frame - 5),
    fps,
    config: { damping: 12, stiffness: 90, mass: 0.8 },
  });

  const numberScale = isContinuous ? 1 : interpolate(spr, [0, 1], [0.85, 1]);
  const numberOpacity = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);

  const valueFontSize = isPortrait ? width * 0.16 : width * 0.085;
  const labelFontSize = isPortrait ? width * 0.045 : width * 0.024;

  let displayString = `${prefix || ''}${value}${suffix || ''}`;
  let finalScale = numberScale;

  if (numeric_value !== null && numeric_value !== undefined && animation_plan?.beats) {
    const numBeat = animation_plan.beats.find((b) => b.kind === 'number') || animation_plan.beats[0];
    if (numBeat) {
      const p = interpolate(
        frame,
        [numBeat.start_frame, numBeat.end_frame],
        [0, 1],
        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
      );
      const easeP = spring({
        frame: p * fps,
        fps,
        config: { damping: 14, stiffness: 45 },
      });
      const currentValue = easeP * numeric_value;
      const decimals = value.includes('.') ? value.split('.')[1].length : 0;
      
      const formatted = currentValue.toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      });
      displayString = `${prefix || ''}${formatted}${suffix || ''}`;

      const popSpr = spring({
        frame: Math.max(0, frame - numBeat.end_frame),
        fps,
        config: { damping: 12, stiffness: 120 },
      });
      const popBoost = interpolate(popSpr, [0, 0.5, 1], [0, 0.05, 0]);
      finalScale = numberScale * (1 + popBoost);

      if (frame >= numBeat.end_frame) {
        displayString = `${prefix || ''}${value}${suffix || ''}`; // Exact target at end
      }
    }
  }

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header headline={headline} theme={theme} isGrouped={isGrouped} isFirstInGroup={isFirstInGroup} />
      <Card
        theme={theme}
        delayFrames={4}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{ width: isPortrait ? '90%' : '65%' }}
      >
        <div
          style={{
            opacity: numberOpacity,
            transform: `scale(${finalScale})`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              fontSize: Math.min(140, Math.max(48, Math.round(valueFontSize))),
              fontWeight: 900,
              color: theme.accent,
              letterSpacing: '-0.03em',
              lineHeight: 1.05,
              textShadow: `0 8px 32px ${theme.primary}40`,
            }}
          >
            {displayString}
          </div>
          {label && (
            <div
              style={{
                marginTop: Math.round(height * 0.015),
                fontSize: Math.min(36, Math.max(18, Math.round(labelFontSize))),
                fontWeight: 600,
                color: theme.text,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {label}
            </div>
          )}
          {subtext && (
            <div
              style={{
                marginTop: Math.round(height * 0.01),
                fontSize: Math.min(24, Math.max(14, Math.round(labelFontSize * 0.8))),
                fontWeight: 400,
                color: theme.muted,
                textAlign: 'center',
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
