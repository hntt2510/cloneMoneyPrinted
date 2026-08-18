import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { GaugeProps } from '../types';

export const GaugeTemplate: React.FC<GaugeProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const currentVal = Number(props.current_value) || 0;
  const maxVal = Number(props.max_value) || 100;
  const minVal = Number(props.min_value) || 0;
  const pct = Math.min(100, Math.max(0, ((currentVal - minVal) / (maxVal - minVal)) * 100));
  const variant = props.variant || props.layout_archetype || 'radial_gauge';

  // Entrance spring
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

  // Counter interpolated value
  const animatedVal = Math.round(interpolate(fillSpr, [0, 1], [0, currentVal]));

  // Geometry for radial gauge (240 degree arc)
  const size = isPortrait ? Math.min(width * 0.76, 420) : Math.min(height * 0.58, 440);
  const strokeWidth = size * 0.09;
  const radius = size * 0.38;
  const arcLength = Math.PI * radius * (240 / 180);

  // Geometry for progress ring (360 degrees)
  const ringCircumference = 2 * Math.PI * radius;

  // Resolve badge spring
  const resolveSpr = spring({
    frame: Math.max(0, frame - Math.round(durationInFrames * 0.65)),
    fps,
    config: { damping: 15, stiffness: 130 },
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
            marginBottom: isPortrait ? 20 : 28,
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

        {/* Gauge Body */}
        {variant === 'linear_meter' ? (
          /* Linear Meter Variant */
          <div
            style={{
              width: '100%',
              maxWidth: isPortrait ? 380 : 640,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 20,
              padding: '24px 32px',
              backgroundColor: theme.surface,
              border: `1.5px solid ${theme.surfaceBorder}`,
              borderRadius: 20,
              boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            }}
          >
            <div
              style={{
                width: '100%',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
              }}
            >
              <span style={{ fontSize: isPortrait ? 14 : 16, fontWeight: 800, color: theme.muted }}>
                {props.label || 'Progress'}
              </span>
              <span style={{ fontSize: isPortrait ? 28 : 38, fontWeight: 900, color: theme.accent }}>
                {props.display_value || `${animatedVal}${props.unit || '%'}`}
              </span>
            </div>

            {/* Track & Bar */}
            <div
              style={{
                width: '100%',
                height: isPortrait ? 16 : 22,
                backgroundColor: theme.background,
                borderRadius: 12,
                overflow: 'hidden',
                position: 'relative',
                border: `1px solid ${theme.surfaceBorder}`,
              }}
            >
              <div
                style={{
                  width: `${pct * fillSpr}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${theme.accent}, ${theme.positive})`,
                  borderRadius: 12,
                  boxShadow: `0 0 16px ${theme.accent}88`,
                }}
              />
            </div>

            <div
              style={{
                width: '100%',
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 12,
                fontWeight: 700,
                color: theme.muted,
              }}
            >
              <span>{minVal}{props.unit || '%'}</span>
              <span>{maxVal}{props.unit || '%'}</span>
            </div>
          </div>
        ) : (
          /* Radial Gauge & Progress Ring Variants */
          <div
            style={{
              position: 'relative',
              width: size,
              height: variant === 'radial_gauge' ? size * 0.78 : size,
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
                overflow: 'visible',
                transform: variant === 'radial_gauge' ? 'rotate(150deg)' : 'rotate(-90deg)',
              }}
            >
              {/* Background Track Arc */}
              <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={theme.surfaceBorder}
                strokeWidth={strokeWidth}
                strokeDasharray={variant === 'radial_gauge' ? `${arcLength} ${2 * Math.PI * radius}` : `${ringCircumference} ${ringCircumference}`}
                strokeLinecap="round"
                opacity={0.6}
              />

              {/* Progress Fill Arc */}
              <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={pct > 90 ? theme.positive : theme.accent}
                strokeWidth={strokeWidth * 1.05}
                strokeDasharray={
                  variant === 'radial_gauge'
                    ? `${arcLength * (pct / 100) * fillSpr} ${2 * Math.PI * radius}`
                    : `${ringCircumference * (pct / 100) * fillSpr} ${ringCircumference}`
                }
                strokeLinecap="round"
                style={{
                  filter: `drop-shadow(0 0 16px ${pct > 90 ? theme.positive : theme.accent}88)`,
                }}
              />
            </svg>

            {/* Center Gauge Value & Label */}
            <div
              style={{
                position: 'absolute',
                top: variant === 'radial_gauge' ? '32%' : 'auto',
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
                  fontSize: isPortrait ? 40 : 54,
                  fontWeight: 900,
                  color: theme.text,
                  lineHeight: 1,
                  letterSpacing: '-0.03em',
                }}
              >
                {props.display_value || `${animatedVal}${props.unit || '%'}`}
              </div>

              <div
                style={{
                  fontSize: isPortrait ? 13 : 15,
                  fontWeight: 800,
                  color: theme.muted,
                  letterSpacing: '0.1em',
                  textTransform: 'uppercase',
                  marginTop: 6,
                }}
              >
                {props.label || 'Completed'}
              </div>

              {variant === 'radial_gauge' && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    marginTop: 12,
                    fontSize: 12,
                    fontWeight: 700,
                    color: theme.muted,
                  }}
                >
                  <span>{minVal}{props.unit || '%'}</span>
                  <span>/</span>
                  <span>{maxVal}{props.unit || '%'}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Subtext / Key Resolve */}
        {props.subtext && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              color: theme.muted,
              marginTop: 20,
              textAlign: 'center',
              opacity: resolveSpr,
            }}
          >
            {props.subtext}
          </div>
        )}
      </div>
    </Layout>
  );
};
