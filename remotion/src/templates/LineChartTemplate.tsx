import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { LineChartProps, Theme } from '../types';

export const LineChartTemplate: React.FC<LineChartProps & { theme?: Partial<Theme> }> = ({
  headline,
  points = [],
  unit,
  show_area = true,
  theme: customTheme,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const validPoints = points.slice(0, 8);
  const count = validPoints.length;

  const minY = Math.min(...validPoints.map((p) => p.y_value), 0);
  const maxY = Math.max(...validPoints.map((p) => p.y_value), 1);
  const yRange = Math.max(maxY - minY, 1);

  const svgWidth = isPortrait ? width * 0.78 : width * 0.7;
  const svgHeight = height * (isPortrait ? 0.38 : 0.35);

  const paddingLeft = 40;
  const paddingRight = 40;
  const paddingTop = 40;
  const paddingBottom = 40;

  const innerW = svgWidth - paddingLeft - paddingRight;
  const innerH = svgHeight - paddingTop - paddingBottom;

  const coords = validPoints.map((p, idx) => {
    const x = paddingLeft + (idx / Math.max(1, count - 1)) * innerW;
    const yRatio = (p.y_value - minY) / yRange;
    const y = paddingTop + (1 - yRatio) * innerH;
    return { x, y, point: p };
  });

  const pathD = coords.reduce((acc, curr, idx) => {
    return idx === 0 ? `M ${curr.x} ${curr.y}` : `${acc} L ${curr.x} ${curr.y}`;
  }, '');

  const areaD = coords.length > 0
    ? `${pathD} L ${coords[coords.length - 1].x} ${svgHeight - paddingBottom} L ${coords[0].x} ${svgHeight - paddingBottom} Z`
    : '';

  const lineProgress = interpolate(frame, [8, Math.round(durationInFrames * 0.65)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <Layout theme={theme}>
      <Header headline={headline} theme={theme} />
      <Card theme={theme} style={{ width: '92%', padding: 24 }}>
        <svg width={svgWidth} height={svgHeight} style={{ overflow: 'visible' }}>
          <defs>
            <linearGradient id="lineAreaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={theme.primary} stopOpacity="0.35" />
              <stop offset="100%" stopColor={theme.primary} stopOpacity="0.0" />
            </linearGradient>
          </defs>

          {show_area && (
            <path
              d={areaD}
              fill="url(#lineAreaGrad)"
              opacity={lineProgress}
            />
          )}

          <line
            x1={paddingLeft}
            y1={svgHeight - paddingBottom}
            x2={svgWidth - paddingRight}
            y2={svgHeight - paddingBottom}
            stroke={theme.border}
            strokeWidth="2"
          />

          <path
            d={pathD}
            fill="none"
            stroke={theme.accent}
            strokeWidth="5"
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeDasharray="2000"
            strokeDashoffset={2000 * (1 - lineProgress)}
          />

          {coords.map((c, idx) => {
            const pointAppearFrame = 8 + Math.round((idx / Math.max(1, count - 1)) * durationInFrames * 0.55);
            const spr = spring({
              frame: Math.max(0, frame - pointAppearFrame),
              fps,
              config: { damping: 12, stiffness: 100, mass: 0.8 },
            });
            const pointScale = interpolate(spr, [0, 1], [0, 1]);
            const pointOpacity = interpolate(spr, [0, 1], [0, 1]);

            const displayVal = c.point.display_value || `${c.point.y_value}${unit ? ` ${unit}` : ''}`;

            return (
              <g key={idx} opacity={pointOpacity} transform={`scale(${pointScale})`} style={{ transformOrigin: `${c.x}px ${c.y}px` }}>
                <circle cx={c.x} cy={c.y} r="7" fill={theme.background} stroke={theme.text} strokeWidth="3" />
                <text
                  x={c.x}
                  y={c.y - 14}
                  fill={theme.text}
                  fontSize={isPortrait ? "18" : "20"}
                  fontWeight="800"
                  textAnchor="middle"
                >
                  {displayVal}
                </text>
                <text
                  x={c.x}
                  y={svgHeight - paddingBottom + 24}
                  fill={theme.muted}
                  fontSize={isPortrait ? "14" : "16"}
                  fontWeight="600"
                  textAnchor="middle"
                >
                  {c.point.x_label}
                </text>
              </g>
            );
          })}
        </svg>
      </Card>
    </Layout>
  );
};
