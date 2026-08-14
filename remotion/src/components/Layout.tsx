import React from 'react';
import { AbsoluteFill, useVideoConfig } from 'remotion';
import { defaultFontFamily, resolveTheme } from '../theme/theme';
import { Theme } from '../types';

interface LayoutProps {
  children: React.ReactNode;
  theme?: Partial<Theme>;
}

export const Layout: React.FC<LayoutProps> = ({ children, theme: customTheme }) => {
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const paddingX = Math.round(width * 0.08);
  const paddingY = Math.round(height * 0.08);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: theme.background,
        color: theme.text,
        fontFamily: defaultFontFamily,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        padding: `${paddingY}px ${paddingX}px`,
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}
    >
      {/* Background subtle ambient radial glow */}
      <div
        style={{
          position: 'absolute',
          top: '20%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: Math.min(width, height) * 0.9,
          height: Math.min(width, height) * 0.9,
          borderRadius: '50%',
          background: `radial-gradient(circle, ${theme.primary}15 0%, rgba(0,0,0,0) 70%)`,
          pointerEvents: 'none',
        }}
      />
      <div
        style={{
          position: 'relative',
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          zIndex: 1,
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};
