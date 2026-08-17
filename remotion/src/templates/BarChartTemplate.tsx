import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { BarChartProps, Theme } from '../types';

export const BarChartTemplate: React.FC<BarChartProps> = ({
  headline,
  items = [],
  unit,
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
  const validItems = items.slice(0, 6);
  const maxVal = Math.max(...validItems.map((it) => Math.abs(it.value)), 1);

  const chartHeight = Math.round(height * (isPortrait ? 0.45 : 0.42));

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header headline={headline} theme={theme} isGrouped={isGrouped} isFirstInGroup={isFirstInGroup} />
      <Card
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{
          width: '92%',
          height: chartHeight,
          padding: `${Math.round(height * 0.03)}px ${Math.round(width * 0.04)}px`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-around',
            width: '100%',
            height: '100%',
            gap: Math.round(width * 0.02),
            borderBottom: `2px solid ${theme.border}`,
            paddingBottom: 8,
            boxSizing: 'border-box',
          }}
        >
          {validItems.map((item, idx) => {
            let delay = isContinuous ? 0 : 8 + idx * 4;
            if (animation_plan?.beats) {
              const cBeats = animation_plan.beats.filter(b => b.kind === 'chart_item');
              if (cBeats[idx]) {
                delay = cBeats[idx].start_frame;
              }
            }
            
            const spr = spring({
              frame: Math.max(0, frame - delay),
              fps,
              config: { damping: 14, stiffness: 90, mass: 0.9 },
            });
            const progress = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
            const targetRatio = Math.max(0.05, Math.abs(item.value) / maxVal);
            const currentHeightPct = targetRatio * progress * 80;

            const barColor = item.color || (idx === validItems.length - 1 ? theme.accent : theme.primary);
            const displayVal = item.display_value || `${item.value}${unit ? ` ${unit}` : ''}`;

            const labelSize = isPortrait ? width * 0.035 : width * 0.018;
            const valSize = isPortrait ? width * 0.04 : width * 0.022;

            return (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  height: '100%',
                  flex: 1,
                  maxWidth: isPortrait ? 90 : 120,
                }}
              >
                <div
                  style={{
                    opacity: progress,
                    fontSize: Math.min(28, Math.max(14, Math.round(valSize))),
                    fontWeight: 800,
                    color: theme.text,
                    marginBottom: 8,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {displayVal}
                </div>

                <div
                  style={{
                    width: '100%',
                    height: `${currentHeightPct}%`,
                    backgroundColor: barColor,
                    borderRadius: '8px 8px 0 0',
                    boxShadow: `0 4px 16px ${barColor}40`,
                    minHeight: 6,
                  }}
                />

                <div
                  style={{
                    marginTop: 12,
                    fontSize: Math.min(24, Math.max(12, Math.round(labelSize))),
                    fontWeight: 600,
                    color: theme.muted,
                    textAlign: 'center',
                    wordBreak: 'break-word',
                  }}
                >
                  {item.label}
                </div>
              </div>
            );
          })}
        </div>
      </Card>
    </Layout>
  );
};
