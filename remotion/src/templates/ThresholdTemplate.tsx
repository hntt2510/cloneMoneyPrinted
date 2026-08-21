import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { ThresholdProps } from '../types';

export const ThresholdTemplate: React.FC<ThresholdProps> = ({
  headline,
  current_value,
  current_display,
  threshold_value,
  threshold_display,
  threshold_label = 'Limit',
  theme: customTheme,
  isGrouped = false,
  animation_plan,
  eyebrow,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const curVal = Number(current_value) || 0;
  const thresVal = Number(threshold_value) || 0;
  const hasOverflow = curVal > thresVal;
  const statusColor = hasOverflow
    ? SEMANTIC_COLORS.threshold.danger
    : SEMANTIC_COLORS.threshold.safe;

  // Visual scaling:
  // If overflow exists, place the threshold marker at 50% (exact visual center of track)
  // so the safe baseline and overflow regions balance symmetrically.
  const thresholdPct = hasOverflow
    ? 50.0
    : Math.min(80, Math.max(25, (thresVal / (thresVal * 1.25)) * 100));

  const currentPct = hasOverflow
    ? Math.min(92, Math.max(10, (curVal / (thresVal * 2.0)) * 100))
    : Math.min(thresholdPct, Math.max(5, (curVal / (thresVal * 1.25)) * 100));

  // --- KINETIC BEAT TIMING (from animation_plan or calculated fallbacks) ---
  const limitBeat = animation_plan?.beats?.find(
    (b) => b.kind === 'threshold' || b.id.includes('limit')
  );
  const growBeat = animation_plan?.beats?.find(
    (b) => b.id.includes('grow') || b.kind === 'number'
  );
  const crossBeat = animation_plan?.beats?.find(
    (b) => b.id.includes('cross') || b.kind === 'highlight'
  );
  const resolveBeat = animation_plan?.beats?.find(
    (b) => b.id.includes('resolve') || b.kind === 'resolve'
  );

  const phase1_setupFrame = 0;
  const phase2_limitValFrame = limitBeat
    ? Math.max(0, limitBeat.start_frame + Math.round((limitBeat.end_frame - limitBeat.start_frame) * 0.35))
    : Math.round(durationInFrames * 0.12);
  const phase3_growStartFrame = growBeat
    ? growBeat.start_frame
    : Math.round(durationInFrames * 0.25);
  const phase3_growEndFrame = growBeat
    ? growBeat.end_frame
    : Math.round(durationInFrames * 0.70);
  const phase4_crossFrame = crossBeat
    ? crossBeat.start_frame
    : Math.round(durationInFrames * 0.72);
  const phase5_resolveFrame = resolveBeat
    ? resolveBeat.start_frame
    : Math.round(durationInFrames * 0.82);

  // --- SPRINGS & TRANSITIONS ---
  // Phase 1: Setup (frames 0+)
  const headerSpr = spring({
    frame: Math.max(0, frame - phase1_setupFrame),
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  const markerLineSpr = spring({
    frame: Math.max(0, frame - phase1_setupFrame - 4),
    fps,
    config: { damping: 14, stiffness: 100 },
  });

  // Phase 2: Limit Value Reveal (frames phase2_limitValFrame+)
  const limitValSpr = spring({
    frame: Math.max(0, frame - phase2_limitValFrame),
    fps,
    config: { damping: 14, stiffness: 110 },
  });

  // Phase 3: Bar Growth (smoothly spanning phase3_growStartFrame -> phase3_growEndFrame)
  const growProgress = interpolate(
    frame,
    [phase3_growStartFrame, phase3_growEndFrame],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );
  const smoothedGrow = spring({
    frame: Math.max(0, frame - phase3_growStartFrame),
    fps,
    config: { damping: 22, stiffness: 40 },
  });
  const effectiveGrow = interpolate(
    frame,
    [phase3_growStartFrame, phase3_growEndFrame],
    [0, 1],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );
  const animatedProgress = Math.min(1, Math.max(0, (growProgress * 0.7 + smoothedGrow * 0.3)));
  const animatedCurrentPct = (frame < phase3_growStartFrame)
    ? 0
    : Math.min(currentPct, animatedProgress * currentPct);

  const baseFillPct = Math.min(animatedCurrentPct, thresholdPct);
  const overflowFillPct = Math.max(0, animatedCurrentPct - thresholdPct);

  // Phase 4: Crossing Moment & Conclusion Headline Reveal (frames phase4_crossFrame+)
  const crossSpr = spring({
    frame: Math.max(0, frame - phase4_crossFrame),
    fps,
    config: { damping: 12, stiffness: 130 },
  });

  const isCrossed = hasOverflow && frame >= phase4_crossFrame && animatedCurrentPct >= thresholdPct - 0.5;

  // Phase 5: Consequence Resolution Badge (frames phase5_resolveFrame+)
  const resolveSpr = spring({
    frame: Math.max(0, frame - phase5_resolveFrame),
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  // --- PROGRESSIVE COPY REVEAL ---
  // Do NOT show conclusion headlines (e.g. "DAMAGE EXCEEDS LIMIT") before the crossing moment.
  // Pre-crossing: show the neutral subject (e.g. "PROPERTY DAMAGE LIABILITY" or "API REQUESTS").
  // Post-crossing: reveal the conclusion headline.
  const isConclusionHeadline = /\b(?:exceeds?|exceeded|over\s+limit|above\s+limit|beyond\s+limit)\b/i.test(headline);
  let neutralSubject = headline;
  if (isConclusionHeadline) {
    neutralSubject = headline
      .replace(/\b(?:damage\s+exceeds\s+limit|exceeds?\s+(?:policy\s+)?limit|exceeded)\b/gi, '')
      .trim();
    if (!neutralSubject || neutralSubject.length < 2) {
      neutralSubject = eyebrow
        ? eyebrow
        : (threshold_label
            ? (threshold_label.toUpperCase().endsWith('LIMIT') ? threshold_label.toUpperCase() : `${threshold_label.toUpperCase()} LIMIT`)
            : 'POLICY LIMIT');
    }
  }

  const showConclusion = hasOverflow && frame >= phase4_crossFrame;
  const activeHeadline = showConclusion ? headline : neutralSubject;

  const activeEyebrow = showConclusion
    ? 'LIMIT EXCEEDED'
    : (eyebrow && eyebrow !== neutralSubject ? eyebrow : threshold_label.toUpperCase());

  // Title Fitting
  const titleFit = fitText({
    text: activeHeadline,
    maxWidth: safe.titleZone.width * 0.9,
    maxHeight: safe.titleZone.height - 16,
    preferredFontSize: isPortrait ? 24 : 36,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  // --- GEOMETRY & SAFE CHART ZONE CENTERING ---
  const trackWidth = isPortrait
    ? Math.min(safe.chartZone.width * 0.90, 800)
    : Math.min(safe.chartZone.width * 0.75, 880);
  const trackHeight = isPortrait ? 26 : 32;

  // Visually center track within the safe chart zone (accounting for top/bottom labels)
  const trackLeft = safe.chartZone.x + (safe.chartZone.width - trackWidth) / 2;
  const trackTop = safe.chartZone.y + Math.round(safe.chartZone.height * 0.38);

  // --- SAFE ANNOTATION CLAMPING ---
  // Clamp marker top label inside track safe padding
  const markerPx = (thresholdPct / 100) * trackWidth;
  const clampedMarkerLabelX = Math.max(90, Math.min(trackWidth - 90, markerPx));
  const markerLabelShift = clampedMarkerLabelX - markerPx;

  // Clamp current value bottom label inside track safe padding
  const currentPx = (animatedCurrentPct / 100) * trackWidth;
  const clampedCurrentLabelX = Math.max(75, Math.min(trackWidth - 75, currentPx));
  const currentLabelShift = clampedCurrentLabelX - currentPx;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="radial_light" theme={theme} subtle_motion />

      {/* ZONE 1: TITLE ZONE (Progressive Copy Reveal) */}
      <div
        style={{
          position: 'absolute',
          left: safe.titleZone.x,
          top: safe.titleZone.y,
          width: safe.titleZone.width,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          opacity: headerSpr,
          transform: `translateY(${interpolate(headerSpr, [0, 1], [16, 0])}px)`,
          zIndex: 10,
        }}
      >
        {activeEyebrow && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              letterSpacing: '0.14em',
              color: showConclusion ? statusColor : theme.accent,
              textTransform: 'uppercase',
              marginBottom: 4,
              transition: 'color 0.2s ease',
            }}
          >
            {activeEyebrow}
          </div>
        )}
        <h1
          style={{
            margin: 0,
            fontSize: titleFit.fontSize,
            lineHeight: `${titleFit.lineHeight}px`,
            fontWeight: 800,
            color: theme.text,
            letterSpacing: '-0.02em',
            maxWidth: safe.titleZone.width * 0.9,
            wordBreak: 'break-word',
          }}
        >
          {titleFit.lines.map((ln, i) => (
            <div key={i}>{ln}</div>
          ))}
        </h1>
      </div>

      {/* ZONE 2: CENTERED CHART GEOMETRY & TRACK */}
      <div
        style={{
          position: 'absolute',
          left: trackLeft,
          top: trackTop,
          width: trackWidth,
          zIndex: 5,
        }}
      >
        {/* Track Bar */}
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: trackHeight,
            backgroundColor: theme.surfaceBorder,
            borderRadius: trackHeight / 2,
            overflow: 'visible',
          }}
        >
          {/* Base Safe Fill (up to threshold limit) */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              height: '100%',
              width: `${baseFillPct}%`,
              backgroundColor: theme.primary,
              borderRadius: `${trackHeight / 2}px ${hasOverflow && overflowFillPct > 0 ? '0 0' : `${trackHeight / 2}px ${trackHeight / 2}px`} ${trackHeight / 2}px`,
              boxShadow: `0 0 14px ${theme.primary}66`,
            }}
          />

          {/* Overflow Fill (past threshold limit) */}
          {hasOverflow && overflowFillPct > 0 && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: `${thresholdPct}%`,
                height: '100%',
                width: `${overflowFillPct}%`,
                backgroundColor: statusColor,
                borderRadius: '0 8px 8px 0',
                boxShadow: isCrossed
                  ? `0 0 24px ${statusColor}CC`
                  : `0 0 16px ${statusColor}88`,
              }}
            />
          )}

          {/* Limit Vertical Line Marker */}
          <div
            style={{
              position: 'absolute',
              top: -16,
              bottom: -16,
              left: `${thresholdPct}%`,
              width: 4,
              backgroundColor: '#ffffff',
              transform: 'translateX(-50%)',
              opacity: markerLineSpr,
              boxShadow: isCrossed
                ? `0 0 18px #ffffff, 0 0 24px ${statusColor}`
                : '0 0 12px rgba(255,255,255,0.8)',
              zIndex: 3,
            }}
          >
            {/* Phase B: Limit Label & Value Above Marker (Safe Clamped) */}
            <div
              style={{
                position: 'absolute',
                bottom: '100%',
                left: '50%',
                transform: `translateX(calc(-50% + ${markerLabelShift}px)) scale(${interpolate(limitValSpr, [0, 1], [0.85, 1])})`,
                marginBottom: 12,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                whiteSpace: 'nowrap',
                opacity: limitValSpr,
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 800,
                  color: theme.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                }}
              >
                {threshold_label}
              </span>
              <span
                style={{
                  fontSize: isPortrait ? 20 : 26,
                  fontWeight: 900,
                  color: theme.text,
                }}
              >
                {threshold_display || `$${thresVal.toLocaleString()}`}
              </span>
            </div>
          </div>

          {/* Phase C: Current Value Indicator Label (Follows Growth, Safe Clamped) */}
          {animatedCurrentPct > 4 && (
            <div
              style={{
                position: 'absolute',
                top: '100%',
                left: `${animatedCurrentPct}%`,
                transform: `translateX(calc(-50% + ${currentLabelShift}px))`,
                marginTop: 14,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                whiteSpace: 'nowrap',
                zIndex: 4,
                opacity: Math.min(1, animatedProgress * 1.5),
              }}
            >
              <span
                style={{
                  fontSize: isPortrait ? 20 : 28,
                  fontWeight: 900,
                  color: isCrossed ? statusColor : theme.positive,
                }}
              >
                {current_display || `$${curVal.toLocaleString()}`}
              </span>
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 800,
                  color: isCrossed ? statusColor : theme.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                }}
              >
                ACTUAL
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ZONE 3: PHASE E STATUS / CONSEQUENCE BADGE */}
      {hasOverflow && (
        <div
          style={{
            position: 'absolute',
            top: trackTop + trackHeight + 90,
            left: safe.chartZone.x,
            width: safe.chartZone.width,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            opacity: resolveSpr,
            transform: `scale(${interpolate(resolveSpr, [0, 1], [0.9, 1])})`,
            zIndex: 6,
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 10,
              padding: '10px 24px',
              borderRadius: 24,
              backgroundColor: `${statusColor}1A`,
              border: `1.5px solid ${statusColor}`,
              color: statusColor,
              fontSize: isPortrait ? 14 : 17,
              fontWeight: 900,
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              boxShadow: `0 0 20px ${statusColor}33`,
              maxWidth: trackWidth,
              textAlign: 'center',
            }}
          >
            ⚠️ EXCEEDS {threshold_label.toUpperCase()} BY ${(curVal - thresVal).toLocaleString()}
          </div>
        </div>
      )}
    </Layout>
  );
};
