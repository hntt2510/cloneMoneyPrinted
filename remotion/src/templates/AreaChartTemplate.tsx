import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText } from '../layout';
import { resolveTheme } from '../theme/theme';
import { AreaChartProps } from '../types';

export const AreaChartTemplate: React.FC<AreaChartProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const rawPoints = props.points || [
    { x_label: '2022', y_value: 100, display_value: '$100' },
    { x_label: '2024', y_value: 150, display_value: '$150' },
    { x_label: '2026', y_value: 220, display_value: '$220' },
  ];

  const yValues = rawPoints.map((p) => Number(p.y_value) || 0);
  const maxY = Math.max(...yValues, 10);
  const minY = Math.min(0, ...yValues);
  const yRange = maxY - minY || 1;

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

  // 2. Geometry
  const chartW = isPortrait ? safe.chartZone.width * 0.92 : Math.min(safe.chartZone.width * 0.85, 960);
  const chartH = isPortrait ? safe.chartZone.height * 0.65 : safe.chartZone.height * 0.68;
  const chartLeft = safe.chartZone.x + (safe.chartZone.width - chartW) / 2;
  const chartTop = safe.chartZone.y + Math.round(safe.chartZone.height * 0.06);

  const paddingL = 40;
  const paddingR = 40;
  const paddingT = 30;
  const paddingB = 40;
  const innerW = chartW - paddingL - paddingR;
  const innerH = chartH - paddingT - paddingB;

  const coords = rawPoints.map((p, idx) => {
    const x = paddingL + (idx / Math.max(1, rawPoints.length - 1)) * innerW;
    const yVal = Number(p.y_value) || 0;
    const y = paddingT + innerH - ((yVal - minY) / yRange) * innerH;
    return { x, y, point: p };
  });

  const linePath = coords.reduce((acc, c, idx) => {
    return idx === 0 ? `M ${c.x} ${c.y}` : `${acc} L ${c.x} ${c.y}`;
  }, '');

  const areaPath = coords.length > 0
    ? `${linePath} L ${coords[coords.length - 1].x} ${paddingT + innerH} L ${coords[0].x} ${paddingT + innerH} Z`
    : '';

  const drawSpr = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: { damping: 14, stiffness: 75 },
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

      {/* ZONE 2: AREA CHART SVG */}
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
          <defs>
            <linearGradient id="areaGlow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={theme.accent} stopOpacity="0.35" />
              <stop offset="100%" stopColor={theme.accent} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {/* Baseline */}
          <line
            x1={paddingL - 10}
            y1={paddingT + innerH}
            x2={chartW - paddingR + 10}
            y2={paddingT + innerH}
            stroke={theme.surfaceBorder}
            strokeWidth={1.5}
          />

          {/* Semi-transparent Area Gradient Fill */}
          <path
            d={areaPath}
            fill="url(#areaGlow)"
            opacity={drawSpr}
          />

          {/* Area Top Line */}
          <path
            d={linePath}
            fill="none"
            stroke={theme.accent}
            strokeWidth={4}
            style={{
              filter: `drop-shadow(0 0 12px ${theme.accent}80)`,
              opacity: drawSpr,
            }}
          />

          {/* Points and Values */}
          {coords.map((c, i) => {
            const delay = 10 + i * Math.max(8, Math.floor((durationInFrames * 0.4) / coords.length));
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
                  {c.point.display_value || c.point.y_value}
                </text>
                <text
                  x={c.x}
                  y={paddingT + innerH + 22}
                  fill={theme.muted}
                  fontSize={isPortrait ? 11 : 13}
                  fontWeight={800}
                  textAnchor="middle"
                >
                  {c.point.x_label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </Layout>
  );
};
