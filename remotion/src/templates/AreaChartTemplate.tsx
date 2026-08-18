import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { AreaChartProps } from '../types';

export const AreaChartTemplate: React.FC<AreaChartProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const rawPoints = props.points || [
    { x_label: '2022', y_value: 100, display_value: '$100' },
    { x_label: '2024', y_value: 150, display_value: '$150' },
    { x_label: '2026', y_value: 220, display_value: '$220' },
  ];

  const yValues = rawPoints.map((p) => Number(p.y_value) || 0);
  const maxY = Math.max(...yValues, 10);
  const minY = Math.min(0, ...yValues);
  const yRange = maxY - minY || 1;

  // Chart dimensions
  const chartW = isPortrait ? width * 0.88 : Math.min(width * 0.75, 840);
  const chartH = isPortrait ? height * 0.42 : height * 0.46;
  const paddingL = 48;
  const paddingR = 32;
  const paddingT = 32;
  const paddingB = 48;

  const innerW = chartW - paddingL - paddingR;
  const innerH = chartH - paddingT - paddingB;

  // Coordinates
  const coords = rawPoints.map((p, idx) => {
    const x = paddingL + (idx / Math.max(1, rawPoints.length - 1)) * innerW;
    const yVal = Number(p.y_value) || 0;
    const y = paddingT + innerH - ((yVal - minY) / yRange) * innerH;
    return { x, y, point: p };
  });

  // SVG Path definitions
  const linePath = coords.reduce((acc, c, idx) => {
    return idx === 0 ? `M ${c.x} ${c.y}` : `${acc} L ${c.x} ${c.y}`;
  }, '');

  const areaPath = coords.length > 0
    ? `${linePath} L ${coords[coords.length - 1].x} ${paddingT + innerH} L ${coords[0].x} ${paddingT + innerH} Z`
    : '';

  // Entrance spring
  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Path drawing spring
  const drawSpr = spring({
    frame: Math.max(0, frame - 8),
    fps,
    config: { damping: 14, stiffness: 75 },
  });

  const approxPathLen = innerW * 1.5;

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
          padding: isPortrait ? '36px 20px' : '44px 56px',
          boxSizing: 'border-box',
          position: 'relative',
        }}
      >
        {/* Header Section */}
        <div
          style={{
            textAlign: 'center',
            marginBottom: isPortrait ? 20 : 28,
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

        {/* SVG Area Chart Container */}
        <div
          style={{
            width: chartW,
            height: chartH,
            backgroundColor: theme.surface,
            border: `1.5px solid ${theme.surfaceBorder}`,
            borderRadius: 20,
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
            position: 'relative',
            overflow: 'hidden',
          }}
        >
          <svg width={chartW} height={chartH} viewBox={`0 0 ${chartW} ${chartH}`}>
            <defs>
              <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={theme.accent} stopOpacity={0.45 * drawSpr} />
                <stop offset="100%" stopColor={theme.accent} stopOpacity={0.0} />
              </linearGradient>
            </defs>

            {/* Gridlines */}
            {[0.25, 0.5, 0.75, 1.0].map((tick, i) => {
              const y = paddingT + innerH * (1 - tick);
              return (
                <line
                  key={i}
                  x1={paddingL}
                  y1={y}
                  x2={paddingL + innerW}
                  y2={y}
                  stroke={theme.surfaceBorder}
                  strokeDasharray="4 4"
                  strokeWidth={1}
                />
              );
            })}

            {/* Area Fill */}
            <path d={areaPath} fill="url(#areaGradient)" />

            {/* Line Stroke */}
            <path
              d={linePath}
              fill="none"
              stroke={theme.accent}
              strokeWidth={4}
              strokeDasharray={`${approxPathLen} ${approxPathLen}`}
              strokeDashoffset={approxPathLen * (1 - drawSpr)}
              strokeLinecap="round"
              style={{
                filter: `drop-shadow(0 0 12px ${theme.accent}88)`,
              }}
            />

            {/* Data Point Dots and Labels */}
            {coords.map((c, idx) => {
              const pointDelay = 12 + idx * Math.max(4, Math.floor((durationInFrames * 0.35) / coords.length));
              const pointSpr = spring({
                frame: Math.max(0, frame - pointDelay),
                fps,
                config: { damping: 14, stiffness: 120 },
              });

              return (
                <g key={idx} opacity={pointSpr} transform={`translate(0, ${interpolate(pointSpr, [0, 1], [10, 0])})`}>
                  {/* Outer circle halo */}
                  <circle
                    cx={c.x}
                    cy={c.y}
                    r={8}
                    fill={theme.background}
                    stroke={theme.accent}
                    strokeWidth={3}
                  />

                  {/* Value badge */}
                  <text
                    x={c.x}
                    y={c.y - 14}
                    textAnchor="middle"
                    fill={theme.text}
                    fontSize={isPortrait ? 12 : 14}
                    fontWeight={900}
                  >
                    {c.point.display_value || c.point.y_value}
                  </text>

                  {/* X Axis Label */}
                  <text
                    x={c.x}
                    y={paddingT + innerH + 24}
                    textAnchor="middle"
                    fill={theme.muted}
                    fontSize={isPortrait ? 11 : 13}
                    fontWeight={800}
                  >
                    {c.point.x_label}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </div>
    </Layout>
  );
};
