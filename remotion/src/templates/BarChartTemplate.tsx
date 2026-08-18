import React from 'react';
import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { SlideIn } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { BarChartProps } from '../types';

export const BarChartTemplate: React.FC<BarChartProps> = ({
  headline, items, theme: customTheme, isGrouped = false, animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  // Axes and grid fade in (first 15 frames)
  const gridOp = interpolate(frame, [0, 15], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  const maxVal = Math.max(...items.map(i => i.value), 1);
  const gridLines = [0, maxVal * 0.33, maxVal * 0.66, maxVal];

  const chartW = isPortrait ? width * 0.8 : width * 0.7;
  const chartH = isPortrait ? height * 0.4 : height * 0.5;
  const barWidth = (chartW * 0.6) / items.length;
  const spacing = (chartW * 0.4) / (items.length + 1);

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
            const y = chartH - (gl / maxVal) * chartH;
            return (
              <line key={`grid-${i}`} x1={0} y1={y} x2={chartW} y2={y} stroke={theme.surfaceBorder} strokeWidth={2} strokeDasharray="4 4" />
            );
          })}
          
          {/* Axes */}
          <line x1={0} y1={0} x2={0} y2={chartH} stroke={theme.muted} strokeWidth={2} />
          <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke={theme.muted} strokeWidth={2} />
          
          {/* Bars */}
          {items.map((item, idx) => {
            const beat = animation_plan?.beats?.find(b => b.data_ref === `bar_${idx}`);
            const startFrame = beat?.start_frame ?? (15 + idx * 10);
            
            const barH = (item.value / maxVal) * chartH;
            const x = spacing + idx * (barWidth + spacing);
            
            const progress = interpolate(frame, [startFrame, startFrame + 15], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
            const currH = progress * barH;
            const y = chartH - currH;
            
            if (frame < startFrame) return null;
            
            return (
              <g key={`bar-${idx}`}>
                <rect x={x} y={y} width={barWidth} height={currH} fill={item.color || theme.primary} rx={4} ry={4} />
                {progress > 0.5 && (
                  <text x={x + barWidth / 2} y={chartH + 24} fill={theme.muted} fontSize={16} fontWeight={600} textAnchor="middle">{item.label}</text>
                )}
                {progress > 0.8 && (
                  <text x={x + barWidth / 2} y={y - 12} fill={theme.text} fontSize={20} fontWeight={800} textAnchor="middle">{item.display_value || item.value}</text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </Layout>
  );
};
