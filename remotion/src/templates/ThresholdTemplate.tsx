import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { Theme, ThresholdProps } from '../types';

export const ThresholdTemplate: React.FC<ThresholdProps> = ({
  headline,
  current_value,
  current_display,
  threshold_value,
  threshold_display,
  threshold_label = 'Threshold',
  subtext,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;
  const maxVal = Math.max(current_value, threshold_value, 1) * 1.25;
  const currentPct = Math.min(100, Math.max(5, (current_value / maxVal) * 100));
  const thresholdPct = Math.min(95, Math.max(5, (threshold_value / maxVal) * 100));

  const spr = spring({
    frame: Math.max(0, frame - (isContinuous ? 0 : 8)),
    fps,
    config: { damping: 14, stiffness: 90, mass: 0.9 },
  });

  const progress = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
  const animatedCurrentPct = currentPct * progress;

  const meetsThreshold = current_value >= threshold_value;
  const statusColor = meetsThreshold ? theme.positive : theme.warning;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header
        headline={headline}
        subheadline={subtext}
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
      />
      <Card
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{ width: isPortrait ? '92%' : '75%', padding: '36px 32px' }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            width: '100%',
            marginBottom: 28,
          }}
        >
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>
              Current Value
            </div>
            <div style={{ fontSize: isPortrait ? 36 : 48, fontWeight: 900, color: statusColor, marginTop: 4 }}>
              {current_display || current_value}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>
              {threshold_label}
            </div>
            <div style={{ fontSize: isPortrait ? 36 : 48, fontWeight: 900, color: theme.text, marginTop: 4 }}>
              {threshold_display || threshold_value}
            </div>
          </div>
        </div>

        <div
          style={{
            position: 'relative',
            width: '100%',
            height: 32,
            backgroundColor: theme.surfaceBorder,
            borderRadius: 16,
            overflow: 'visible',
          }}
        >
          <div
            style={{
              width: `${animatedCurrentPct}%`,
              height: '100%',
              backgroundColor: statusColor,
              borderRadius: 16,
              boxShadow: `0 0 20px ${statusColor}60`,
            }}
          />

          <div
            style={{
              position: 'absolute',
              left: `${thresholdPct}%`,
              top: -10,
              bottom: -10,
              width: 4,
              backgroundColor: theme.text,
              borderRadius: 2,
              boxShadow: '0 0 10px rgba(255,255,255,0.8)',
              zIndex: 2,
            }}
          />
        </div>
      </Card>
    </Layout>
  );
};
