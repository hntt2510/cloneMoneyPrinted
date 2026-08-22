import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { BackgroundTreatment, Theme } from '../types';

export type BackgroundVariant = BackgroundTreatment | 'split_tone' | 'accent_band' | 'flat';

interface BackgroundProps {
  variant?: BackgroundVariant | string;
  theme: Theme;
  subtle_motion?: boolean;
}

export const Background: React.FC<BackgroundProps> = ({ variant = 'radial_light', theme, subtle_motion = true }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const driftY = subtle_motion ? progress * 4 : 0;

  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    overflow: 'hidden',
    zIndex: 0,
  };

  if (variant === 'soft_grid') {
    return (
      <div style={containerStyle}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: theme.background }} />
        {/* Subtle grid pattern */}
        <div
          style={{
            position: 'absolute',
            top: 0, left: 0, right: 0, bottom: 0,
            backgroundImage: `linear-gradient(to right, ${theme.surfaceBorder}40 1px, transparent 1px), linear-gradient(to bottom, ${theme.surfaceBorder}40 1px, transparent 1px)`,
            backgroundSize: '48px 48px',
            opacity: 0.6,
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: `${45 + driftY}%`, left: '50%',
            transform: 'translate(-50%, -50%)',
            width: '80%', height: '60%',
            borderRadius: '50%',
            background: `radial-gradient(ellipse at center, ${theme.primary}14 0%, transparent 70%)`,
          }}
        />
      </div>
    );
  }

  if (variant === 'spotlight') {
    return (
      <div style={containerStyle}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: theme.background }} />
        <div
          style={{
            position: 'absolute',
            top: '0%', left: '50%',
            transform: 'translateX(-50%)',
            width: '65%', height: '75%',
            borderRadius: '50%',
            background: `radial-gradient(ellipse at top, ${theme.primary}22 0%, ${theme.accent}10 40%, transparent 80%)`,
            filter: 'blur(20px)',
          }}
        />
      </div>
    );
  }

  if (variant === 'subtle_texture') {
    return (
      <div style={containerStyle}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: theme.background }} />
        <div
          style={{
            position: 'absolute',
            top: 0, left: 0, right: 0, bottom: 0,
            backgroundImage: `radial-gradient(${theme.surfaceBorder}80 1px, transparent 1px)`,
            backgroundSize: '24px 24px',
            opacity: 0.5,
          }}
        />
      </div>
    );
  }

  if (variant === 'asset_blur') {
    return (
      <div style={containerStyle}>
        <div
          style={{
            position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
            background: `linear-gradient(135deg, ${theme.background}EE 0%, ${theme.surface}CC 100%)`,
            backdropFilter: 'blur(12px)',
          }}
        />
      </div>
    );
  }

  if (variant === 'radial_light') {
    return (
      <div style={containerStyle}>
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
          background: theme.background,
        }} />
        <div style={{
          position: 'absolute',
          top: `${40 + driftY}%`, left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '70%', height: '60%',
          borderRadius: '50%',
          background: `radial-gradient(ellipse at center, ${theme.primary}18 0%, transparent 70%)`,
        }} />
      </div>
    );
  }
  
  if (variant === 'split_tone') {
    return (
      <div style={containerStyle}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: theme.background }} />
        <div style={{
          position: 'absolute', top: 0, right: 0, width: '38%', bottom: 0,
          background: `linear-gradient(to left, ${theme.surface}80, transparent)`,
        }} />
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: '2px',
          background: `linear-gradient(to right, transparent, ${theme.accent}40, transparent)`,
        }} />
      </div>
    );
  }
  
  if (variant === 'gradient_field') {
    return (
      <div style={containerStyle}>
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
          background: `linear-gradient(160deg, ${theme.background} 0%, ${theme.surface}99 100%)`,
        }} />
      </div>
    );
  }

  if (variant === 'accent_band') {
    return (
      <div style={containerStyle}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, background: theme.background }} />
        <div style={{
          position: 'absolute', bottom: 0, left: 0, right: 0, height: '4px',
          background: `linear-gradient(to right, ${theme.primary}, ${theme.accent})`,
        }} />
      </div>
    );
  }

  // neutral_flat / flat
  return <div style={{ ...containerStyle, background: theme.background }} />;
};
