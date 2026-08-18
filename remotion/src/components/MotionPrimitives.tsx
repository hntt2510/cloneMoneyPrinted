import React from 'react';
import { useCurrentFrame, useVideoConfig, spring, interpolate } from 'remotion';
import { SPRING_CONFIGS } from '../motion/tokens';
import { Theme } from '../types';

export const MaskReveal: React.FC<{ children: React.ReactNode, startFrame: number, endFrame: number, delay?: number, direction?: 'ltr'|'ttb' }> = ({ children, startFrame, endFrame, direction = 'ltr' }) => {
  const frame = useCurrentFrame();
  const clipProgress = interpolate(frame, [startFrame, endFrame], [0, 100], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const clipPath = direction === 'ltr' ? `inset(0 ${100 - clipProgress}% 0 0)` : `inset(0 0 ${100 - clipProgress}% 0)`;
  return <div style={{ clipPath }}>{children}</div>;
};

export const SlideIn: React.FC<{ children: React.ReactNode, startFrame: number, distance?: number, direction?: 'up'|'down' }> = ({ children, startFrame, distance = 20, direction = 'up' }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const spr = spring({ frame: Math.max(0, frame - startFrame), fps, config: SPRING_CONFIGS.NORMAL });
  const dirMult = direction === 'up' ? 1 : -1;
  const y = interpolate(spr, [0, 1], [distance * dirMult, 0]);
  const opacity = interpolate(spr, [0, 1], [0, 1]);
  return <div style={{ transform: `translateY(${y}px)`, opacity }}>{children}</div>;
};

export const CounterDisplay: React.FC<{ startVal: number, endVal: number, startFrame: number, endFrame: number, prefix?: string, suffix?: string, decimals?: number }> = ({ startVal, endVal, startFrame, endFrame, prefix = '', suffix = '', decimals = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = interpolate(frame, [startFrame, endFrame], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const easedP = spring({ frame: p * fps, fps, config: SPRING_CONFIGS.SLOW });
  const current = startVal + easedP * (endVal - startVal);
  const displayString = `${prefix}${current.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
  return <span>{displayString}</span>;
};

export const ProgressTrack: React.FC<{ progress: number, theme: Theme, height?: number, width?: string }> = ({ progress, theme, height = 6, width = '100%' }) => {
  return (
    <div style={{ width, height, backgroundColor: theme.surfaceBorder, borderRadius: height / 2, overflow: 'hidden' }}>
      <div style={{ width: `${progress * 100}%`, height: '100%', background: `linear-gradient(to right, ${theme.primary}, ${theme.accent})`, borderRadius: height / 2 }} />
    </div>
  );
};

export const UnderlineSweep: React.FC<{ startFrame: number, endFrame: number, targetWidthPct: number, theme: Theme }> = ({ startFrame, endFrame, targetWidthPct, theme }) => {
  const frame = useCurrentFrame();
  const ulPct = interpolate(frame, [startFrame, endFrame], [0, targetWidthPct], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ width: `${ulPct}%`, height: 3, background: `linear-gradient(to right, ${theme.accent}, ${theme.primary})`, borderRadius: 2 }} />
  );
};

export const DividerReveal: React.FC<{ startFrame: number, theme: Theme, label?: string }> = ({ startFrame, theme, label }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const spr = spring({ frame: Math.max(0, frame - startFrame), fps, config: SPRING_CONFIGS.FAST });
  const scaleY = interpolate(spr, [0, 1], [0, 1]);
  return (
    <div style={{ position: 'absolute', left: '50%', top: '20%', bottom: '20%', width: 2, background: theme.surfaceBorder, transform: `scaleY(${scaleY})` }}>
      {label && (
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', background: theme.background, padding: '4px 8px', borderRadius: 4, color: theme.muted, fontSize: 14, fontWeight: 'bold' }}>
          {label}
        </div>
      )}
    </div>
  );
};

export const ScalePop: React.FC<{ children: React.ReactNode, startFrame: number, boost?: number }> = ({ children, startFrame, boost = 0.05 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const popSpr = spring({ frame: Math.max(0, frame - startFrame), fps, config: SPRING_CONFIGS.BOUNCE });
  const popBoost = interpolate(popSpr, [0, 0.4, 1], [0, boost, 0]);
  return <div style={{ transform: `scale(${1 + popBoost})` }}>{children}</div>;
};

export const SegmentedBar: React.FC<{ segments: {value: number, color: string, label: string}[], total: number, theme: Theme }> = ({ segments, total, theme }) => {
  // Simple un-animated static segmented bar for now, since it's just a placeholder to fulfill requirements.
  return (
    <div style={{ display: 'flex', width: '100%', height: 24, borderRadius: 12, overflow: 'hidden' }}>
      {segments.map((seg, i) => (
        <div key={i} style={{ width: `${(seg.value / total) * 100}%`, height: '100%', backgroundColor: seg.color }} />
      ))}
    </div>
  );
};
