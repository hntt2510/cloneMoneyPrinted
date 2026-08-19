import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { GaugeProps } from '../types';

export const GaugeTemplate: React.FC<GaugeProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const currentVal = Number(props.current_value) || 0;
  const maxVal = Number(props.max_value) || 100;
  const minVal = Number(props.min_value) || 0;
  const pct = Math.min(100, Math.max(0, ((currentVal - minVal) / (maxVal - minVal)) * 100));
  const variant = props.variant || props.layout_archetype || 'radial_gauge';

  // 1. Title Zone
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

  // Gauge fill spring
  const fillSpr = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: { damping: 14, stiffness: 85 },
  });

  const animatedVal = Math.round(interpolate(fillSpr, [0, 1], [0, currentVal]));

  // Geometry for radial gauge (240 degree arc)
  const size = isPortrait ? Math.min(safe.chartZone.width * 0.76, 380) : Math.min(safe.chartZone.height * 0.68, 420);
  const strokeWidth = size * 0.09;
  const radius = size * 0.38;
  const arcLength = Math.PI * radius * (240 / 180);

  // Semantic color selection
  const gaugeColor = SEMANTIC_COLORS.gauge.progress;

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

      {/* ZONE 2: GAUGE SVG CONTAINER */}
      <div
        style={{
          position: 'absolute',
          left: safe.chartZone.x,
          top: safe.chartZone.y,
          width: safe.chartZone.width,
          height: safe.chartZone.height,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 5,
        }}
      >
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
            style={{ overflow: 'visible' }}
          >
            {/* Background 240deg Track */}
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={theme.surfaceBorder}
              strokeWidth={strokeWidth}
              strokeDasharray={`${arcLength} ${2 * Math.PI * radius}`}
              strokeDashoffset={0}
              strokeLinecap="round"
              style={{
                transform: 'rotate(150deg)',
                transformOrigin: '50% 50%',
              }}
            />

            {/* Filled Progress Arc */}
            <circle
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={gaugeColor}
              strokeWidth={strokeWidth}
              strokeDasharray={`${arcLength * (pct / 100) * fillSpr} ${2 * Math.PI * radius}`}
              strokeDashoffset={0}
              strokeLinecap="round"
              style={{
                transform: 'rotate(150deg)',
                transformOrigin: '50% 50%',
                filter: `drop-shadow(0 0 16px ${gaugeColor}99)`,
              }}
            />
          </svg>

          {/* Center Value and Label */}
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
                fontSize: isPortrait ? 38 : 52,
                fontWeight: 900,
                color: '#ffffff',
                lineHeight: 1,
                letterSpacing: '-0.03em',
                textShadow: `0 0 16px ${gaugeColor}80`,
              }}
            >
              {props.display_value || `${animatedVal}${props.unit || '%'}`}
            </div>
            <div
              style={{
                fontSize: isPortrait ? 12 : 14,
                fontWeight: 800,
                color: theme.muted,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                marginTop: 6,
                maxWidth: size * 0.5,
              }}
            >
              {props.label || 'Complete'}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
};
