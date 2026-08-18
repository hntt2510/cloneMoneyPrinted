import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { RankedListProps } from '../types';

export const RankedListTemplate: React.FC<RankedListProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const items = props.items || [
    { rank: 1, label: 'Item 1', value: 100, display_value: '100', highlight: true },
    { rank: 2, label: 'Item 2', value: 80, display_value: '80', highlight: false },
  ];

  const maxVal = Math.max(...items.map((it) => Number(it.value) || 1), 1);

  // Header entrance
  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Stagger delays
  const rowDelayBase = 6;
  const rowDelayStep = Math.max(4, Math.floor((durationInFrames * 0.45) / items.length));

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
        {/* Header Section */}
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

        {/* Ranked Rows List */}
        <div
          style={{
            width: '100%',
            maxWidth: isPortrait ? 420 : 760,
            display: 'flex',
            flexDirection: 'column',
            gap: isPortrait ? 12 : 16,
          }}
        >
          {items.map((item, idx) => {
            const itemDelay = rowDelayBase + idx * rowDelayStep;
            const itemSpr = spring({
              frame: Math.max(0, frame - itemDelay),
              fps,
              config: { damping: 15, stiffness: 100 },
            });

            const val = Number(item.value) || 0;
            const pct = maxVal > 0 ? (val / maxVal) * 100 : 50;
            const isTop = item.rank === 1 || item.highlight;
            const rankBg = isTop ? theme.accent : theme.surfaceBorder;

            return (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: isPortrait ? 12 : 18,
                  padding: isPortrait ? '10px 14px' : '14px 20px',
                  backgroundColor: theme.surface,
                  border: `1.5px solid ${isTop ? theme.accent : theme.surfaceBorder}`,
                  borderRadius: 16,
                  opacity: itemSpr,
                  transform: `translateX(${interpolate(itemSpr, [0, 1], [-24, 0])}px)`,
                  boxShadow: isTop ? `0 4px 20px ${theme.accent}33` : '0 4px 16px rgba(0,0,0,0.2)',
                }}
              >
                {/* Rank Badge */}
                <div
                  style={{
                    width: isPortrait ? 32 : 38,
                    height: isPortrait ? 32 : 38,
                    borderRadius: 10,
                    backgroundColor: rankBg,
                    color: isTop ? '#0B0F19' : theme.text,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: isPortrait ? 14 : 16,
                    fontWeight: 900,
                    flexShrink: 0,
                  }}
                >
                  #{item.rank || idx + 1}
                </div>

                {/* Label and Bar */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'baseline',
                    }}
                  >
                    <span
                      style={{
                        fontSize: isPortrait ? 14 : 16,
                        fontWeight: 800,
                        color: theme.text,
                      }}
                    >
                      {item.label}
                    </span>

                    {item.display_value && (
                      <span
                        style={{
                          fontSize: isPortrait ? 14 : 16,
                          fontWeight: 900,
                          color: isTop ? theme.accent : theme.muted,
                        }}
                      >
                        {item.display_value}
                      </span>
                    )}
                  </div>

                  {/* Horizontal Bar */}
                  <div
                    style={{
                      width: '100%',
                      height: 8,
                      backgroundColor: theme.background,
                      borderRadius: 4,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${pct * itemSpr}%`,
                        height: '100%',
                        backgroundColor: isTop ? theme.accent : theme.positive,
                        borderRadius: 4,
                        boxShadow: isTop ? `0 0 10px ${theme.accent}88` : 'none',
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {props.subtext && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              color: theme.muted,
              marginTop: 20,
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
