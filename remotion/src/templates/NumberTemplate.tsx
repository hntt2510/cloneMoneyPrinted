import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { NumberProps, Theme } from '../types';

export const NumberTemplate: React.FC<NumberProps & { theme?: Partial<Theme> }> = ({
  headline,
  value,
  prefix,
  suffix,
  label,
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
    config: { damping: 12, stiffness: 90, mass: 0.8 },
  });

  const numberScale = interpolate(spr, [0, 1], [0.85, 1]);
  const numberOpacity = interpolate(spr, [0, 1], [0, 1]);

  const valueFontSize = isPortrait ? width * 0.16 : width * 0.085;
  const labelFontSize = isPortrait ? width * 0.045 : width * 0.024;

  const displayString = `${prefix || ''}${value}${suffix || ''}`;

  return (
    <Layout theme={theme}>
      <Header headline={headline} theme={theme} />
      <Card theme={theme} delayFrames={4} style={{ width: isPortrait ? '90%' : '65%' }}>
        <div
          style={{
            opacity: numberOpacity,
            transform: `scale(${numberScale})`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            style={{
              fontSize: Math.min(140, Math.max(48, Math.round(valueFontSize))),
              fontWeight: 900,
              color: theme.accent,
              letterSpacing: '-0.03em',
              lineHeight: 1.05,
              textShadow: `0 8px 32px ${theme.primary}40`,
            }}
          >
            {displayString}
          </div>
          {label && (
            <div
              style={{
                marginTop: Math.round(height * 0.015),
                fontSize: Math.min(36, Math.max(18, Math.round(labelFontSize))),
                fontWeight: 600,
                color: theme.text,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {label}
            </div>
          )}
          {subtext && (
            <div
              style={{
                marginTop: Math.round(height * 0.01),
                fontSize: Math.min(24, Math.max(14, Math.round(labelFontSize * 0.8))),
                fontWeight: 400,
                color: theme.muted,
                textAlign: 'center',
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
