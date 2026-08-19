import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { ThresholdProps } from '../types';

export const ThresholdTemplate: React.FC<ThresholdProps> = ({
  headline,
  current_value,
  current_display,
  threshold_value,
  threshold_display,
  threshold_label = 'Limit',
  theme: customTheme,
  isGrouped = false,
  animation_plan,
  eyebrow,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const curVal = Number(current_value) || 0;
  const thresVal = Number(threshold_value) || 0;
  const maxVal = Math.max(curVal, thresVal, 10) * 1.22;
  const currentPct = Math.min(95, Math.max(5, (curVal / maxVal) * 100));
  const thresholdPct = Math.min(90, Math.max(10, (thresVal / maxVal) * 100));

  const hasOverflow = curVal > thresVal;
  const statusColor = hasOverflow
    ? SEMANTIC_COLORS.threshold.danger
    : SEMANTIC_COLORS.threshold.safe;

  // 1. Title Zone
  const titleFit = fitText({
    text: headline,
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

  // 2. 4-Phase Choreography Springs
  // Phase 1: Limit Marker (frames 0 - 20)
  const limitSpr = spring({
    frame: Math.max(0, frame - 6),
    fps,
    config: { damping: 14, stiffness: 100 },
  });

  // Phase 2: Bar Growth (frames 15 - 55)
  const growSpr = spring({
    frame: Math.max(0, frame - 16),
    fps,
    config: { damping: 16, stiffness: 70 },
  });

  const animatedCurrentPct = growSpr * currentPct;
  const baseFillPct = Math.min(animatedCurrentPct, thresholdPct);
  const overflowFillPct = Math.max(0, animatedCurrentPct - thresholdPct);

  // Phase 3: Crossing & Warning Pulse (around frame 45+)
  const crossSpr = spring({
    frame: Math.max(0, frame - 40),
    fps,
    config: { damping: 10, stiffness: 140 },
  });

  // Phase 4: Final Status Badge (frames 60+)
  const resolveSpr = spring({
    frame: Math.max(0, frame - Math.round(durationInFrames * 0.65)),
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  const trackWidth = isPortrait ? safe.chartZone.width * 0.92 : Math.min(safe.chartZone.width * 0.85, 960);
  const trackHeight = isPortrait ? 28 : 34;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="radial_light" theme={theme} subtle_motion />

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
        {eyebrow && (
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
            {eyebrow}
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

      {/* ZONE 2: THRESHOLD TRACK CONTAINER */}
      <div
        style={{
          position: 'absolute',
          left: safe.chartZone.x + (safe.chartZone.width - trackWidth) / 2,
          top: safe.chartZone.y + Math.round(safe.chartZone.height * 0.35),
          width: trackWidth,
          zIndex: 5,
        }}
      >
        {/* Track Bar */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: trackHeight,
            backgroundColor: theme.surfaceBorder,
            borderRadius: trackHeight / 2,
            overflow: 'visible',
          }}
        >
          {/* Base Safe Fill (up to limit) */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              height: '100%',
              width: `${baseFillPct}%`,
              backgroundColor: theme.primary,
              borderRadius: `${trackHeight / 2}px 0 0 ${trackHeight / 2}px`,
              boxShadow: `0 0 14px ${theme.primary}66`,
            }}
          />

          {/* Overflow Fill (past limit) */}
          {hasOverflow && overflowFillPct > 0 && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: `${thresholdPct}%`,
                height: '100%',
                width: `${overflowFillPct}%`,
                backgroundColor: statusColor,
                borderRadius: '0 8px 8px 0',
                boxShadow: `0 0 18px ${statusColor}99`,
              }}
            />
          )}

          {/* Limit Vertical Line Marker */}
          <div
            style={{
              position: 'absolute',
              top: -18,
              bottom: -18,
              left: `${thresholdPct}%`,
              width: 4,
              backgroundColor: '#ffffff',
              transform: 'translateX(-50%)',
              opacity: limitSpr,
              boxShadow: '0 0 12px rgba(255,255,255,0.8)',
              zIndex: 3,
            }}
          >
            {/* Limit Label Above */}
            <div
              style={{
                position: 'absolute',
                bottom: '100%',
                left: '50%',
                transform: 'translateX(-50%)',
                marginBottom: 10,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                whiteSpace: 'nowrap',
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 800, color: theme.muted, textTransform: 'uppercase' }}>
                {threshold_label}
              </span>
              <span style={{ fontSize: isPortrait ? 18 : 24, fontWeight: 900, color: theme.text }}>
                {threshold_display || `$${thresVal.toLocaleString()}`}
              </span>
            </div>
          </div>

          {/* Current Value Indicator Label (Follows Growth) */}
          {animatedCurrentPct > 5 && (
            <div
              style={{
                position: 'absolute',
                top: '100%',
                left: `${animatedCurrentPct}%`,
                transform: 'translateX(-50%)',
                marginTop: 14,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                whiteSpace: 'nowrap',
                zIndex: 4,
              }}
            >
              <span style={{ fontSize: isPortrait ? 20 : 28, fontWeight: 900, color: hasOverflow ? statusColor : theme.positive }}>
                {current_display || `$${curVal.toLocaleString()}`}
              </span>
              <span style={{ fontSize: 13, fontWeight: 800, color: hasOverflow ? statusColor : theme.muted, textTransform: 'uppercase' }}>
                ACTUAL
              </span>
            </div>
          )}
        </div>

        {/* Phase 4 Status Pill Badge */}
        {hasOverflow && (
          <div
            style={{
              display: 'flex',
              justifyContent: 'center',
              marginTop: 80,
              opacity: resolveSpr,
              transform: `scale(${interpolate(resolveSpr, [0, 1], [0.85, 1])})`,
            }}
          >
            <div
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 24px',
                borderRadius: 24,
                backgroundColor: `${statusColor}22`,
                border: `1.5px solid ${statusColor}`,
                color: statusColor,
                fontSize: isPortrait ? 14 : 17,
                fontWeight: 900,
                letterSpacing: '0.06em',
                textTransform: 'uppercase',
                boxShadow: `0 0 20px ${statusColor}44`,
              }}
            >
              ⚠️ EXCEEDS POLICY LIMIT BY ${(curVal - thresVal).toLocaleString()}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};
