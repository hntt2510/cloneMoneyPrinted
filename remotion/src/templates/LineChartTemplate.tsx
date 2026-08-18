import React from 'react';
import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { SlideIn } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { LineChartProps } from '../types';

export const LineChartTemplate: React.FC<LineChartProps> = ({
  headline, points, theme: customTheme, isGrouped = false, animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const maxVal = Math.max(...points.map(p => p.y_value), 1);
  const minVal = Math.min(...points.map(p => p.y_value), 0);
  const range = maxVal - minVal || 1;
  
  const chartW = isPortrait ? width * 0.8 : width * 0.7;
  const chartH = isPortrait ? height * 0.4 : height * 0.5;

  // Grid / Axes
  const gridOp = interpolate(frame, [0, 15], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const gridLines = [0, 0.33, 0.66, 1].map(pct => minVal + (range * pct));

  // Path coordinates
  const coords = points.map((p, i) => {
    const x = (i / Math.max(1, points.length - 1)) * chartW;
    const y = chartH - ((p.y_value - minVal) / range) * chartH;
    return { x, y, p };
  });

  const pathD = coords.reduce((acc, curr, idx) => {
    return acc + (idx === 0 ? `M ${curr.x},${curr.y}` : ` L ${curr.x},${curr.y}`);
  }, "");

  // Path animation
  const totalLength = chartW * 2; // rough estimate
  const lastPointBeat = animation_plan?.beats?.find(b => b.data_ref === `point_${points.length - 1}`);
  const lineEndFrame = lastPointBeat?.start_frame ?? 60;
  
  const drawPct = interpolate(frame, [15, lineEndFrame], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const strokeDashoffset = totalLength * (1 - drawPct);

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />
      
      <SlideIn startFrame={0}>
        <div style={{ position: 'absolute', top: '10%', width: '100%', textAlign: 'center', fontSize: isPortrait ? 32 : 48, fontWeight: 800, color: theme.text }}>
          {headline}
        </div>
      </SlideIn>

      <div style={{ position: 'absolute', top: '25%', left: (width - chartW) / 2, width: chartW, height: chartH, opacity: gridOp }}>
        <svg width={chartW} height={chartH} style={{ overflow: 'visible' }}>
          {/* Grid lines */}
          {gridLines.map((gl, i) => {
            const y = chartH - ((gl - minVal) / range) * chartH;
            return (
              <line key={`grid-${i}`} x1={0} y1={y} x2={chartW} y2={y} stroke={theme.surfaceBorder} strokeWidth={2} strokeDasharray="4 4" />
            );
          })}
          
          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={chartH} stroke={theme.muted} strokeWidth={2} />
          <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke={theme.muted} strokeWidth={2} />
          
          {/* The Line */}
          <path d={pathD} fill="none" stroke={theme.accent} strokeWidth={4} strokeDasharray={totalLength} strokeDashoffset={strokeDashoffset} />
          
          {/* Points */}
          {coords.map((c, i) => {
            const beat = animation_plan?.beats?.find(b => b.data_ref === `point_${i}`);
            const startFrame = beat?.start_frame ?? (15 + i * 15);
            
            if (frame < startFrame) return null;
            
            const isLast = i === coords.length - 1;
            const r = isLast ? interpolate(frame, [startFrame, startFrame+10], [0, 8], { extrapolateRight: 'clamp' }) : 6;
            
            return (
              <g key={`pt-${i}`}>
                <circle cx={c.x} cy={c.y} r={r} fill={theme.primary} stroke={theme.background} strokeWidth={2} />
                <text x={c.x} y={chartH + 24} fill={theme.muted} fontSize={16} fontWeight={600} textAnchor="middle">{c.p.x_label}</text>
                <text x={c.x} y={c.y - 16} fill={theme.text} fontSize={20} fontWeight={800} textAnchor="middle">{c.p.display_value || c.p.y_value}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </Layout>
  );
};
