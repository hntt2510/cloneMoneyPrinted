import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Card } from '../components/Card';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { Theme, ThresholdProps } from '../types';

export const ThresholdTemplate: React.FC<ThresholdProps> = ({
  headline,
  current_value,
  current_display,
  threshold_value,
  threshold_display,
  threshold_label = 'Threshold',
  subtext,
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

  let animatedCurrentPct = currentPct;
  let pulseScale = 1;

  if (isContinuous) {
    animatedCurrentPct = currentPct;
  } else if (animation_plan?.beats && animation_plan.beats.some(b => b.kind === 'threshold')) {
    const tBeat = animation_plan.beats.find(b => b.kind === 'threshold')!;
    const phase1Duration = Math.max(1, tBeat.end_frame - tBeat.start_frame) * 0.5;
    const phase2Start = tBeat.start_frame + phase1Duration;
    
    // Phase 1: 0 to threshold (or current if current < threshold)
    const target1 = Math.min(currentPct, thresholdPct);
    const p1 = interpolate(frame, [tBeat.start_frame, tBeat.start_frame + phase1Duration], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
    const ease1 = spring({ frame: p1 * fps, fps, config: { damping: 14, stiffness: 60 } });
    
    // Phase 2: threshold to current (only if current > threshold)
    let p2 = 0;
    let ease2 = 0;
    if (currentPct > thresholdPct) {
      p2 = interpolate(frame, [phase2Start, tBeat.end_frame], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
      ease2 = spring({ frame: p2 * fps, fps, config: { damping: 14, stiffness: 60 } });
      
      const pulseSpr = spring({
        frame: Math.max(0, frame - phase2Start),
        fps,
        config: { damping: 10, stiffness: 120 }
      });
      pulseScale = 1 + interpolate(pulseSpr, [0, 1], [0, 0.15]) - interpolate(pulseSpr, [0, 1], [0, 0.15]);
    }
    
    animatedCurrentPct = (target1 * ease1) + ((currentPct - target1) * ease2);
  } else {
    const spr = spring({
      frame: Math.max(0, frame - 8),
      fps,
      config: { damping: 14, stiffness: 90, mass: 0.9 },
    });
    animatedCurrentPct = currentPct * interpolate(spr, [0, 1], [0, 1]);
  }

  const meetsThreshold = current_value >= threshold_value;
  const statusColor = meetsThreshold ? theme.positive : theme.warning;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header
        headline={headline}
        subheadline={subtext}
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
      />
      <Card
        theme={theme}
        isGrouped={isGrouped}
        isFirstInGroup={isFirstInGroup}
        style={{ width: isPortrait ? '92%' : '75%', padding: '36px 32px' }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            width: '100%',
            marginBottom: 28,
          }}
        >
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>
              Current Value
            </div>
            <div style={{ fontSize: isPortrait ? 36 : 48, fontWeight: 900, color: statusColor, marginTop: 4 }}>
              {current_display || current_value}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>
              {threshold_label}
            </div>
            <div style={{ fontSize: isPortrait ? 36 : 48, fontWeight: 900, color: theme.text, marginTop: 4 }}>
              {threshold_display || threshold_value}
            </div>
          </div>
        </div>

        <div
          style={{
            position: 'relative',
            width: '100%',
            height: 32,
            backgroundColor: theme.surfaceBorder,
            borderRadius: 16,
            overflow: 'visible',
          }}
        >
          <div
            style={{
              width: `${animatedCurrentPct}%`,
              height: '100%',
              backgroundColor: statusColor,
              borderRadius: 16,
              boxShadow: `0 0 20px ${statusColor}60`,
            }}
          />

          <div
            style={{
              position: 'absolute',
              left: `${thresholdPct}%`,
              top: -10,
              bottom: -10,
              width: 4,
              backgroundColor: theme.text,
              borderRadius: 2,
              transform: `scale(${pulseScale})`,
              boxShadow: '0 0 10px rgba(255,255,255,0.8)',
              zIndex: 2,
            }}
          />
        </div>
      </Card>
    </Layout>
  );
};
