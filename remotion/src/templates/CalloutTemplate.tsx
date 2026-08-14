import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { CalloutProps, Theme } from '../types';

export const CalloutTemplate: React.FC<CalloutProps & { theme?: Partial<Theme> }> = ({
  headline,
  emphasis,
  subtext,
  theme: customTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const spr = spring({
    frame: Math.max(0, frame - 5),
    fps,
    config: { damping: 13, stiffness: 90, mass: 0.85 },
  });

  const scale = interpolate(spr, [0, 1], [0.9, 1]);
  const opacity = interpolate(spr, [0, 1], [0, 1]);

  return (
    <Layout theme={theme}>
      <Header headline={headline} theme={theme} />
      <Card
        theme={theme}
        style={{
          width: isPortrait ? '92%' : '75%',
          padding: `${Math.round(height * 0.04)}px ${Math.round(width * 0.04)}px`,
        }}
      >
        <div
          style={{
            opacity,
            transform: `scale(${scale})`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
          }}
        >
          {emphasis && (
            <div
              style={{
                backgroundColor: `${theme.primary}20`,
                border: `2px solid ${theme.accent}`,
                borderRadius: 16,
                padding: '18px 36px',
                fontSize: Math.min(56, Math.max(24, Math.round(isPortrait ? width * 0.075 : width * 0.042))),
                fontWeight: 900,
                color: theme.accent,
                letterSpacing: '-0.02em',
                lineHeight: 1.2,
                boxShadow: `0 8px 32px ${theme.primary}25`,
                wordBreak: 'break-word',
              }}
            >
              {emphasis}
            </div>
          )}
          {subtext && (
            <div
              style={{
                marginTop: emphasis ? 20 : 0,
                fontSize: Math.min(32, Math.max(16, Math.round(isPortrait ? width * 0.045 : width * 0.024))),
                fontWeight: 500,
                color: theme.muted,
                lineHeight: 1.4,
                maxWidth: '90%',
              }}
            >
              {subtext}
            </div>
          )}
        </div>
      </Card>
    </Layout>
  );
};
