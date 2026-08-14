import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { AgeMarkerProps, Theme } from '../types';

export const AgeMarkerTemplate: React.FC<AgeMarkerProps & { theme?: Partial<Theme> }> = ({
  headline,
  markers = [],
  subtext,
  theme: customTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const validMarkers = markers.slice(0, 4);

  return (
    <Layout theme={theme}>
      <Header headline={headline} subheadline={subtext} theme={theme} />
      <div
        style={{
          display: 'flex',
          flexDirection: isPortrait ? 'column' : 'row',
          gap: Math.round(Math.min(width, height) * 0.04),
          width: '92%',
          justifyContent: 'center',
          alignItems: 'center',
        }}
      >
        {validMarkers.map((m, idx) => {
          const spr = spring({
            frame: Math.max(0, frame - (6 + idx * 5)),
            fps,
            config: { damping: 12, stiffness: 90, mass: 0.8 },
          });

          const scale = interpolate(spr, [0, 1], [0.8, 1]);
          const opacity = interpolate(spr, [0, 1], [0, 1]);
          const isHighlighted = !!m.highlight;

          return (
            <div
              key={idx}
              style={{
                opacity,
                transform: `scale(${scale})`,
                display: 'flex',
                flex: isPortrait ? undefined : 1,
                width: isPortrait ? '80%' : undefined,
                justifyContent: 'center',
              }}
            >
              <Card
                theme={theme}
                highlight={isHighlighted}
                style={{
                  width: '100%',
                  padding: `${Math.round(height * 0.035)}px ${Math.round(width * 0.03)}px`,
                  textAlign: 'center',
                }}
              >
                <div
                  style={{
                    fontSize: Math.min(24, Math.max(14, Math.round(width * 0.018))),
                    fontWeight: 700,
                    color: isHighlighted ? theme.accent : theme.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                  }}
                >
                  AGE
                </div>
                <div
                  style={{
                    fontSize: Math.min(100, Math.max(42, Math.round(isPortrait ? width * 0.14 : width * 0.075))),
                    fontWeight: 900,
                    color: isHighlighted ? theme.accent : theme.text,
                    lineHeight: 1.05,
                    margin: '6px 0',
                    textShadow: isHighlighted ? `0 0 24px ${theme.accent}60` : undefined,
                  }}
                >
                  {m.age}
                </div>
                {m.label && (
                  <div
                    style={{
                      fontSize: Math.min(22, Math.max(13, Math.round(width * 0.016))),
                      fontWeight: 600,
                      color: isHighlighted ? theme.text : theme.muted,
                      marginTop: 4,
                    }}
                  >
                    {m.label}
                  </div>
                )}
              </Card>
            </div>
          );
        })}
      </div>
    </Layout>
  );
};
