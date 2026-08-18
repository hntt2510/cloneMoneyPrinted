import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { ThresholdProps } from '../types';

export const ThresholdTemplate: React.FC<ThresholdProps> = ({
  headline,
  current_value,
  current_display,
  threshold_value,
  threshold_display,
  threshold_label = 'Threshold',
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
  animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;
  const maxVal = Math.max(current_value, threshold_value, 1) * 1.25;
  const currentPct = Math.min(100, Math.max(5, (current_value / maxVal) * 100));
  const thresholdPct = Math.min(95, Math.max(5, (threshold_value / maxVal) * 100));
  
  // Phase beats
  const limitBeat = animation_plan?.beats?.find(b => b.kind === 'threshold');
  const growBeat = animation_plan?.beats?.find(b => b.kind === 'number');
  const crossBeat = animation_plan?.beats?.find(b => b.kind === 'highlight');
  const resolveBeat = animation_plan?.beats?.find(b => b.kind === 'resolve');

  const limitStart = isContinuous ? 0 : (limitBeat?.start_frame ?? 0);
  const limitEnd = isContinuous ? 5 : (limitBeat?.end_frame ?? 20);
  const growStart = isContinuous ? 0 : (growBeat?.start_frame ?? limitEnd);
  const growEnd = isContinuous ? 5 : (growBeat?.end_frame ?? growStart + 30);
  const crossStart = isContinuous ? 0 : (crossBeat?.start_frame ?? growEnd);
  const resolveStart = isContinuous ? 0 : (resolveBeat?.start_frame ?? crossStart + 10);

  // 1. Limit marker slide-in
  const limitSpr = spring({ frame: Math.max(0, frame - limitStart), fps, config: { damping: 14, stiffness: 90 } });
  const limitY = isContinuous ? 0 : interpolate(limitSpr, [0, 1], [-20, 0]);
  const limitOp = isContinuous ? 1 : interpolate(limitSpr, [0, 1], [0, 1]);

  // 2. Bar grow (pre-threshold and post-threshold)
  const growPct = isContinuous ? 1 : interpolate(frame, [growStart, growEnd], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const growEased = spring({ frame: growPct * fps, fps, config: { damping: 16, stiffness: 60 } });
  
  const animatedCurrentPct = growEased * currentPct;
  const baseFillPct = Math.min(animatedCurrentPct, thresholdPct);
  const overflowFillPct = Math.max(0, animatedCurrentPct - thresholdPct);

  // 3. Crossing pulse
  const crossSpr = spring({ frame: Math.max(0, frame - crossStart), fps, config: { damping: 10, stiffness: 120 } });
  const markerPulse = interpolate(crossSpr, [0, 0.4, 1], [1, 1.4, 1]);
  const overflowColorSpr = interpolate(crossSpr, [0, 1], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // 4. Resolve labels
  const resolveSpr = spring({ frame: Math.max(0, frame - resolveStart), fps, config: { damping: 14, stiffness: 90 } });
  const resolveOp = isContinuous ? 1 : interpolate(resolveSpr, [0, 1], [0, 1]);
  const resolveY = isContinuous ? 0 : interpolate(resolveSpr, [0, 1], [10, 0]);

  const hasOverflow = current_value > threshold_value;
  const overflowColor = hasOverflow ? theme.warning : theme.positive;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="radial_light" theme={theme} subtle_motion />
      
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        padding: '0 5%',
      }}>
        {/* Headline */}
        <div style={{
          position: 'absolute', top: '15%',
          fontSize: isPortrait ? 32 : 48, fontWeight: 800, color: theme.text,
          opacity: limitOp, transform: `translateY(${limitY}px)`,
        }}>
          {headline}
        </div>

        {/* Track Area */}
        <div style={{
          position: 'relative',
          width: isPortrait ? '90%' : '70%',
          height: 24,
          backgroundColor: theme.surfaceBorder,
          borderRadius: 12,
          marginTop: '10%',
        }}>
          {/* Base Fill */}
          <div style={{
            position: 'absolute', top: 0, left: 0, height: '100%',
            width: `${baseFillPct}%`,
            backgroundColor: theme.primary,
            borderRadius: 12,
          }} />

          {/* Overflow Fill */}
          {hasOverflow && overflowFillPct > 0 && (
            <div style={{
              position: 'absolute', top: 0, left: `${thresholdPct}%`, height: '100%',
              width: `${overflowFillPct}%`,
              backgroundColor: overflowColor,
              opacity: overflowColorSpr,
              borderRadius: '0 12px 12px 0',
              boxShadow: `0 0 12px ${overflowColor}80`,
            }} />
          )}

          {/* Threshold Marker */}
          <div style={{
            position: 'absolute', top: -16, bottom: -16, left: `${thresholdPct}%`,
            width: 4, backgroundColor: theme.text,
            transform: `translateX(-50%) scale(${markerPulse})`,
            opacity: limitOp,
            boxShadow: '0 0 8px rgba(255,255,255,0.5)',
          }}>
            {/* Limit Label Above Marker */}
            <div style={{
              position: 'absolute', bottom: '100%', left: '50%',
              transform: 'translateX(-50%)', marginBottom: 12,
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              whiteSpace: 'nowrap',
            }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>{threshold_label}</span>
              <span style={{ fontSize: 24, fontWeight: 900, color: theme.text }}>{threshold_display || threshold_value}</span>
            </div>
          </div>
          
          {/* Current Value Label (follows the bar) */}
          {animatedCurrentPct > 0 && (
            <div style={{
              position: 'absolute', bottom: '100%', left: `${animatedCurrentPct}%`,
              transform: 'translateX(-50%)', marginBottom: 12,
              display: 'flex', flexDirection: 'column', alignItems: 'center',
              whiteSpace: 'nowrap',
            }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: hasOverflow ? overflowColor : theme.positive, textTransform: 'uppercase' }}>DAMAGE</span>
              <span style={{ fontSize: 28, fontWeight: 900, color: hasOverflow ? overflowColor : theme.positive }}>{current_display || current_value}</span>
            </div>
          )}
        </div>

        {/* Resolve Label (OVER LIMIT) */}
        {hasOverflow && (
          <div style={{
            position: 'absolute', bottom: '25%',
            opacity: resolveOp, transform: `translateY(${resolveY}px)`,
            fontSize: isPortrait ? 28 : 36, fontWeight: 900,
            color: theme.warning, letterSpacing: '0.05em',
            backgroundColor: `${theme.warning}20`, padding: '8px 24px', borderRadius: 8,
            border: `2px solid ${theme.warning}50`,
          }}>
            OVER LIMIT
          </div>
        )}
      </div>
    </Layout>
  );
};
