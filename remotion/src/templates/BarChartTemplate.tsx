import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { createBandScale, createLinearScale } from '../components/D3Geometry';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, resolveCategoryColor, getItemFocusState } from '../layout';
import { resolveTheme } from '../theme/theme';
import { BarChartProps } from '../types';

export const BarChartTemplate: React.FC<BarChartProps> = ({
  headline,
  items = [],
  theme: customTheme,
  isGrouped = false,
  animation_plan,
  eyebrow,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);
  const barItems = items.length > 0 ? items : [
    { label: 'Plan A', value: 120, display_value: '$120' },
    { label: 'Plan B', value: 180, display_value: '$180' },
    { label: 'Plan C', value: 230, display_value: '$230' },
  ];

  // 1. Title Zone
  const titleFit = fitText({
    text: headline,
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

  // 2. Chart Dimensions
  const chartW = isPortrait ? safe.chartZone.width * 0.92 : Math.min(safe.chartZone.width * 0.85, 960);
  const chartH = isPortrait ? safe.chartZone.height * 0.65 : safe.chartZone.height * 0.68;
  const chartLeft = safe.chartZone.x + (safe.chartZone.width - chartW) / 2;
  const chartTop = safe.chartZone.y + Math.round(safe.chartZone.height * 0.06);

  const maxVal = Math.max(...barItems.map((i) => Number(i.value) || 0), 10);
  const numBars = barItems.length;

  const xScale = createBandScale(
    barItems.map((_, i) => String(i)),
    [20, chartW - 20],
    0.32
  );
  const yScale = createLinearScale([0, maxVal], [chartH - 40, 40]);
  const gridLines = yScale.ticks(3);

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
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
        {eyebrow && (
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
            {eyebrow}
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

      {/* ZONE 2: BAR CHART SVG */}
      <div
        style={{
          position: 'absolute',
          left: chartLeft,
          top: chartTop,
          width: chartW,
          height: chartH,
          zIndex: 5,
        }}
      >
        <svg width={chartW} height={chartH} style={{ overflow: 'visible' }}>
          {/* Horizontal Grid lines */}
          {gridLines.map((gl, i) => {
            const y = yScale(gl);
            return (
              <line
                key={`grid-${i}`}
                x1={0}
                y1={y}
                x2={chartW}
                y2={y}
                stroke={theme.surfaceBorder}
                strokeWidth={1.5}
                strokeDasharray="4 4"
              />
            );
          })}

          {/* Baseline */}
          <line
            x1={0}
            y1={chartH - 40}
            x2={chartW}
            y2={chartH - 40}
            stroke={theme.surfaceBorder}
            strokeWidth={2}
          />

          {/* Bars */}
          {barItems.map((item, idx) => {
            const focus = getItemFocusState(idx, frame, durationInFrames, animation_plan, numBars);

            const delay = 10 + idx * Math.max(8, Math.floor((durationInFrames * 0.45) / numBars));
            const barSpr = spring({
              frame: Math.max(0, frame - delay),
              fps,
              config: { damping: 14, stiffness: 100 },
            });

            const barColor = item.color || resolveCategoryColor({
              label: item.label,
              index: idx,
              totalCategories: numBars,
            });

            const fullBarH = (chartH - 40) - yScale(Number(item.value) || 0);
            const x = xScale(String(idx));
            const barWidth = xScale.bandwidth;
            const currH = barSpr * fullBarH;
            const y = (chartH - 40) - currH;

            const lblFit = fitText({
              text: item.label,
              maxWidth: barWidth * 1.3,
              preferredFontSize: isPortrait ? 11 : 14,
              fontWeight: 800,
              role: 'chart_label',
            });

            return (
              <g
                key={`bar-${idx}`}
                style={{
                  opacity: barSpr * focus.opacity,
                  transition: 'opacity 0.2s ease',
                }}
              >
                {/* Bar Rectangle */}
                <rect
                  x={x}
                  y={y}
                  width={barWidth}
                  height={Math.max(4, currH)}
                  fill={barColor}
                  rx={6}
                  ry={6}
                  style={{
                    filter: focus.isActive ? `drop-shadow(0 0 16px ${barColor}99)` : 'none',
                  }}
                />

                {/* Value Text Above Bar */}
                {barSpr > 0.4 && (
                  <text
                    x={x + barWidth / 2}
                    y={y - 10}
                    fill={focus.isActive ? '#ffffff' : theme.text}
                    fontSize={isPortrait ? 13 : 16}
                    fontWeight={900}
                    textAnchor="middle"
                  >
                    {item.display_value || item.value}
                  </text>
                )}

                {/* Category Label Below Baseline */}
                {barSpr > 0.2 && (
                  <text
                    x={x + barWidth / 2}
                    y={chartH - 18}
                    fill={focus.isActive ? theme.text : theme.muted}
                    fontSize={lblFit.fontSize}
                    fontWeight={focus.isActive ? 900 : 700}
                    textAnchor="middle"
                  >
                    {lblFit.lines[0]}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </Layout>
  );
};
