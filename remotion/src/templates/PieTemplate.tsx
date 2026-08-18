import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { PieProps } from '../types';

export const PieTemplate: React.FC<PieProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const items = (props.items && props.items.length >= 2) ? props.items : [
    { label: 'Option A', value: 50, percentage: 50, display_value: '50%' },
    { label: 'Option B', value: 50, percentage: 50, display_value: '50%' },
  ];

  const totalValue = props.total || items.reduce((acc, it) => acc + (Number(it.value) || 0), 0) || 100;
  const variant = props.variant || props.layout_archetype || 'donut_center_stat';

  // Determine focus item
  const focusItem = items.find((it) => it.highlight) || items[0];
  const focusPct = focusItem.percentage || Math.round(((focusItem.value || 0) / totalValue) * 100);

  // Colors for slices
  const defaultColors = [
    theme.accent,
    theme.positive,
    '#60A5FA',
    '#F59E0B',
    '#EC4899',
    '#8B5CF6',
  ];

  // SVG Geometry
  const size = isPortrait ? Math.min(width * 0.72, 420) : Math.min(height * 0.58, 440);
  const radius = size * 0.38;
  const strokeWidth = variant === 'pie_focus' ? radius : (size * 0.12);
  const normalizedRadius = variant === 'pie_focus' ? radius / 2 : radius - strokeWidth / 2;
  const circumference = 2 * Math.PI * normalizedRadius;

  // Header entrance spring
  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Base ring entrance
  const baseSpr = spring({
    frame: Math.max(0, frame - 4),
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  // Slice animation springs
  const sliceDelayBase = 8;
  const sliceDelayStep = Math.max(4, Math.floor((durationInFrames * 0.45) / items.length));

  // Compute slice angles and offsets
  let accumulatedAngle = 0;
  const sliceData = items.map((item, idx) => {
    const rawVal = Number(item.value) || 0;
    const pct = item.percentage !== undefined && item.percentage !== null
      ? item.percentage
      : (totalValue > 0 ? (rawVal / totalValue) * 100 : 100 / items.length);
    const sliceAngle = (pct / 100) * 360;
    const sliceCircumference = (pct / 100) * circumference;

    const startDelay = sliceDelayBase + idx * sliceDelayStep;
    const sliceSpr = spring({
      frame: Math.max(0, frame - startDelay),
      fps,
      config: { damping: 15, stiffness: 90 },
    });

    const currentOffset = (accumulatedAngle / 360) * circumference;
    accumulatedAngle += sliceAngle;

    const isFocused = item.highlight || item.label === focusItem.label;
    const color = item.color || defaultColors[idx % defaultColors.length];

    return {
      item,
      pct,
      color,
      isFocused,
      sliceCircumference,
      currentOffset,
      sliceSpr,
    };
  });

  // Focus resolution spring
  const focusSpr = spring({
    frame: Math.max(0, frame - Math.round(durationInFrames * 0.65)),
    fps,
    config: { damping: 14, stiffness: 140 },
  });

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
          padding: isPortrait ? '40px 24px' : '48px 64px',
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

        {/* Content Container (Donut Chart + Legend) */}
        <div
          style={{
            display: 'flex',
            flexDirection: isPortrait ? 'column' : 'row',
            alignItems: 'center',
            justifyContent: 'center',
            gap: isPortrait ? 28 : 64,
            width: '100%',
            maxWidth: 1080,
          }}
        >
          {/* SVG Donut / Pie */}
          <div
            style={{
              position: 'relative',
              width: size,
              height: size,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <svg
              width={size}
              height={size}
              viewBox={`0 0 ${size} ${size}`}
              style={{
                transform: 'rotate(-90deg)',
                overflow: 'visible',
              }}
            >
              {/* Background Track Ring */}
              <circle
                cx={size / 2}
                cy={size / 2}
                r={normalizedRadius}
                fill="none"
                stroke={theme.surfaceBorder}
                strokeWidth={strokeWidth}
                opacity={baseSpr * 0.6}
              />

              {/* Slices */}
              {sliceData.map((s, idx) => {
                const strokeDash = `${s.sliceCircumference * s.sliceSpr} ${circumference}`;
                const strokeOffset = -s.currentOffset;

                return (
                  <circle
                    key={idx}
                    cx={size / 2}
                    cy={size / 2}
                    r={normalizedRadius}
                    fill="none"
                    stroke={s.color}
                    strokeWidth={s.isFocused ? strokeWidth * 1.08 : strokeWidth}
                    strokeDasharray={strokeDash}
                    strokeDashoffset={strokeOffset}
                    strokeLinecap={variant === 'segmented_ring' ? 'round' : 'butt'}
                    style={{
                      transition: 'stroke-width 0.2s ease',
                      filter: (s.isFocused && frame >= durationInFrames * 0.65)
                        ? `drop-shadow(0 0 16px ${s.color}66)`
                        : 'none',
                    }}
                  />
                );
              })}
            </svg>

            {/* Center Stat / Cutout content */}
            {variant !== 'pie_focus' && (
              <div
                style={{
                  position: 'absolute',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  textAlign: 'center',
                  opacity: interpolate(focusSpr, [0, 0.4, 1], [0.3, 0.7, 1]),
                  transform: `scale(${interpolate(focusSpr, [0, 1], [0.9, 1])})`,
                  pointerEvents: 'none',
                }}
              >
                <div
                  style={{
                    fontSize: isPortrait ? 32 : 44,
                    fontWeight: 900,
                    color: focusItem.highlight ? theme.accent : theme.text,
                    lineHeight: 1,
                    letterSpacing: '-0.03em',
                  }}
                >
                  {focusItem.display_value || `${Math.round(focusPct)}%`}
                </div>
                <div
                  style={{
                    fontSize: isPortrait ? 12 : 14,
                    fontWeight: 800,
                    color: theme.muted,
                    letterSpacing: '0.1em',
                    textTransform: 'uppercase',
                    marginTop: 4,
                    maxWidth: size * 0.5,
                  }}
                >
                  {props.focus_label || focusItem.label}
                </div>
              </div>
            )}
          </div>

          {/* Legend Items */}
          <div
            style={{
              display: 'flex',
              flexDirection: isPortrait ? 'row' : 'column',
              flexWrap: isPortrait ? 'wrap' : 'nowrap',
              justifyContent: isPortrait ? 'center' : 'flex-start',
              gap: isPortrait ? 14 : 18,
              minWidth: isPortrait ? 'auto' : 280,
            }}
          >
            {sliceData.map((s, idx) => {
              const itemSpr = spring({
                frame: Math.max(0, frame - (sliceDelayBase + idx * sliceDelayStep + 4)),
                fps,
                config: { damping: 16, stiffness: 120 },
              });

              return (
                <div
                  key={idx}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 16,
                    padding: '10px 18px',
                    borderRadius: 12,
                    backgroundColor: s.isFocused ? theme.surface : 'transparent',
                    border: `1px solid ${s.isFocused ? theme.surfaceBorder : 'transparent'}`,
                    opacity: itemSpr,
                    transform: `translateX(${interpolate(itemSpr, [0, 1], [isPortrait ? 0 : 20, 0])}px)`,
                    boxShadow: s.isFocused ? '0 4px 16px rgba(0,0,0,0.25)' : 'none',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div
                      style={{
                        width: 12,
                        height: 12,
                        borderRadius: 3,
                        backgroundColor: s.color,
                        boxShadow: `0 0 8px ${s.color}88`,
                      }}
                    />
                    <div
                      style={{
                        fontSize: isPortrait ? 13 : 15,
                        fontWeight: 800,
                        color: s.isFocused ? theme.text : theme.muted,
                        letterSpacing: '0.02em',
                      }}
                    >
                      {s.item.label}
                    </div>
                  </div>

                  <div
                    style={{
                      fontSize: isPortrait ? 14 : 16,
                      fontWeight: 900,
                      color: s.isFocused ? theme.accent : theme.text,
                    }}
                  >
                    {s.item.display_value || `${Math.round(s.pct)}%`}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {props.subtext && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              color: theme.muted,
              marginTop: 20,
              textAlign: 'center',
              opacity: focusSpr,
            }}
          >
            {props.subtext}
          </div>
        )}
      </div>
    </Layout>
  );
};
