import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { BeforeAfterProps } from '../types';

export const BeforeAfterTemplate: React.FC<BeforeAfterProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  // Header entrance
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

  // Delta resolution spring
  const deltaSpr = spring({
    frame: Math.max(0, frame - Math.round(durationInFrames * 0.65)),
    fps,
    config: { damping: 14, stiffness: 130 },
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
          padding: isPortrait ? '36px 20px' : '44px 64px',
          boxSizing: 'border-box',
          position: 'relative',
        }}
      >
        {/* Header */}
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

        {/* Comparison Split Cards */}
        <div
          style={{
            display: 'flex',
            flexDirection: isPortrait ? 'column' : 'row',
            alignItems: 'center',
            justifyContent: 'center',
            gap: isPortrait ? 20 : 36,
            width: '100%',
            maxWidth: 920,
            position: 'relative',
          }}
        >
          {/* 1. BEFORE CARD */}
          <div
            style={{
              flex: 1,
              width: isPortrait ? '100%' : 'auto',
              maxWidth: isPortrait ? 380 : 'none',
              padding: isPortrait ? '24px 20px' : '36px 32px',
              backgroundColor: theme.surface,
              border: `1.5px solid ${theme.surfaceBorder}`,
              borderRadius: 20,
              boxShadow: '0 8px 32px rgba(0,0,0,0.25)',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              textAlign: 'center',
              opacity: beforeSpr,
              transform: `translateX(${interpolate(beforeSpr, [0, 1], [isPortrait ? 0 : -30, 0])}px)`,
            }}
          >
            <div
              style={{
                fontSize: isPortrait ? 12 : 14,
                fontWeight: 800,
                letterSpacing: '0.15em',
                color: theme.muted,
                textTransform: 'uppercase',
                marginBottom: 10,
              }}
            >
              {props.before_label || 'BEFORE'}
            </div>
            <div
              style={{
                fontSize: isPortrait ? 32 : 46,
                fontWeight: 900,
                color: theme.text,
                letterSpacing: '-0.03em',
              }}
            >
              {props.before_value}
            </div>
          </div>

          {/* Center Transition Icon / Divider */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 44,
              height: 44,
              borderRadius: 22,
              backgroundColor: theme.surface,
              border: `1.5px solid ${theme.surfaceBorder}`,
              color: theme.accent,
              fontSize: 20,
              fontWeight: 900,
              opacity: afterSpr,
              transform: `scale(${interpolate(afterSpr, [0, 1], [0.6, 1])})`,
              boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
              flexShrink: 0,
            }}
          >
            {isPortrait ? '↓' : '→'}
          </div>

          {/* 2. AFTER CARD */}
          <div
            style={{
              flex: 1,
              width: isPortrait ? '100%' : 'auto',
              maxWidth: isPortrait ? 380 : 'none',
              padding: isPortrait ? '24px 20px' : '36px 32px',
              backgroundColor: theme.surface,
              border: `2px solid ${theme.accent}`,
              borderRadius: 20,
              boxShadow: `0 8px 32px ${theme.accent}33`,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              textAlign: 'center',
              opacity: afterSpr,
              transform: `translateX(${interpolate(afterSpr, [0, 1], [isPortrait ? 0 : 30, 0])}px)`,
            }}
          >
            <div
              style={{
                fontSize: isPortrait ? 12 : 14,
                fontWeight: 800,
                letterSpacing: '0.15em',
                color: theme.accent,
                textTransform: 'uppercase',
                marginBottom: 10,
              }}
            >
              {props.after_label || 'AFTER'}
            </div>
            <div
              style={{
                fontSize: isPortrait ? 32 : 46,
                fontWeight: 900,
                color: theme.accent,
                letterSpacing: '-0.03em',
              }}
            >
              {props.after_value}
            </div>
          </div>
        </div>

        {/* Delta Callout Badge */}
        {props.delta_display && (
          <div
            style={{
              marginTop: 28,
              padding: '10px 24px',
              backgroundColor: theme.surface,
              border: `1.5px solid ${theme.positive}`,
              borderRadius: 14,
              color: theme.positive,
              fontSize: isPortrait ? 14 : 16,
              fontWeight: 900,
              opacity: deltaSpr,
              transform: `scale(${interpolate(deltaSpr, [0, 1], [0.85, 1])})`,
              boxShadow: `0 4px 20px ${theme.positive}33`,
            }}
          >
            {props.delta_display}
          </div>
        )}

        {props.subtext && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              color: theme.muted,
              marginTop: 16,
              textAlign: 'center',
            }}
          >
            {props.subtext}
          </div>
        )}
      </div>
    </Layout>
  );
};
