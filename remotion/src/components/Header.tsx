import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { resolveTheme } from '../theme/theme';
import { Theme } from '../types';

interface HeaderProps {
  headline: string;
  subheadline?: string | null;
  theme?: Partial<Theme>;
  delayFrames?: number;
}

export const Header: React.FC<HeaderProps> = ({
  headline,
  subheadline,
  theme: customTheme,
  delayFrames = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const spr = spring({
    frame: Math.max(0, frame - delayFrames),
    fps,
    config: { damping: 15, stiffness: 100, mass: 0.8 },
  });

  const opacity = interpolate(spr, [0, 1], [0, 1]);
  const translateY = interpolate(spr, [0, 1], [24, 0]);

  // Responsive font sizes
  const baseFontSize = isPortrait ? width * 0.065 : width * 0.038;
  const subFontSize = baseFontSize * 0.52;

  return (
    <div
      style={{
        opacity,
        transform: `translateY(${translateY}px)`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        textAlign: 'center',
        marginBottom: Math.round(height * 0.04),
        maxWidth: '92%',
      }}
    >
      <h1
        style={{
          margin: 0,
          fontSize: Math.min(64, Math.max(28, Math.round(baseFontSize))),
          fontWeight: 800,
          color: theme.text,
          letterSpacing: '-0.02em',
          lineHeight: 1.18,
          textTransform: 'uppercase',
          wordBreak: 'break-word',
        }}
      >
        {headline}
      </h1>
      {subheadline && (
        <p
          style={{
            margin: `${Math.round(height * 0.015)}px 0 0 0`,
            fontSize: Math.min(32, Math.max(16, Math.round(subFontSize))),
            fontWeight: 500,
            color: theme.muted,
            lineHeight: 1.4,
            maxWidth: '85%',
          }}
        >
          {subheadline}
        </p>
      )}
    </div>
  );
};
