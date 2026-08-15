import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { CounterProps, Theme } from '../types';

export const CounterTemplate: React.FC<CounterProps> = ({
  headline,
  start_value = 0,
  end_value,
  display_value,
  prefix,
  suffix,
  decimals = 0,
  label,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;
  const startFrame = isContinuous ? 0 : 5;
  const countDuration = Math.max(15, Math.round(durationInFrames * (isContinuous ? 0.8 : 0.6)));

  const progress = interpolate(frame, [startFrame, startFrame + countDuration], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const easedProgress = Math.min(1, Math.max(0, 1 - Math.pow(1 - progress, 3)));
  const currentValue = start_value + (end_value - start_value) * easedProgress;

  const formattedNum =
    decimals > 0
      ? currentValue.toFixed(decimals)
      : Math.round(currentValue).toLocaleString();

  const formattedString = `${prefix || ''}${formattedNum}${suffix || ''}`;

  const valueFontSize = isPortrait ? width * 0.16 : width * 0.085;
  const labelFontSize = isPortrait ? width * 0.045 : width * 0.024;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header headline={headline} theme={theme} isGrouped={isGrouped} isFirstInGroup={isFirstInGroup} />
      <Card
        theme={theme}
        delayFrames={3}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{ width: isPortrait ? '90%' : '65%' }}
      >
        <div
          style={{
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
            {formattedString}
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
        </div>
      </Card>
    </Layout>
  );
};
