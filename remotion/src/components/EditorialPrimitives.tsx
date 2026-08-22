import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Theme } from '../types';

interface CameraPushProps {
  children: React.ReactNode;
  scaleTo?: number;
  maxPanY?: number;
  disabled?: boolean;
  style?: React.CSSProperties;
}

export const CameraPush: React.FC<CameraPushProps> = ({
  children,
  scaleTo = 1.03,
  maxPanY = 4,
  disabled = false,
  style,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  if (disabled) {
    return <div style={{ width: '100%', height: '100%', ...style }}>{children}</div>;
  }

  const scale = interpolate(
    frame,
    [0, Math.max(1, durationInFrames)],
    [1.0, scaleTo],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const panY = interpolate(
    frame,
    [0, Math.max(1, durationInFrames)],
    [0, maxPanY],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        transform: `scale(${scale}) translateY(${panY}px)`,
        transformOrigin: 'center center',
        ...style,
      }}
    >
      {children}
    </div>
  );
};

interface UnderlineDrawProps {
  progress: number;
  color?: string;
  height?: number;
  style?: React.CSSProperties;
}

export const UnderlineDraw: React.FC<UnderlineDrawProps> = ({
  progress,
  color = '#ffffff',
  height = 3,
  style,
}) => {
  const widthPct = Math.min(100, Math.max(0, progress * 100));
  return (
    <div
      style={{
        position: 'relative',
        width: '100%',
        height,
        backgroundColor: 'transparent',
        display: 'flex',
        justifyContent: 'center',
        marginTop: 6,
        ...style,
      }}
    >
      <div
        style={{
          width: `${widthPct}%`,
          height: '100%',
          backgroundColor: color,
          borderRadius: height / 2,
          boxShadow: `0 0 12px ${color}88`,
          transition: 'width 0.1s ease',
        }}
      />
    </div>
  );
};

interface StatBadgeProps {
  label: string;
  value?: string | null;
  color?: string;
  size?: 'sm' | 'md' | 'lg';
  style?: React.CSSProperties;
}

export const StatBadge: React.FC<StatBadgeProps> = ({
  label,
  value,
  color = '#4ade80',
  size = 'md',
  style,
}) => {
  const fontSizeLabel = size === 'sm' ? 11 : size === 'lg' ? 14 : 12;
  const fontSizeValue = size === 'sm' ? 16 : size === 'lg' ? 24 : 20;

  return (
    <div
      style={{
        display: 'inline-flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 2,
        padding: size === 'sm' ? '6px 16px' : '8px 22px',
        borderRadius: 14,
        backgroundColor: `${color}18`,
        border: `1.5px solid ${color}80`,
        boxShadow: `0 0 18px ${color}2A`,
        textAlign: 'center',
        ...style,
      }}
    >
      <span
        style={{
          fontSize: fontSizeLabel,
          fontWeight: 800,
          letterSpacing: '0.10em',
          color,
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      {value && (
        <span
          style={{
            fontSize: fontSizeValue,
            fontWeight: 900,
            color: '#ffffff',
            textShadow: `0 0 10px ${color}`,
          }}
        >
          {value}
        </span>
      )}
    </div>
  );
};

interface DataConnectorProps {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  progress?: number;
  color?: string;
  strokeWidth?: number;
  dashed?: boolean;
}

export const DataConnector: React.FC<DataConnectorProps> = ({
  x1,
  y1,
  x2,
  y2,
  progress = 1.0,
  color = 'rgba(255,255,255,0.4)',
  strokeWidth = 2,
  dashed = false,
}) => {
  const currentX2 = x1 + (x2 - x1) * Math.min(1, Math.max(0, progress));
  const currentY2 = y1 + (y2 - y1) * Math.min(1, Math.max(0, progress));

  return (
    <svg
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 2,
      }}
    >
      <line
        x1={x1}
        y1={y1}
        x2={currentX2}
        y2={currentY2}
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={dashed ? '4 4' : undefined}
      />
    </svg>
  );
};

interface FocusFrameProps {
  active?: boolean;
  color?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export const FocusFrame: React.FC<FocusFrameProps> = ({
  active = true,
  color = '#60a5fa',
  children,
  style,
}) => {
  return (
    <div
      style={{
        position: 'relative',
        borderRadius: 20,
        backgroundColor: active ? 'rgba(255,255,255,0.04)' : 'transparent',
        border: active ? `1.5px solid ${color}66` : '1.5px solid transparent',
        boxShadow: active ? `0 0 24px ${color}1F` : 'none',
        transition: 'all 0.25s ease',
        ...style,
      }}
    >
      {children}
    </div>
  );
};
