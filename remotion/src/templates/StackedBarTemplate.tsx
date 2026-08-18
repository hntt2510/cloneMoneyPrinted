import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { StackedBarProps } from '../types';

export const StackedBarTemplate: React.FC<StackedBarProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const total = Number(props.total) || 100;
  const segments = props.segments || [
    { label: 'Part A', value: 60, display_value: '60%', highlight: true },
    { label: 'Part B', value: 40, display_value: '40%', highlight: false },
  ];

  const defaultColors = [
    theme.accent,
    theme.positive,
    '#60A5FA',
    '#F59E0B',
    '#EC4899',
  ];

  // Header entrance
  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Track width
  const trackW = isPortrait ? width * 0.88 : Math.min(width * 0.78, 860);

  // Segment delays
  const segDelayBase = 8;
  const segDelayStep = Math.max(4, Math.floor((durationInFrames * 0.45) / segments.length));

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: isPortrait ? '36px 20px' : '44px 56px',
          boxSizing: 'border-box',
          position: 'relative',
        }}
      >
        {/* Header Section */}
        <div
          style={{
            textAlign: 'center',
            marginBottom: isPortrait ? 24 : 32,
            opacity: headerSpr,
            transform: `translateY(${interpolate(headerSpr, [0, 1], [16, 0])}px)`,
          }}
        >
          {props.eyebrow && (
            <div
              style={{
                fontSize: isPortrait ? 13 : 15,
                fontWeight: 800,
                letterSpacing: '0.15em',
                color: theme.accent,
                textTransform: 'uppercase',
                marginBottom: 6,
              }}
            >
              {props.eyebrow}
            </div>
          )}
          <div
            style={{
              fontSize: isPortrait ? 22 : 32,
              fontWeight: 900,
              color: theme.text,
              letterSpacing: '-0.02em',
              maxWidth: 780,
              lineHeight: 1.25,
            }}
          >
            {props.headline}
          </div>
        </div>

        {/* Total Callout */}
        <div
          style={{
            fontSize: isPortrait ? 36 : 50,
            fontWeight: 900,
            color: theme.text,
            marginBottom: isPortrait ? 20 : 28,
            letterSpacing: '-0.03em',
            opacity: headerSpr,
          }}
        >
          {props.total_display || `$${total.toLocaleString()}`}
        </div>

        {/* Stacked Continuous Horizontal Bar Track */}
        <div
          style={{
            width: trackW,
            height: isPortrait ? 32 : 44,
            backgroundColor: theme.surface,
            border: `1.5px solid ${theme.surfaceBorder}`,
            borderRadius: 14,
            display: 'flex',
            overflow: 'hidden',
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            marginBottom: isPortrait ? 24 : 32,
          }}
        >
          {segments.map((seg, idx) => {
            const segSpr = spring({
              frame: Math.max(0, frame - (segDelayBase + idx * segDelayStep)),
              fps,
              config: { damping: 15, stiffness: 90 },
            });

            const val = Number(seg.value) || 0;
            const pct = total > 0 ? (val / total) * 100 : 50;
            const color = seg.color || defaultColors[idx % defaultColors.length];

            return (
              <div
                key={idx}
                style={{
                  width: `${pct * segSpr}%`,
                  height: '100%',
                  backgroundColor: color,
                  position: 'relative',
                  borderRight: idx < segments.length - 1 ? `2px solid ${theme.background}` : 'none',
                  boxShadow: seg.highlight ? `0 0 16px ${color}88` : 'none',
                }}
              />
            );
          })}
        </div>

        {/* Segment Labels / Badges */}
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            justifyContent: 'center',
            gap: isPortrait ? 12 : 24,
            maxWidth: trackW,
          }}
        >
          {segments.map((seg, idx) => {
            const segSpr = spring({
              frame: Math.max(0, frame - (segDelayBase + idx * segDelayStep + 4)),
              fps,
              config: { damping: 16, stiffness: 110 },
            });

            const color = seg.color || defaultColors[idx % defaultColors.length];
            const val = Number(seg.value) || 0;
            const pct = total > 0 ? Math.round((val / total) * 100) : 0;

            return (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  padding: '8px 16px',
                  backgroundColor: theme.surface,
                  border: `1px solid ${seg.highlight ? color : theme.surfaceBorder}`,
                  borderRadius: 12,
                  opacity: segSpr,
                  transform: `scale(${interpolate(segSpr, [0, 1], [0.85, 1])})`,
                }}
              >
                <div
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                    backgroundColor: color,
                  }}
                />
                <div style={{ fontSize: isPortrait ? 12 : 14, fontWeight: 800, color: theme.text }}>
                  {seg.label}
                </div>
                <div style={{ fontSize: isPortrait ? 12 : 14, fontWeight: 900, color: color }}>
                  {seg.display_value || `${pct}%`}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Layout>
  );
};
