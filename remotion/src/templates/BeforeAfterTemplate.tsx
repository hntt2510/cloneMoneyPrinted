import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { BeforeAfterProps } from '../types';

export const BeforeAfterTemplate: React.FC<BeforeAfterProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

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

  // "Before" card entrance
  const beforeSpr = spring({
    frame: Math.max(0, frame - 6),
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  // "After" card entrance
  const afterSpr = spring({
    frame: Math.max(0, frame - Math.round(durationInFrames * 0.35)),
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  const cardW = isPortrait ? safe.chartZone.width * 0.88 : Math.min(safe.chartZone.width * 0.42, 440);

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

      {/* ZONE 2: BEFORE / AFTER SPLIT CARDS */}
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
          gap: isPortrait ? 20 : 36,
          zIndex: 5,
        }}
      >
        {/* BEFORE CARD */}
        <div
          style={{
            width: cardW,
            padding: '24px 32px',
            backgroundColor: 'rgba(21, 29, 46, 0.6)',
            border: `1.5px solid ${theme.surfaceBorder}`,
            borderRadius: 20,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
            opacity: beforeSpr,
            transform: `scale(${interpolate(beforeSpr, [0, 1], [0.9, 1])})`,
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
          }}
        >
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              color: SEMANTIC_COLORS.beforeAfter.before,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              marginBottom: 8,
            }}
          >
            {props.before_label || 'BEFORE'}
          </div>
          <div
            style={{
              fontSize: isPortrait ? 36 : 52,
              fontWeight: 900,
              color: '#ffffff',
              letterSpacing: '-0.02em',
            }}
          >
            {props.before_value}
          </div>
        </div>

        {/* ARROW / CONNECTOR */}
        <div
          style={{
            fontSize: 28,
            color: theme.muted,
            opacity: afterSpr,
            transform: isPortrait ? 'rotate(90deg)' : 'none',
          }}
        >
          ➔
        </div>

        {/* AFTER CARD */}
        <div
          style={{
            width: cardW,
            padding: '24px 32px',
            backgroundColor: theme.surface,
            border: `1.5px solid ${theme.accent}`,
            borderRadius: 20,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
            opacity: afterSpr,
            transform: `scale(${interpolate(afterSpr, [0, 1], [0.9, 1])})`,
            boxShadow: `0 8px 32px ${theme.accent}33`,
          }}
        >
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              color: SEMANTIC_COLORS.beforeAfter.after,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              marginBottom: 8,
            }}
          >
            {props.after_label || 'AFTER'}
          </div>
          <div
            style={{
              fontSize: isPortrait ? 36 : 52,
              fontWeight: 900,
              color: SEMANTIC_COLORS.beforeAfter.after,
              letterSpacing: '-0.02em',
              textShadow: `0 0 16px ${theme.accent}80`,
            }}
          >
            {props.after_value}
          </div>
        </div>
      </div>
    </Layout>
  );
};
