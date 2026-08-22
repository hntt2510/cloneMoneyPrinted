import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { createLinearScale, generateSmoothPath } from '../components/D3Geometry';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText } from '../layout';
import { resolveTheme } from '../theme/theme';
import { LineChartProps } from '../types';

export const LineChartTemplate: React.FC<LineChartProps> = ({
  headline,
  points = [],
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
  const pts = points.length > 0 ? points : [
    { x_label: '2022', y_value: 120, display_value: '$120' },
    { x_label: '2024', y_value: 150, display_value: '$150' },
    { x_label: '2026', y_value: 180, display_value: '$180' },
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

  // 2. Geometry
  const chartW = isPortrait ? safe.chartZone.width * 0.92 : Math.min(safe.chartZone.width * 0.85, 960);
  const chartH = isPortrait ? safe.chartZone.height * 0.65 : safe.chartZone.height * 0.68;
  const chartLeft = safe.chartZone.x + (safe.chartZone.width - chartW) / 2;
  const chartTop = safe.chartZone.y + Math.round(safe.chartZone.height * 0.06);

  const maxVal = Math.max(...pts.map((p) => Number(p.y_value) || 0), 10);
  const minVal = Math.min(...pts.map((p) => Number(p.y_value) || 0), 0);
  const range = maxVal - minVal || 1;

  const paddingX = 40;
  const paddingBottom = 40;
  const paddingTop = 30;
  const plotW = chartW - paddingX * 2;
  const plotH = chartH - paddingBottom - paddingTop;

  const xScale = createLinearScale([0, Math.max(1, pts.length - 1)], [paddingX, paddingX + plotW]);
  const yScale = createLinearScale([minVal, maxVal], [paddingTop + plotH, paddingTop]);

  const coords = pts.map((p, i) => {
    const x = xScale(i);
    const y = yScale(Number(p.y_value) || 0);
    return { x, y, p };
  });

  const pathD = generateSmoothPath(coords);

  const totalLength = chartW * 2;
  const drawPct = interpolate(frame, [8, Math.round(durationInFrames * 0.55)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const strokeDashoffset = totalLength * (1 - drawPct);

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

      {/* ZONE 2: LINE CHART SVG */}
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
          {/* Baseline */}
          <line
            x1={paddingX - 10}
            y1={chartH - paddingBottom}
            x2={chartW - paddingX + 10}
            y2={chartH - paddingBottom}
            stroke={theme.surfaceBorder}
            strokeWidth={1.5}
          />

          {/* Line Path */}
          <path
            d={pathD}
            fill="none"
            stroke={theme.accent}
            strokeWidth={4}
            strokeDasharray={totalLength}
            strokeDashoffset={strokeDashoffset}
            style={{ filter: `drop-shadow(0 0 12px ${theme.accent}80)` }}
          />

          {/* Points and Values */}
          {coords.map((c, i) => {
            const delay = 10 + i * Math.max(8, Math.floor((durationInFrames * 0.4) / pts.length));
            const ptSpr = spring({
              frame: Math.max(0, frame - delay),
              fps,
              config: { damping: 14, stiffness: 120 },
            });

            return (
              <g key={`pt-${i}`} style={{ opacity: ptSpr }}>
                <circle
                  cx={c.x}
                  cy={c.y}
                  r={7}
                  fill={theme.accent}
                  stroke="#ffffff"
                  strokeWidth={3}
                  style={{ filter: `drop-shadow(0 0 8px ${theme.accent})` }}
                />
                <text
                  x={c.x}
                  y={c.y - 14}
                  fill="#ffffff"
                  fontSize={isPortrait ? 13 : 16}
                  fontWeight={900}
                  textAnchor="middle"
                >
                  {c.p.display_value || c.p.y_value}
                </text>
                <text
                  x={c.x}
                  y={chartH - paddingBottom + 20}
                  fill={theme.muted}
                  fontSize={isPortrait ? 11 : 13}
                  fontWeight={800}
                  textAnchor="middle"
                >
                  {c.p.x_label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </Layout>
  );
};
