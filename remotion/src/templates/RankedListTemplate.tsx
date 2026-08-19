import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, resolveCategoryColor, getItemFocusState } from '../layout';
import { resolveTheme } from '../theme/theme';
import { RankedListProps } from '../types';

export const RankedListTemplate: React.FC<RankedListProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);
  const items = (props.items && props.items.length > 0) ? props.items : [
    { rank: 1, label: 'Rear-End Collisions', value: 38, display_value: '38%', highlight: true },
    { rank: 2, label: 'Intersection T-Bones', value: 27, display_value: '27%', highlight: false },
    { rank: 3, label: 'Single-Vehicle Runoff', value: 21, display_value: '21%', highlight: false },
    { rank: 4, label: 'Parking Lot Scrapes', value: 14, display_value: '14%', highlight: false },
  ];

  const maxVal = Math.max(...items.map((it) => Number(it.value) || 1), 1);
  const numItems = items.length;

  // 1. Title Zone Layout
  const titleFit = fitText({
    text: props.headline,
    maxWidth: safe.titleZone.width * 0.9,
    maxHeight: safe.titleZone.height - 16,
    preferredFontSize: isPortrait ? 24 : 36,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />

      {/* ZONE 1: TITLE ZONE */}
      <div
        style={{
          position: 'absolute',
          left: safe.titleZone.x,
          top: safe.titleZone.y,
          width: safe.titleZone.width,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          opacity: headerSpr,
          transform: `translateY(${interpolate(headerSpr, [0, 1], [16, 0])}px)`,
          zIndex: 10,
        }}
      >
        {props.eyebrow && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              letterSpacing: '0.14em',
              color: theme.accent,
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            {props.eyebrow}
          </div>
        )}
        <h1
          style={{
            margin: 0,
            fontSize: titleFit.fontSize,
            lineHeight: `${titleFit.lineHeight}px`,
            fontWeight: 800,
            color: theme.text,
            letterSpacing: '-0.02em',
            maxWidth: safe.titleZone.width * 0.9,
            wordBreak: 'break-word',
          }}
        >
          {titleFit.lines.map((ln, i) => (
            <div key={i}>{ln}</div>
          ))}
        </h1>
      </div>

      {/* ZONE 2: RANKED LIST CONTAINER */}
      <div
        style={{
          position: 'absolute',
          left: safe.chartZone.x,
          top: safe.chartZone.y,
          width: safe.chartZone.width,
          height: safe.chartZone.height,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: isPortrait ? 10 : 14,
          zIndex: 5,
        }}
      >
        <div
          style={{
            width: '100%',
            maxWidth: isPortrait ? safe.chartZone.width * 0.94 : Math.min(safe.chartZone.width * 0.78, 800),
            display: 'flex',
            flexDirection: 'column',
            gap: isPortrait ? 10 : 14,
          }}
        >
          {items.map((item, idx) => {
            const focus = getItemFocusState(idx, frame, durationInFrames, props.animation_plan, numItems);

            const delay = 8 + idx * Math.max(6, Math.floor((durationInFrames * 0.45) / numItems));
            const itemSpr = spring({
              frame: Math.max(0, frame - delay),
              fps,
              config: { damping: 15, stiffness: 100 },
            });

            const val = Number(item.value) || 0;
            const pct = maxVal > 0 ? (val / maxVal) * 100 : 50;

            const categoryColor = resolveCategoryColor({
              label: item.label,
              index: idx,
              totalCategories: numItems,
            });

            const lblFit = fitText({
              text: item.label,
              maxWidth: isPortrait ? 220 : 360,
              preferredFontSize: isPortrait ? 13 : 16,
              fontWeight: 800,
              role: 'chart_label',
            });

            return (
              <div
                key={idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: isPortrait ? 12 : 18,
                  padding: isPortrait ? '10px 14px' : '12px 20px',
                  backgroundColor: focus.isActive ? theme.surface : 'rgba(21, 29, 46, 0.5)',
                  border: `1.5px solid ${focus.isActive ? categoryColor : theme.surfaceBorder}`,
                  borderRadius: 14,
                  opacity: itemSpr * focus.opacity,
                  transform: `scale(${focus.scale})`,
                  boxShadow: focus.isActive ? `0 4px 20px ${categoryColor}40` : '0 4px 12px rgba(0,0,0,0.2)',
                  transition: 'all 0.2s ease',
                }}
              >
                {/* Rank Badge */}
                <div
                  style={{
                    width: isPortrait ? 28 : 34,
                    height: isPortrait ? 28 : 34,
                    borderRadius: 8,
                    backgroundColor: categoryColor,
                    color: '#ffffff',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: isPortrait ? 13 : 16,
                    fontWeight: 900,
                    boxShadow: `0 0 10px ${categoryColor}66`,
                    flexShrink: 0,
                  }}
                >
                  #{item.rank || idx + 1}
                </div>

                {/* Label and Visual Fill Bar */}
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}
                  >
                    <span
                      style={{
                        fontSize: lblFit.fontSize,
                        fontWeight: focus.isActive ? 900 : 700,
                        color: focus.isActive ? '#ffffff' : theme.text,
                        letterSpacing: '-0.01em',
                      }}
                    >
                      {lblFit.lines[0]}
                    </span>
                    <span
                      style={{
                        fontSize: isPortrait ? 13 : 16,
                        fontWeight: 900,
                        color: categoryColor,
                      }}
                    >
                      {item.display_value || `${val}`}
                    </span>
                  </div>

                  {/* Horizontal mini-bar */}
                  <div
                    style={{
                      width: '100%',
                      height: 6,
                      backgroundColor: theme.surfaceBorder,
                      borderRadius: 3,
                      overflow: 'hidden',
                    }}
                  >
                    <div
                      style={{
                        width: `${pct * itemSpr}%`,
                        height: '100%',
                        backgroundColor: categoryColor,
                        borderRadius: 3,
                        boxShadow: `0 0 8px ${categoryColor}80`,
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Layout>
  );
};
