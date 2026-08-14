import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { TextProps, Theme } from '../types';

export const TextTemplate: React.FC<TextProps & { theme?: Partial<Theme> }> = ({
  headline,
  subheadline,
  style_variant = 'bold',
  theme: customTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const spr = spring({
    frame,
    fps,
    config: { damping: 13, stiffness: 95, mass: 0.8 },
  });

  const titleOpacity = interpolate(spr, [0, 1], [0, 1]);
  const titleScale = interpolate(spr, [0, 1], [0.9, 1]);
  const titleTranslateY = interpolate(spr, [0, 1], [24, 0]);

  const lineSpr = spring({
    frame: Math.max(0, frame - 6),
    fps,
    config: { damping: 14, stiffness: 90, mass: 0.9 },
  });
  const lineWidthPct = interpolate(lineSpr, [0, 1], [0, 100]);

  const fontSize = isPortrait ? width * 0.095 : width * 0.058;
  const subFontSize = fontSize * 0.45;

  return (
    <Layout theme={theme}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          maxWidth: '90%',
          opacity: titleOpacity,
          transform: `scale(${titleScale}) translateY(${titleTranslateY}px)`,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: Math.min(96, Math.max(36, Math.round(fontSize))),
            fontWeight: 900,
            color: theme.text,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
            textTransform: 'uppercase',
            wordBreak: 'break-word',
          }}
        >
          {headline}
        </h1>

        {/* Accent Underline */}
        <div
          style={{
            width: `${lineWidthPct * 0.4}%`,
            height: 6,
            backgroundColor: theme.accent,
            borderRadius: 3,
            marginTop: 20,
            marginBottom: subheadline ? 20 : 0,
            boxShadow: `0 0 16px ${theme.accent}80`,
          }}
        />

        {subheadline && (
          <p
            style={{
              margin: 0,
              fontSize: Math.min(42, Math.max(20, Math.round(subFontSize))),
              fontWeight: 600,
              color: theme.muted,
              lineHeight: 1.35,
              maxWidth: '85%',
            }}
          >
            {subheadline}
          </p>
        )}
      </div>
    </Layout>
  );
};
