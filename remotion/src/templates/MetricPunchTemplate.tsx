import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { CameraPush, UnderlineDraw } from '../components/EditorialPrimitives';
import { Layout } from '../components/Layout';
import { ProgressiveText } from '../components/ProgressiveText';
import { fitText, getSafeArea } from '../layout';
import { resolveTheme } from '../theme/theme';
import { NumberProps } from '../types';

export const MetricPunchTemplate: React.FC<NumberProps> = ({
  headline,
  value,
  numeric_value,
  prefix = '',
  suffix = '',
  label,
  subtext,
  eyebrow,
  context_label,
  delta_direction,
  delta_sentiment,
  delta_value,
  delta_display,
  before_value,
  after_value,
  theme: customTheme,
  isGrouped = false,
  animation_plan,
  renderer_decision,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const technique = renderer_decision?.storytelling_technique || 'metric_punch';
  const bgTreatment = renderer_decision?.background_treatment || 'radial_light';

  const deltaDir = delta_direction || (delta_display?.startsWith('+') ? 'positive' : delta_display?.startsWith('-') ? 'negative' : 'neutral');
  const deltaArrow = deltaDir === 'positive' ? '↑' : deltaDir === 'negative' ? '↓' : '';
  const deltaText = delta_display || delta_value || (deltaDir === 'positive' ? 'INCREASE' : deltaDir === 'negative' ? 'DECREASE' : 'DELTA');

  // Separate mathematical arrow direction from semantic color sentiment
  const deltaColor = delta_sentiment === 'negative'
    ? '#F87171'
    : delta_sentiment === 'positive'
    ? '#34D399'
    : theme.accent;

  // Kinetic beat timing
  const numberBeat = animation_plan?.beats?.find((b) => b.kind === 'number' || b.id.includes('num') || b.id.includes('val'));
  const phraseBeat = animation_plan?.beats?.find((b) => b.kind === 'phrase' || b.id.includes('phrase') || b.id.includes('takeaway'));

  const punchStartFrame = numberBeat ? numberBeat.start_frame : Math.round(durationInFrames * 0.15);
  const punchEndFrame = numberBeat ? numberBeat.end_frame : Math.round(durationInFrames * 0.55);
  const holdStartFrame = phraseBeat ? phraseBeat.start_frame : punchEndFrame + 10;

  // Springs
  const enterSpr = spring({
    frame: Math.max(0, frame - 2),
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  const punchSpr = spring({
    frame: Math.max(0, frame - punchStartFrame),
    fps,
    config: { damping: 14, stiffness: 140 },
  });

  const underlineProgress = interpolate(
    frame,
    [punchStartFrame, punchEndFrame],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  // Numeric count-up if numeric_value is available
  const parsedNum = numeric_value !== undefined && numeric_value !== null ? Number(numeric_value) : null;
  const countProgress = interpolate(
    frame,
    [punchStartFrame, punchEndFrame],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );
  const countEased = spring({
    frame: countProgress * fps,
    fps,
    config: { damping: 18, stiffness: 90 },
  });

  const animatedValueStr = (() => {
    if (frame < punchStartFrame) {
      return '';
    }
    if (parsedNum === null || isNaN(parsedNum)) {
      return value;
    }
    const currentNum = Math.round(countEased * parsedNum);
    const pfx = prefix || (value.startsWith('$') ? '$' : '');
    const sfx = suffix || (value.endsWith('%') ? '%' : '');
    return `${pfx}${currentNum.toLocaleString()}${sfx}`;
  })();

  const titleFit = fitText({
    text: headline,
    maxWidth: width * (isPortrait ? 0.88 : 0.72),
    maxHeight: 120,
    preferredFontSize: isPortrait ? 26 : 38,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  const metricFontSize = isPortrait ? 56 : 88;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant={bgTreatment} theme={theme} subtle_motion />

      <CameraPush scaleTo={1.035} maxPanY={5}>
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            textAlign: 'center',
            padding: '0 40px',
            boxSizing: 'border-box',
          }}
        >
          {/* Eyebrow / Subject Category */}
          {(eyebrow || context_label) && (
            <div
              style={{
                fontSize: isPortrait ? 12 : 15,
                fontWeight: 800,
                letterSpacing: '0.14em',
                color: theme.accent,
                textTransform: 'uppercase',
                marginBottom: 10,
                opacity: enterSpr,
                transform: `translateY(${interpolate(enterSpr, [0, 1], [10, 0])}px)`,
              }}
            >
              {eyebrow || context_label}
            </div>
          )}

          {/* Progressive Headline */}
          <div
            style={{
              maxWidth: width * (isPortrait ? 0.88 : 0.72),
              marginBottom: isPortrait ? 20 : 28,
              opacity: enterSpr,
              transform: `translateY(${interpolate(enterSpr, [0, 1], [12, 0])}px)`,
            }}
          >
            <ProgressiveText
              text={headline}
              startFrame={0}
              endFrame={punchStartFrame}
              fontSize={titleFit.fontSize}
              lineHeight={`${titleFit.lineHeight}px`}
              color={theme.text}
              fontWeight={800}
              maxWidth={width * (isPortrait ? 0.88 : 0.72)}
            />
          </div>

          {/* TECHNIQUE BRANCHING */}
          {technique === 'metric_context' ? (
            /* Context Card Mode */
            <div
              style={{
                maxWidth: width * (isPortrait ? 0.90 : 0.65),
                padding: isPortrait ? '24px 20px' : '36px 48px',
                borderRadius: 24,
                backgroundColor: `${theme.surface}E6`,
                border: `1.5px solid ${theme.surfaceBorder}`,
                boxShadow: `0 16px 48px rgba(0,0,0,0.4), 0 0 24px ${theme.primary}18`,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                textAlign: 'center',
                opacity: punchSpr,
                transform: `scale(${interpolate(punchSpr, [0, 1], [0.92, 1])})`,
              }}
            >
              <div
                style={{
                  fontSize: metricFontSize * 0.9,
                  fontWeight: 900,
                  lineHeight: 1.05,
                  letterSpacing: '-0.03em',
                  color: theme.primary,
                  textShadow: `0 0 24px ${theme.primary}44`,
                }}
              >
                {animatedValueStr}
              </div>

              {label && (
                <div
                  style={{
                    display: 'inline-block',
                    fontSize: isPortrait ? 12 : 14,
                    fontWeight: 800,
                    color: theme.accent,
                    backgroundColor: `${theme.accent}18`,
                    border: `1px solid ${theme.accent}44`,
                    padding: '4px 14px',
                    borderRadius: 20,
                    textTransform: 'uppercase',
                    letterSpacing: '0.10em',
                    marginTop: 12,
                  }}
                >
                  {label}
                </div>
              )}

              {subtext && (
                <div
                  style={{
                    marginTop: 16,
                    fontSize: isPortrait ? 14 : 16,
                    fontWeight: 600,
                    color: theme.muted,
                    lineHeight: 1.45,
                    maxWidth: 540,
                    opacity: interpolate(frame, [holdStartFrame, holdStartFrame + 12], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    }),
                  }}
                >
                  {subtext}
                </div>
              )}
            </div>
          ) : technique === 'metric_delta' ? (
            /* Delta Change Indicator Mode */
            <div
              style={{
                display: 'inline-flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: punchSpr,
                transform: `scale(${interpolate(punchSpr, [0, 1], [0.90, 1])})`,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                <div
                  style={{
                    fontSize: metricFontSize,
                    fontWeight: 900,
                    lineHeight: 1.05,
                    letterSpacing: '-0.03em',
                    color: theme.primary,
                    textShadow: `0 0 28px ${theme.primary}55`,
                  }}
                >
                  {animatedValueStr}
                </div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '6px 16px',
                    borderRadius: 24,
                    backgroundColor: `${deltaColor}22`,
                    border: `1.5px solid ${deltaColor}`,
                    color: deltaColor,
                    fontSize: isPortrait ? 14 : 18,
                    fontWeight: 900,
                    letterSpacing: '0.04em',
                    boxShadow: `0 0 16px ${deltaColor}33`,
                  }}
                >
                  {deltaArrow && <span style={{ fontSize: isPortrait ? 16 : 20, lineHeight: 1 }}>{deltaArrow}</span>}
                  <span>{deltaText}</span>
                </div>
              </div>

              {/* Kinetic Underline */}
              <div style={{ width: '85%', maxWidth: 380, marginTop: 8 }}>
                <UnderlineDraw progress={underlineProgress} color={theme.accent} height={4} />
              </div>

              {label && (
                <div
                  style={{
                    fontSize: isPortrait ? 13 : 16,
                    fontWeight: 800,
                    color: theme.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.10em',
                    marginTop: 14,
                  }}
                >
                  {label}
                </div>
              )}

              {subtext && (
                <div
                  style={{
                    maxWidth: 680,
                    marginTop: 18,
                    fontSize: isPortrait ? 14 : 18,
                    fontWeight: 600,
                    color: theme.muted,
                    lineHeight: 1.4,
                    opacity: interpolate(frame, [holdStartFrame, holdStartFrame + 15], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    }),
                  }}
                >
                  {subtext}
                </div>
              )}
            </div>
          ) : (
            /* Default Metric Punch Mode */
            <div
              style={{
                display: 'inline-flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: punchSpr,
                transform: `scale(${interpolate(punchSpr, [0, 1], [0.88, 1])})`,
              }}
            >
              <div
                style={{
                  fontSize: metricFontSize,
                  fontWeight: 900,
                  lineHeight: 1.05,
                  letterSpacing: '-0.03em',
                  color: theme.primary,
                  textShadow: `0 0 28px ${theme.primary}55`,
                }}
              >
                {animatedValueStr}
              </div>

              {/* Kinetic Underline */}
              <div style={{ width: '85%', maxWidth: 360 }}>
                <UnderlineDraw progress={underlineProgress} color={theme.accent} height={4} />
              </div>

              {/* Micro Label / Context */}
              {label && (
                <div
                  style={{
                    fontSize: isPortrait ? 13 : 16,
                    fontWeight: 800,
                    color: theme.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.10em',
                    marginTop: 14,
                  }}
                >
                  {label}
                </div>
              )}

              {/* Supporting Subtext */}
              {subtext && (
                <div
                  style={{
                    maxWidth: 680,
                    marginTop: 20,
                    fontSize: isPortrait ? 14 : 18,
                    fontWeight: 600,
                    color: theme.muted,
                    lineHeight: 1.4,
                    opacity: interpolate(frame, [holdStartFrame, holdStartFrame + 15], [0, 1], {
                      extrapolateLeft: 'clamp',
                      extrapolateRight: 'clamp',
                    }),
                  }}
                >
                  {subtext}
                </div>
              )}
            </div>
          )}
        </div>
      </CameraPush>
    </Layout>
  );
};
