import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { ComparisonProps, Theme } from '../types';

export const ComparisonTemplate: React.FC<ComparisonProps> = ({
  headline,
  items = [],
  subtext,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;
  const validItems = items.slice(0, 4);

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header
        headline={headline}
        subheadline={subtext}
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
      />
      <div
        style={{
          display: 'flex',
          flexDirection: isPortrait ? 'column' : 'row',
          gap: Math.round(Math.min(width, height) * 0.035),
          width: '95%',
          justifyContent: 'center',
          alignItems: 'stretch',
        }}
      >
        {validItems.map((item, idx) => {
          const delay = isContinuous ? 0 : 6 + idx * 5;
          const spr = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 14, stiffness: 90, mass: 0.9 },
          });
          const itemOpacity = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
          const itemTranslateY = isContinuous ? 0 : interpolate(spr, [0, 1], [20, 0]);

          const isHighlighted = !!item.highlight;
          const valFontSize = isPortrait ? width * 0.09 : width * 0.052;
          const labelFontSize = isPortrait ? width * 0.042 : width * 0.022;

          return (
            <div
              key={idx}
              style={{
                flex: 1,
                opacity: itemOpacity,
                transform: `translateY(${itemTranslateY}px)`,
                display: 'flex',
              }}
            >
              <Card
                theme={theme}
                highlight={isHighlighted}
                isGrouped={isGrouped}
                isFirstInGroup={isFirstInGroup}
                style={{ width: '100%', padding: `${Math.round(height * 0.03)}px ${Math.round(width * 0.03)}px` }}
              >
                <div
                  style={{
                    fontSize: Math.min(32, Math.max(16, Math.round(labelFontSize))),
                    fontWeight: 600,
                    color: isHighlighted ? theme.accent : theme.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                    marginBottom: Math.round(height * 0.015),
                    textAlign: 'center',
                  }}
                >
                  {item.label}
                </div>
                <div
                  style={{
                    fontSize: Math.min(84, Math.max(28, Math.round(valFontSize))),
                    fontWeight: 900,
                    color: isHighlighted ? theme.positive : theme.text,
                    letterSpacing: '-0.02em',
                    lineHeight: 1.1,
                    textAlign: 'center',
                  }}
                >
                  {item.value}
                </div>
              </Card>
            </div>
          );
        })}
      </div>
    </Layout>
  );
};
