import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { NumberProps, Theme } from '../types';

export const NumberTemplate: React.FC<NumberProps> = ({
  headline, value, prefix, suffix, label, subtext,
  eyebrow, context_label,
  theme: customTheme, isGrouped = false, isFirstInGroup = true, animation_plan, numeric_value,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;
  const isContinuous = isGrouped && !isFirstInGroup;

  // Get beats
  const setupBeat = animation_plan?.beats?.find(b => b.kind === 'setup');
  const revealBeat = animation_plan?.beats?.find(b => b.kind === 'reveal');
  const numberBeat = animation_plan?.beats?.find(b => b.kind === 'number');
  const highlightBeat = animation_plan?.beats?.find(b => b.kind === 'highlight');
  const contextBeat = animation_plan?.beats?.find(b => b.kind === 'phrase');

  // EYEBROW: MaskReveal left-to-right
  const eyebrowStart = isContinuous ? 0 : (setupBeat?.start_frame ?? 0);
  const eyebrowEnd = isContinuous ? 5 : (setupBeat?.end_frame ?? 10);

  // HEADLINE: SlideIn from y=20
  const headlineStart = isContinuous ? 0 : (revealBeat?.start_frame ?? eyebrowEnd);
  const headlineEnd = isContinuous ? 5 : (revealBeat?.end_frame ?? eyebrowEnd + 8);

  // UNDERLINE: sweeps after headline
  const underlineStart = headlineEnd;
  const underlineEnd = underlineStart + 8;

  // COUNTER: number beat
  const counterStart = isContinuous ? 0 : (numberBeat?.start_frame ?? underlineEnd);
  const counterEnd = isContinuous ? 5 : (numberBeat?.end_frame ?? counterStart + 30);

  // PROGRESS TRACK: grows in sync with counter
  const trackProgress = interpolate(frame, [counterStart, counterEnd], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // SCALE POP on settle
  const popSpr = highlightBeat ? spring({ frame: Math.max(0, frame - highlightBeat.start_frame), fps, config: { damping: 8, stiffness: 200 } }) : 0;
  const popBoost = interpolate(popSpr, [0, 0.4, 1], [0, 0.04, 0]);

  // CONTEXT LABEL
  const ctxStart = isContinuous ? 0 : (contextBeat?.start_frame ?? counterEnd + 5);

  // COUNTER VALUE & DEDUPLICATION
  const rawValue = (value ?? '').toString();
  const rawPrefix = prefix || '';
  const rawSuffix = suffix || '';

  // Strip duplicate leading prefix or trailing suffix already embedded in value
  let cleanValue = rawValue;
  if (rawPrefix && cleanValue.startsWith(rawPrefix)) {
    cleanValue = cleanValue.slice(rawPrefix.length);
  }
  if (rawSuffix && cleanValue.endsWith(rawSuffix)) {
    cleanValue = cleanValue.slice(0, -rawSuffix.length);
  }

  let displayString = `${rawPrefix}${cleanValue}${rawSuffix}`;
  if (numeric_value != null && numberBeat) {
    if (frame < counterStart && !isContinuous) {
      displayString = '';
    } else {
      const cp = interpolate(frame, [counterStart, counterEnd], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
      const easedP = spring({ frame: cp * fps, fps, config: { damping: 16, stiffness: 45 } });
      const current = easedP * numeric_value;
      const decimals = cleanValue.includes('.') ? cleanValue.split('.')[1].length : 0;
      if (frame < counterEnd) {
        displayString = `${rawPrefix}${current.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${rawSuffix}`;
      }
    }
  }

  const eyebrowSize = Math.min(28, Math.max(14, Math.round(isPortrait ? width * 0.038 : width * 0.020)));
  const headlineSize = Math.min(52, Math.max(24, Math.round(isPortrait ? width * 0.065 : width * 0.038)));
  const valueSize = Math.min(140, Math.max(48, Math.round(isPortrait ? width * 0.16 : width * 0.085)));
  const labelSize = Math.min(28, Math.max(14, Math.round(isPortrait ? width * 0.038 : width * 0.022)));

  // Eyebrow clipPath reveal
  const eyebrowClip = isContinuous ? 100 : interpolate(frame, [eyebrowStart, eyebrowEnd], [0, 100], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // Headline slide
  const headlineSpr = spring({ frame: Math.max(0, frame - headlineStart), fps, config: { damping: 14, stiffness: 90, mass: 0.9 } });
  const headlineY = isContinuous ? 0 : interpolate(headlineSpr, [0, 1], [20, 0]);
  const headlineOp = isContinuous ? 1 : interpolate(headlineSpr, [0, 1], [0, 1]);

  // Underline sweep
  const ulPct = isContinuous ? 45 : interpolate(frame, [underlineStart, underlineEnd], [0, 45], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  // Counter spring
  const valueSpr = spring({ frame: Math.max(0, frame - counterStart), fps, config: { damping: 14, stiffness: 90, mass: 0.9 } });
  const valueOp = isContinuous ? 1 : interpolate(valueSpr, [0, 1], [0, 1]);
  const valueScale = isContinuous ? 1 : interpolate(valueSpr, [0, 1], [0.88, 1]) * (1 + popBoost);

  // Context label slide
  const ctxSpr = spring({ frame: Math.max(0, frame - ctxStart), fps, config: { damping: 14, stiffness: 80 } });
  const ctxOp = isContinuous ? 1 : interpolate(ctxSpr, [0, 1], [0, 1]);
  const ctxY = isContinuous ? 0 : interpolate(ctxSpr, [0, 1], [12, 0]);

  const displayEyebrow = eyebrow || label || null;
  const displayContext = context_label || subtext || null;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="radial_light" theme={theme} subtle_motion />
      <div style={{
        position: 'relative', zIndex: 1,
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        width: '100%', height: '100%',
        gap: Math.round(height * 0.02),
      }}>
        {/* EYEBROW */}
        {displayEyebrow && (
          <div style={{
            clipPath: `inset(0 ${100 - eyebrowClip}% 0 0)`,
            fontSize: eyebrowSize, fontWeight: 700,
            color: theme.muted, textTransform: 'uppercase', letterSpacing: '0.12em',
          }}>
            {displayEyebrow}
          </div>
        )}

        {/* HEADLINE */}
        <div style={{
          opacity: headlineOp, transform: `translateY(${headlineY}px)`,
          fontSize: headlineSize, fontWeight: 800,
          color: theme.text, letterSpacing: '-0.02em',
          textAlign: 'center',
        }}>
          {headline}
        </div>

        {/* UNDERLINE SWEEP */}
        <div style={{
          width: `${ulPct}%`, height: 3,
          background: `linear-gradient(to right, ${theme.accent}, ${theme.primary})`,
          borderRadius: 2, marginBottom: Math.round(height * 0.01),
        }} />

        {/* VALUE COUNTER */}
        <div style={{
          opacity: valueOp, transform: `scale(${valueScale})`,
          fontSize: valueSize, fontWeight: 900,
          color: theme.accent, letterSpacing: '-0.04em', lineHeight: 1.0,
          textShadow: `0 8px 40px ${theme.primary}50`,
        }}>
          {displayString}
        </div>

        {/* PROGRESS TRACK (grows in sync with counter) */}
        <div style={{
          width: isPortrait ? '80%' : '50%', height: 6,
          backgroundColor: theme.surfaceBorder, borderRadius: 3,
          overflow: 'hidden', marginTop: Math.round(height * 0.015),
        }}>
          <div style={{
            width: `${trackProgress * 100}%`, height: '100%',
            background: `linear-gradient(to right, ${theme.primary}, ${theme.accent})`,
            borderRadius: 3,
            boxShadow: `0 0 12px ${theme.accent}60`,
          }} />
        </div>

        {/* CONTEXT LABEL */}
        {displayContext && (
          <div style={{
            opacity: ctxOp, transform: `translateY(${ctxY}px)`,
            marginTop: Math.round(height * 0.01),
            fontSize: labelSize, fontWeight: 600,
            color: theme.muted, letterSpacing: '0.06em', textTransform: 'uppercase',
          }}>
            {displayContext}
          </div>
        )}
      </div>
    </Layout>
  );
};
