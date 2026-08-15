import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { resolveTheme } from '../theme/theme';
import { Theme } from '../types';

interface CardProps {
  children: React.ReactNode;
  theme?: Partial<Theme>;
  delayFrames?: number;
  highlight?: boolean;
  style?: React.CSSProperties;
  isGrouped?: boolean;
  isFirstInGroup?: boolean;
}

export const Card: React.FC<CardProps> = ({
  children,
  theme: customTheme,
  delayFrames = 0,
  highlight = false,
  style = {},
  isGrouped = false,
  isFirstInGroup = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);

  const isContinuous = isGrouped && !isFirstInGroup;

  const spr = spring({
    frame: Math.max(0, frame - delayFrames),
    fps,
    config: { damping: 14, stiffness: 90, mass: 0.9 },
  });

  const opacity = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
  const scale = isContinuous ? 1 : interpolate(spr, [0, 1], [0.92, 1]);

  return (
    <div
      style={{
        opacity,
        transform: `scale(${scale})`,
        backgroundColor: highlight ? `${theme.primary}18` : theme.surface,
        border: `1.5px solid ${highlight ? theme.accent : theme.surfaceBorder}`,
        borderRadius: Math.round(Math.min(width, height) * 0.025),
        boxShadow: highlight
          ? `0 12px 36px ${theme.primary}30`
          : '0 8px 32px rgba(0, 0, 0, 0.35)',
        padding: `${Math.round(height * 0.035)}px ${Math.round(width * 0.04)}px`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        boxSizing: 'border-box',
        ...style,
      }}
    >
      {children}
    </div>
  );
};
