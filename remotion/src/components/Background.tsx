import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import { Theme } from '../types';

type BackgroundVariant = 'gradient_field' | 'radial_light' | 'split_tone' | 'accent_band' | 'flat';

interface BackgroundProps {
  variant?: BackgroundVariant;
  theme: Theme;
  subtle_motion?: boolean;
}

export const Background: React.FC<BackgroundProps> = ({ variant = 'flat', theme, subtle_motion = false }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, width, height } = useVideoConfig();
  
  const progress = interpolate(frame, [0, durationInFrames], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const driftY = subtle_motion ? progress * 4 : 0; // max 4px drift

  const containerStyle: React.CSSProperties = {
    position: 'absolute',
    top: 0, left: 0, right: 0, bottom: 0,
    overflow: 'hidden',
  };

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
          background: `linear-gradient(160deg, ${theme.background} 0%, ${theme.surface}80 100%)`,
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

  // flat
  return <div style={{ ...containerStyle, background: theme.background }} />;
};
