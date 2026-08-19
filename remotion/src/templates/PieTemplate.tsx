import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, resolveCategoryColor, getItemFocusState } from '../layout';
import { resolveTheme } from '../theme/theme';
import { PieProps } from '../types';

export const PieTemplate: React.FC<PieProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const items = (props.items && props.items.length >= 2) ? props.items : [
    { label: 'Premium', value: 40, percentage: 40, display_value: '40%' },
    { label: 'Standard', value: 35, percentage: 35, display_value: '35%' },
    { label: 'Basic', value: 25, percentage: 25, display_value: '25%' },
  ];

  const totalValue = props.total || items.reduce((acc, it) => acc + (Number(it.value) || 0), 0) || 100;
  const variant = props.variant || props.layout_archetype || 'donut_center_stat';

  // 1. Title Zone Layout
  const titleFit = fitText({
    text: props.headline,
    maxWidth: safe.titleZone.width * 0.9,
    maxHeight: safe.titleZone.height - 16,
    preferredFontSize: isPortrait ? 24 : 36,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // 2. Geometry Dimensions
  const size = isPortrait ? Math.min(safe.chartZone.width * 0.72, 380) : Math.min(safe.chartZone.height * 0.68, 440);
  const radius = size * 0.38;
  const strokeWidth = variant === 'pie_focus' ? radius : (size * 0.12);
  const normalizedRadius = variant === 'pie_focus' ? radius / 2 : radius - strokeWidth / 2;
  const circumference = 2 * Math.PI * normalizedRadius;

  // Base ring entrance
  const baseSpr = spring({
    frame: Math.max(0, frame - 4),
    fps,
    config: { damping: 18, stiffness: 100 },
  });

  // Slice calculation with distinct categorical color resolution
  let accumulatedAngle = 0;
  const sliceData = items.map((item, idx) => {
    const rawVal = Number(item.value) || 0;
    const pct = item.percentage !== undefined && item.percentage !== null
      ? item.percentage
      : (totalValue > 0 ? (rawVal / totalValue) * 100 : 100 / items.length);
    const sliceAngle = (pct / 100) * 360;
    const sliceCircumference = (pct / 100) * circumference;

    const sliceSpr = spring({
      frame: Math.max(0, frame - (8 + idx * 6)),
      fps,
      config: { damping: 15, stiffness: 90 },
    });

    const currentOffset = (accumulatedAngle / 360) * circumference;
    accumulatedAngle += sliceAngle;

    // Distinct categorical color resolution
    const color = item.color || resolveCategoryColor({
      label: item.label,
      index: idx,
      totalCategories: items.length,
    });

    const focus = getItemFocusState(idx, frame, durationInFrames, props.animation_plan, items.length);

    return {
      item,
      pct,
      color,
      sliceCircumference,
      currentOffset,
      sliceSpr,
      focus,
    };
  });

  // Determine currently active item for center stat
  const activeSlice = sliceData.find((s) => s.focus.isActive) || sliceData[0];
  const centerDisplay = activeSlice.item.display_value || `${Math.round(activeSlice.pct)}%`;
  const centerLabel = activeSlice.item.label;

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />

      {/* ZONE 1: TITLE ZONE */}
      <div
        style={{
          position: 'absolute',
          left: safe.titleZone.x,
          top: safe.titleZone.y,
          width: safe.titleZone.width,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          opacity: headerSpr,
          transform: `translateY(${interpolate(headerSpr, [0, 1], [16, 0])}px)`,
          zIndex: 10,
        }}
      >
        {props.eyebrow && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              letterSpacing: '0.14em',
              color: theme.accent,
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            {props.eyebrow}
          </div>
        )}
        <h1
          style={{
            margin: 0,
            fontSize: titleFit.fontSize,
            lineHeight: `${titleFit.lineHeight}px`,
            fontWeight: 800,
            color: theme.text,
            letterSpacing: '-0.02em',
            maxWidth: safe.titleZone.width * 0.9,
            wordBreak: 'break-word',
          }}
        >
          {titleFit.lines.map((ln, i) => (
            <div key={i}>{ln}</div>
          ))}
        </h1>
      </div>

      {/* ZONE 2 & 3: CHART & LEGEND */}
      <div
        style={{
          position: 'absolute',
          left: safe.chartZone.x,
          top: safe.chartZone.y,
          width: safe.chartZone.width,
          height: safe.chartZone.height,
          display: 'flex',
          flexDirection: isPortrait ? 'column' : 'row',
          alignItems: 'center',
          justifyContent: 'center',
          gap: isPortrait ? 24 : 56,
          zIndex: 5,
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

            {/* Colored Slices */}
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
                  strokeWidth={s.focus.isActive ? strokeWidth * 1.12 : strokeWidth}
                  strokeDasharray={strokeDash}
                  strokeDashoffset={strokeOffset}
                  strokeLinecap={variant === 'segmented_ring' ? 'round' : 'butt'}
                  style={{
                    transition: 'all 0.2s ease',
                    opacity: s.focus.opacity,
                    filter: s.focus.isActive
                      ? `drop-shadow(0 0 16px ${s.color})`
                      : 'none',
                  }}
                />
              );
            })}
          </svg>

          {/* Center Stat Display */}
          {variant !== 'pie_focus' && (
            <div
              style={{
                position: 'absolute',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                textAlign: 'center',
                pointerEvents: 'none',
              }}
            >
              <div
                style={{
                  fontSize: isPortrait ? 30 : 42,
                  fontWeight: 900,
                  color: activeSlice.color,
                  lineHeight: 1,
                  letterSpacing: '-0.03em',
                  textShadow: activeSlice.focus.isActive ? `0 0 12px ${activeSlice.color}80` : 'none',
                  transition: 'color 0.2s ease',
                }}
              >
                {centerDisplay}
              </div>
              <div
                style={{
                  fontSize: isPortrait ? 11 : 13,
                  fontWeight: 800,
                  color: theme.muted,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  marginTop: 4,
                  maxWidth: size * 0.52,
                }}
              >
                {centerLabel}
              </div>
            </div>
          )}
        </div>

        {/* Legend Cards */}
        <div
          style={{
            display: 'flex',
            flexDirection: isPortrait ? 'row' : 'column',
            flexWrap: isPortrait ? 'wrap' : 'nowrap',
            justifyContent: isPortrait ? 'center' : 'flex-start',
            gap: isPortrait ? 12 : 16,
            minWidth: isPortrait ? 'auto' : 260,
          }}
        >
          {sliceData.map((s, idx) => {
            const itemSpr = spring({
              frame: Math.max(0, frame - (10 + idx * 5)),
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
                  backgroundColor: s.focus.isActive ? theme.surface : 'rgba(21, 29, 46, 0.4)',
                  border: `1.5px solid ${s.focus.isActive ? s.color : theme.surfaceBorder}`,
                  opacity: itemSpr * s.focus.opacity,
                  transform: `scale(${s.focus.scale})`,
                  boxShadow: s.focus.isActive ? `0 4px 20px ${s.color}33` : 'none',
                  transition: 'all 0.2s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {/* Category Color Marker */}
                  <div
                    style={{
                      width: 14,
                      height: 14,
                      borderRadius: 4,
                      backgroundColor: s.color,
                      boxShadow: `0 0 8px ${s.color}80`,
                    }}
                  />
                  <div
                    style={{
                      fontSize: isPortrait ? 12 : 14,
                      fontWeight: s.focus.isActive ? 900 : 700,
                      color: s.focus.isActive ? '#ffffff' : theme.text,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {s.item.label}
                  </div>
                </div>

                <div
                  style={{
                    fontSize: isPortrait ? 13 : 15,
                    fontWeight: 900,
                    color: s.color,
                  }}
                >
                  {s.item.display_value || `${Math.round(s.pct)}%`}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Layout>
  );
};
