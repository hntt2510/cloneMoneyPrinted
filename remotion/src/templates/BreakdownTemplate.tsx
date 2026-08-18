import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { MaskReveal, SlideIn } from '../components/MotionPrimitives';
import { SPRING_CONFIGS } from '../motion/tokens';
import { resolveTheme } from '../theme/theme';
import { BaseTemplateProps, Theme } from '../types';

export interface BreakdownTotal {
  label: string;
  value: string;
  numeric_value: number;
}

export interface BreakdownPart {
  label: string;
  value: string;
  numeric_value: number;
  highlight?: boolean;
}

export interface BreakdownProps extends BaseTemplateProps {
  headline?: string;
  eyebrow?: string;
  total?: BreakdownTotal;
  parts?: BreakdownPart[];
  items?: Array<{ label?: string; value?: string; numeric_value?: number | null; highlight?: boolean }>;
  subtext?: string | null;
  scenes?: Array<{
    scene_id: string;
    props?: Record<string, any>;
    start_frame: number;
    end_frame: number;
    duration_frames: number;
  }>;
}

function parseNumeric(val: any): number | null {
  if (typeof val === 'number' && !isNaN(val)) return val;
  if (typeof val === 'string') {
    const cleaned = val.replace(/[\$,]/g, '').trim();
    const parsed = parseFloat(cleaned);
    if (!isNaN(parsed)) return parsed;
  }
  return null;
}

export function resolveBreakdownData(props: BreakdownProps): { total: BreakdownTotal; parts: BreakdownPart[] } | null {
  // 1. Explicit total and parts
  if (props.total && props.parts && Array.isArray(props.parts) && props.parts.length >= 2) {
    const totalVal = Number(props.total.numeric_value) || parseNumeric(props.total.value) || 0;
    const parts = props.parts.map((p, idx) => {
      const pVal = Number(p.numeric_value) || parseNumeric(p.value) || 0;
      return {
        label: p.label || (idx === 0 ? 'YOU PAY' : 'INSURANCE'),
        value: p.value || `$${pVal.toLocaleString()}`,
        numeric_value: pVal,
        highlight: p.highlight !== undefined ? p.highlight : idx === 0,
      };
    });
    const partsSum = parts.reduce((sum, p) => sum + p.numeric_value, 0);
    if (totalVal > 0 && parts.length >= 2 && Math.abs(totalVal - partsSum) <= 1.0) {
      return {
        total: {
          label: props.total.label || 'TOTAL REPAIR',
          value: props.total.value || `$${totalVal.toLocaleString()}`,
          numeric_value: totalVal,
        },
        parts,
      };
    }
  }

  // 2. From group scenes (3 scenes: Scene 0 = Total, Scene 1 = Part 1, Scene 2 = Part 2)
  if (props.scenes && Array.isArray(props.scenes) && props.scenes.length >= 3) {
    const s0 = props.scenes[0]?.props || {};
    const s1 = props.scenes[1]?.props || {};
    const s2 = props.scenes[2]?.props || {};

    const v0 = Number(s0.numeric_value) || parseNumeric(s0.value) || 0;
    const v1 = Number(s1.numeric_value) || parseNumeric(s1.value) || 0;
    const v2 = Number(s2.numeric_value) || parseNumeric(s2.value) || 0;

    if (v0 > 0 && v1 > 0 && v2 > 0 && Math.abs(v0 - (v1 + v2)) <= 1.0) {
      return {
        total: {
          label: s0.headline || s0.eyebrow || 'TOTAL REPAIR',
          value: s0.value || `$${v0.toLocaleString()}`,
          numeric_value: v0,
        },
        parts: [
          {
            label: s1.headline || s1.eyebrow || 'YOU PAY',
            value: s1.value || `$${v1.toLocaleString()}`,
            numeric_value: v1,
            highlight: true,
          },
          {
            label: s2.headline || s2.eyebrow || 'INSURANCE',
            value: s2.value || `$${v2.toLocaleString()}`,
            numeric_value: v2,
            highlight: false,
          },
        ],
      };
    }
  }

  // 3. Derive from items array (3 items where item 0 is total and items 1,2 are parts)
  const rawItems = props.items || [];
  if (rawItems.length === 3) {
    const v0 = Number(rawItems[0].numeric_value) || parseNumeric(rawItems[0].value) || 0;
    const v1 = Number(rawItems[1].numeric_value) || parseNumeric(rawItems[1].value) || 0;
    const v2 = Number(rawItems[2].numeric_value) || parseNumeric(rawItems[2].value) || 0;

    if (v0 > 0 && v1 > 0 && v2 > 0 && Math.abs(v0 - (v1 + v2)) <= 1.0) {
      return {
        total: {
          label: rawItems[0].label || 'TOTAL REPAIR',
          value: rawItems[0].value || `$${v0.toLocaleString()}`,
          numeric_value: v0,
        },
        parts: [
          {
            label: rawItems[1].label || 'YOU PAY',
            value: rawItems[1].value || `$${v1.toLocaleString()}`,
            numeric_value: v1,
            highlight: true,
          },
          {
            label: rawItems[2].label || 'INSURANCE',
            value: rawItems[2].value || `$${v2.toLocaleString()}`,
            numeric_value: v2,
            highlight: false,
          },
        ],
      };
    }
  }

  // 4. Derive from items array (2 parts summing to an explicit positive total)
  if (rawItems.length === 2) {
    const p1 = Number(rawItems[0].numeric_value) || parseNumeric(rawItems[0].value) || 0;
    const p2 = Number(rawItems[1].numeric_value) || parseNumeric(rawItems[1].value) || 0;
    const sumTotal = p1 + p2;
    if (sumTotal > 0 && p1 > 0 && p2 > 0) {
      return {
        total: {
          label: 'TOTAL REPAIR',
          value: `$${sumTotal.toLocaleString()}`,
          numeric_value: sumTotal,
        },
        parts: [
          {
            label: rawItems[0].label || 'YOU PAY',
            value: rawItems[0].value || `$${p1.toLocaleString()}`,
            numeric_value: p1,
            highlight: rawItems[0].highlight ?? true,
          },
          {
            label: rawItems[1].label || 'INSURANCE',
            value: rawItems[1].value || `$${p2.toLocaleString()}`,
            numeric_value: p2,
            highlight: rawItems[1].highlight ?? false,
          },
        ],
      };
    }
  }

  // Strictly return null if ungrounded or mathematically inconsistent - DO NOT INVENT VALUES
  return null;
}

export const BreakdownTemplate: React.FC<BreakdownProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const breakdownData = resolveBreakdownData(props);
  if (!breakdownData) {
    // If breakdown data is invalid or missing grounded numbers, return null or safe fallback
    return null;
  }
  const { total, parts } = breakdownData;

  // Determine storyboard timeline milestones
  let phaseA_end = Math.round(durationInFrames * 0.33);
  let phaseB_end = Math.round(durationInFrames * 0.66);
  let phaseC_end = durationInFrames;

  if (props.scenes && props.scenes.length >= 3) {
    const s0Dur = props.scenes[0].duration_frames || phaseA_end;
    const s1Dur = props.scenes[1].duration_frames || (phaseB_end - phaseA_end);
    phaseA_end = s0Dur;
    phaseB_end = s0Dur + s1Dur;
    phaseC_end = durationInFrames;
  }

  // Phase A: Total bar grows (0 -> phaseA_end)
  const totalBarProgress = interpolate(frame, [5, Math.min(phaseA_end - 5, 35)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const totalBarEased = spring({
    frame: totalBarProgress * fps,
    fps,
    config: SPRING_CONFIGS.NORMAL,
  });

  // Animated Total Counter
  const totalCounterP = interpolate(frame, [5, Math.min(phaseA_end - 5, 35)], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const totalCountEased = spring({
    frame: totalCounterP * fps,
    fps,
    config: SPRING_CONFIGS.SLOW,
  });
  const currentTotalVal = Math.round(totalCountEased * total.numeric_value);
  const totalDisplayStr = frame < phaseA_end - 5
    ? `$${currentTotalVal.toLocaleString()}`
    : total.value;

  // Phase B: Split calculation (starts at phaseA_end)
  const part1Ratio = total.numeric_value > 0 ? parts[0].numeric_value / total.numeric_value : 0.1667;
  const splitP = interpolate(frame, [phaseA_end, phaseA_end + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const splitSpr = spring({
    frame: splitP * fps,
    fps,
    config: SPRING_CONFIGS.NORMAL,
  });

  // Part 1 counter
  const part1CounterP = interpolate(frame, [phaseA_end + 5, phaseA_end + 25], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const part1CountEased = spring({
    frame: part1CounterP * fps,
    fps,
    config: SPRING_CONFIGS.SLOW,
  });
  const currentPart1Val = Math.round(part1CountEased * parts[0].numeric_value);
  const part1DisplayStr = frame < phaseA_end + 25
    ? `$${currentPart1Val.toLocaleString()}`
    : parts[0].value;

  // Phase C: Insurance resolve (starts at phaseB_end)
  const resolveP = interpolate(frame, [phaseB_end, phaseB_end + 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const resolveSpr = spring({
    frame: resolveP * fps,
    fps,
    config: SPRING_CONFIGS.NORMAL,
  });

  // Part 2 counter
  const part2CounterP = interpolate(frame, [phaseB_end + 5, phaseB_end + 25], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const part2CountEased = spring({
    frame: part2CounterP * fps,
    fps,
    config: SPRING_CONFIGS.SLOW,
  });
  const currentPart2Val = Math.round(part2CountEased * parts[1].numeric_value);
  const part2DisplayStr = frame < phaseB_end + 25
    ? `$${currentPart2Val.toLocaleString()}`
    : parts[1].value;

  // Final Equation Pop
  const equationP = interpolate(frame, [phaseB_end + 20, phaseB_end + 35], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const equationSpr = spring({
    frame: equationP * fps,
    fps,
    config: SPRING_CONFIGS.FAST,
  });

  const trackWidth = isPortrait ? '90%' : '75%';
  const part1WidthPct = (part1Ratio * 100);
  const part2WidthPct = (100 - part1WidthPct);

  // Dynamic Headline
  let activeHeadline = total.label;
  if (frame >= phaseB_end) {
    activeHeadline = 'INSURANCE SETTLEMENT';
  } else if (frame >= phaseA_end) {
    activeHeadline = 'YOUR OUT-OF-POCKET';
  }

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <Background variant="split_tone" theme={theme} subtle_motion />

      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '0 5%',
          boxSizing: 'border-box',
        }}
      >
        {/* EYEBROW & HEADLINE */}
        <div style={{ position: 'absolute', top: isPortrait ? '10%' : '12%', textAlign: 'center' }}>
          <div
            style={{
              fontSize: isPortrait ? 16 : 22,
              fontWeight: 700,
              color: theme.accent,
              textTransform: 'uppercase',
              letterSpacing: '0.12em',
              marginBottom: 8,
            }}
          >
            COST BREAKDOWN
          </div>
          <div
            style={{
              fontSize: isPortrait ? 32 : 48,
              fontWeight: 900,
              color: theme.text,
              letterSpacing: '-0.02em',
            }}
          >
            {activeHeadline}
          </div>
        </div>

        {/* TOTAL VALUE DISPLAY (Remains on screen!) */}
        <div
          style={{
            position: 'absolute',
            top: isPortrait ? '24%' : '26%',
            textAlign: 'center',
          }}
        >
          <div style={{ fontSize: isPortrait ? 16 : 20, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>
            {total.label}
          </div>
          <div
            style={{
              fontSize: isPortrait ? 56 : 76,
              fontWeight: 900,
              color: theme.accent,
              letterSpacing: '-0.03em',
              textShadow: `0 8px 32px ${theme.primary}40`,
            }}
          >
            {totalDisplayStr}
          </div>
        </div>

        {/* HORIZONTAL BREAKDOWN BAR */}
        <div
          style={{
            position: 'relative',
            width: trackWidth,
            height: isPortrait ? 36 : 44,
            backgroundColor: theme.surfaceBorder,
            borderRadius: 22,
            marginTop: isPortrait ? '18%' : '14%',
            overflow: 'hidden',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
          }}
        >
          {/* Phase A: Solid Initial Total Bar */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              height: '100%',
              width: `${totalBarEased * 100}%`,
              backgroundColor: theme.primary,
              borderRadius: 22,
            }}
          />

          {/* Phase B: Segment 1 (YOU PAY) Highlights & Separates */}
          {frame >= phaseA_end && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                height: '100%',
                width: `${part1WidthPct * splitSpr}%`,
                backgroundColor: theme.accent,
                boxShadow: `0 0 16px ${theme.accent}`,
                zIndex: 2,
              }}
            />
          )}

          {/* Split Divider */}
          {frame >= phaseA_end && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                bottom: 0,
                left: `${part1WidthPct}%`,
                width: 3,
                backgroundColor: theme.text,
                zIndex: 3,
                boxShadow: '0 0 8px rgba(255,255,255,0.8)',
              }}
            />
          )}

          {/* Phase C: Segment 2 (INSURANCE) Highlights */}
          {frame >= phaseB_end && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: `${part1WidthPct}%`,
                height: '100%',
                width: `${part2WidthPct * resolveSpr}%`,
                backgroundColor: theme.positive,
                boxShadow: `0 0 16px ${theme.positive}`,
                zIndex: 2,
              }}
            />
          )}
        </div>

        {/* SEGMENT LABELS BELOW BAR */}
        <div
          style={{
            position: 'relative',
            width: trackWidth,
            display: 'flex',
            justifyContent: 'space-between',
            marginTop: 16,
          }}
        >
          {/* Part 1 Label (YOU PAY) */}
          {frame >= phaseA_end && (
            <div
              style={{
                opacity: splitSpr,
                transform: `translateY(${interpolate(splitSpr, [0, 1], [10, 0])}px)`,
                textAlign: 'left',
                width: `${part1WidthPct}%`,
              }}
            >
              <div style={{ fontSize: isPortrait ? 14 : 18, fontWeight: 700, color: theme.accent, textTransform: 'uppercase' }}>
                {parts[0].label}
              </div>
              <div style={{ fontSize: isPortrait ? 24 : 32, fontWeight: 900, color: theme.text }}>
                {part1DisplayStr}
              </div>
            </div>
          )}

          {/* Part 2 Label (INSURANCE) */}
          {frame >= phaseB_end && (
            <div
              style={{
                opacity: resolveSpr,
                transform: `translateY(${interpolate(resolveSpr, [0, 1], [10, 0])}px)`,
                textAlign: 'right',
                width: `${part2WidthPct}%`,
              }}
            >
              <div style={{ fontSize: isPortrait ? 14 : 18, fontWeight: 700, color: theme.positive, textTransform: 'uppercase' }}>
                {parts[1].label}
              </div>
              <div style={{ fontSize: isPortrait ? 24 : 32, fontWeight: 900, color: theme.text }}>
                {part2DisplayStr}
              </div>
            </div>
          )}
        </div>

        {/* PHASE D: FINAL RESOLVED EQUATION (Resolves $1K + $5K = $6K) */}
        {frame >= phaseB_end + 15 && (
          <div
            style={{
              position: 'absolute',
              bottom: isPortrait ? '10%' : '12%',
              opacity: equationSpr,
              transform: `scale(${interpolate(equationSpr, [0, 1], [0.92, 1])})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: isPortrait ? 12 : 24,
              backgroundColor: theme.surface,
              border: `1.5px solid ${theme.surfaceBorder}`,
              borderRadius: 16,
              padding: isPortrait ? '12px 18px' : '16px 32px',
              boxShadow: '0 8px 32px rgba(0, 0, 0, 0.4)',
            }}
          >
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: isPortrait ? 12 : 14, fontWeight: 700, color: theme.accent }}>{parts[0].label}</div>
              <div style={{ fontSize: isPortrait ? 22 : 30, fontWeight: 900, color: theme.text }}>{parts[0].value}</div>
            </div>

            <div style={{ fontSize: isPortrait ? 24 : 32, fontWeight: 900, color: theme.muted }}>+</div>

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: isPortrait ? 12 : 14, fontWeight: 700, color: theme.positive }}>{parts[1].label}</div>
              <div style={{ fontSize: isPortrait ? 22 : 30, fontWeight: 900, color: theme.text }}>{parts[1].value}</div>
            </div>

            <div style={{ fontSize: isPortrait ? 24 : 32, fontWeight: 900, color: theme.muted }}>=</div>

            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: isPortrait ? 12 : 14, fontWeight: 700, color: theme.accent }}>{total.label}</div>
              <div style={{ fontSize: isPortrait ? 22 : 30, fontWeight: 900, color: theme.text }}>{total.value}</div>
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};

export const BreakdownGroupMaster: React.FC<{
  scenes: Array<{
    scene_id: string;
    props?: Record<string, any>;
    start_frame: number;
    end_frame: number;
    duration_frames: number;
  }>;
  theme?: Partial<Theme>;
  durationInFrames: number;
  breakdownData?: { total: BreakdownTotal; parts: BreakdownPart[] } | null;
}> = ({ scenes, theme, durationInFrames, breakdownData: passedBreakdownData }) => {
  const breakdownData = passedBreakdownData || resolveBreakdownData({ scenes, ...(scenes[0]?.props || {}) });
  if (!breakdownData) {
    return null;
  }

  const s0 = scenes[0]?.props || {};
  const breakdownProps: BreakdownProps = {
    headline: s0.headline || breakdownData.total.label,
    total: breakdownData.total,
    parts: breakdownData.parts,
    scenes,
    theme,
  };

  return <BreakdownTemplate {...breakdownProps} isGrouped={true} />;
};
