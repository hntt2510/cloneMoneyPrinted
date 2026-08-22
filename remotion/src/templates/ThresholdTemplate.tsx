import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { ProgressiveText } from '../components/ProgressiveText';
import { fitText, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { GroupScene, Theme, ThresholdProps } from '../types';

interface ThresholdGraphicViewProps {
  theme: Theme;
  isPortrait: boolean;
  width: number;
  height: number;
  activeEyebrow: string | null;
  activeHeadline: string;
  neutralSubject: string;
  fullHeadline: string;
  showConclusion: boolean;
  phase1_setupFrame: number;
  phase2_limitValFrame: number;
  phase4_crossFrame: number;
  phase5_resolveFrame: number;
  headerSpr: number;
  markerLineSpr: number;
  limitValSpr: number;
  threshold_label: string;
  threshold_display: string;
  thresVal: number;
  thresholdPct: number;
  animatedCurrentPct: number;
  animatedProgress: number;
  current_display: string;
  curVal: number;
  isCrossed: boolean;
  hasOverflow: boolean;
  baseFillPct: number;
  overflowFillPct: number;
  statusColor: string;
  resolveSpr: number;
  excessDisplay: string;
}

const ThresholdGraphicView: React.FC<ThresholdGraphicViewProps> = ({
  theme,
  isPortrait,
  width,
  height,
  activeEyebrow,
  activeHeadline,
  neutralSubject,
  fullHeadline,
  showConclusion,
  phase1_setupFrame,
  phase2_limitValFrame,
  phase4_crossFrame,
  phase5_resolveFrame,
  headerSpr,
  markerLineSpr,
  limitValSpr,
  threshold_label,
  threshold_display,
  thresVal,
  thresholdPct,
  animatedCurrentPct,
  animatedProgress,
  current_display,
  curVal,
  isCrossed,
  hasOverflow,
  baseFillPct,
  overflowFillPct,
  statusColor,
  resolveSpr,
  excessDisplay,
}) => {
  // Title Fitting
  const titleMaxWidth = width * (isPortrait ? 0.88 : 0.70);
  const titleFit = fitText({
    text: activeHeadline,
    maxWidth: titleMaxWidth,
    maxHeight: 110,
    preferredFontSize: isPortrait ? 24 : 34,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  // Compact track dimensions (occupying 48% - 56% canvas width on desktop)
  const trackWidth = isPortrait
    ? Math.min(width * 0.86, 720)
    : Math.min(width * 0.52, 980);
  const trackHeight = isPortrait ? 28 : 34;

  const trackLeft = (width - trackWidth) / 2;
  const trackTop = Math.round(height * (isPortrait ? 0.44 : 0.47));

  // Marker label clamping
  const markerPx = (thresholdPct / 100) * trackWidth;
  const clampedMarkerX = Math.max(90, Math.min(trackWidth - 90, markerPx));
  const markerShift = clampedMarkerX - markerPx;

  // Current label clamping
  const currentPx = (animatedCurrentPct / 100) * trackWidth;
  const clampedCurrentX = Math.max(80, Math.min(trackWidth - 80, currentPx));
  const currentShift = clampedCurrentX - currentPx;

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      <Background variant="radial_light" theme={theme} subtle_motion />

      {/* ZONE 1: HEADLINE / PROGRESSIVE SUBJECT */}
      <div
        style={{
          position: 'absolute',
          left: (width - titleMaxWidth) / 2,
          top: Math.round(height * (isPortrait ? 0.18 : 0.22)),
          width: titleMaxWidth,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          opacity: headerSpr,
          transform: `translateY(${interpolate(headerSpr, [0, 1], [14, 0])}px)`,
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
              marginBottom: 6,
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
            maxWidth: titleMaxWidth,
            wordBreak: 'break-word',
            display: 'flex',
            justifyContent: 'center',
          }}
        >
          {showConclusion ? (
            <ProgressiveText
              text={fullHeadline}
              startFrame={phase4_crossFrame}
              endFrame={phase5_resolveFrame}
              fontSize={titleFit.fontSize}
              lineHeight={`${titleFit.lineHeight}px`}
              color={theme.text}
              fontWeight={800}
              maxWidth={titleMaxWidth}
            />
          ) : (
            <ProgressiveText
              text={neutralSubject}
              startFrame={phase1_setupFrame}
              endFrame={phase2_limitValFrame}
              fontSize={titleFit.fontSize}
              lineHeight={`${titleFit.lineHeight}px`}
              color={theme.text}
              fontWeight={800}
              maxWidth={titleMaxWidth}
            />
          )}
        </h1>
      </div>

      {/* ZONE 2: COMPACT CENTERED TRACK & VALUES */}
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
          {/* Base Safe Fill */}
          <div
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              height: '100%',
              width: `${baseFillPct}%`,
              backgroundColor: theme.primary,
              borderRadius: `${trackHeight / 2}px ${hasOverflow && overflowFillPct > 0 ? '0 0' : `${trackHeight / 2}px ${trackHeight / 2}px`} ${trackHeight / 2}px`,
              boxShadow: `0 0 16px ${theme.primary}66`,
            }}
          />

          {/* Overflow Fill */}
          {hasOverflow && overflowFillPct > 0 && (
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: `${thresholdPct}%`,
                height: '100%',
                width: `${overflowFillPct}%`,
                backgroundColor: statusColor,
                borderRadius: `0 ${trackHeight / 2}px ${trackHeight / 2}px 0`,
                boxShadow: isCrossed
                  ? `0 0 24px ${statusColor}CC`
                  : `0 0 16px ${statusColor}88`,
              }}
            />
          )}

          {/* Vertical Marker Line */}
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
              zIndex: 4,
            }}
          >
            {/* Limit Label & Value (Above Marker) */}
            <div
              style={{
                position: 'absolute',
                bottom: '100%',
                left: '50%',
                transform: `translateX(calc(-50% + ${markerShift}px)) scale(${interpolate(limitValSpr, [0, 1], [0.85, 1])})`,
                marginBottom: 14,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                whiteSpace: 'nowrap',
                opacity: limitValSpr,
              }}
            >
              <span
                style={{
                  fontSize: isPortrait ? 22 : 28,
                  fontWeight: 900,
                  color: theme.text,
                  lineHeight: 1.1,
                }}
              >
                {threshold_display || `$${thresVal.toLocaleString()}`}
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  color: theme.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.10em',
                  marginTop: 2,
                }}
              >
                {threshold_label}
              </span>
            </div>
          </div>

          {/* Current Value Indicator Label (Below Track) */}
          {animatedCurrentPct > 2 && (
            <div
              style={{
                position: 'absolute',
                top: '100%',
                left: `${animatedCurrentPct}%`,
                transform: `translateX(calc(-50% + ${currentShift}px))`,
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
                  fontSize: isPortrait ? 22 : 30,
                  fontWeight: 900,
                  color: isCrossed ? statusColor : theme.positive,
                  lineHeight: 1.1,
                }}
              >
                {current_display || `$${curVal.toLocaleString()}`}
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  color: isCrossed ? statusColor : theme.muted,
                  textTransform: 'uppercase',
                  letterSpacing: '0.10em',
                  marginTop: 2,
                }}
              >
                ACTUAL
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ZONE 3: COMPACT 2-LINE STATUS / CONSEQUENCE BLOCK */}
      {hasOverflow && (
        <div
          style={{
            position: 'absolute',
            top: trackTop + trackHeight + (isPortrait ? 82 : 98),
            left: 0,
            width: '100%',
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
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
              padding: isPortrait ? '8px 24px' : '10px 32px',
              borderRadius: 16,
              backgroundColor: `${statusColor}2A`,
              border: `1.5px solid ${statusColor}`,
              boxShadow: `0 0 24px ${statusColor}44`,
              textAlign: 'center',
            }}
          >
            <span
              style={{
                fontSize: isPortrait ? 11 : 13,
                fontWeight: 800,
                letterSpacing: '0.12em',
                color: statusColor,
                textTransform: 'uppercase',
              }}
            >
              OVER LIMIT
            </span>
            <span
              style={{
                fontSize: isPortrait ? 20 : 26,
                fontWeight: 900,
                letterSpacing: '0.02em',
                color: '#ffffff',
                textShadow: `0 0 12px ${statusColor}`,
              }}
            >
              {excessDisplay}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

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

  const curVal = Number(current_value) || 0;
  const thresVal = Number(threshold_value) || 0;
  const hasOverflow = curVal > thresVal;
  const statusColor = hasOverflow
    ? SEMANTIC_COLORS.threshold.danger
    : SEMANTIC_COLORS.threshold.safe;

  const thresholdPct = hasOverflow
    ? 50.0
    : Math.min(80, Math.max(25, (thresVal / (thresVal * 1.25)) * 100));

  const currentPct = hasOverflow
    ? Math.min(92, Math.max(10, (curVal / (thresVal * 2.0)) * 100))
    : Math.min(thresholdPct, Math.max(5, (curVal / (thresVal * 1.25)) * 100));

  // Kinetic beat timing
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

  // Springs
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

  const limitValSpr = spring({
    frame: Math.max(0, frame - phase2_limitValFrame),
    fps,
    config: { damping: 14, stiffness: 110 },
  });

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
  const animatedProgress = Math.min(1, Math.max(0, (growProgress * 0.7 + smoothedGrow * 0.3)));
  const animatedCurrentPct = (frame < phase3_growStartFrame)
    ? 0
    : Math.min(currentPct, animatedProgress * currentPct);

  const baseFillPct = Math.min(animatedCurrentPct, thresholdPct);
  const overflowFillPct = Math.max(0, animatedCurrentPct - thresholdPct);

  const isCrossed = hasOverflow && frame >= phase4_crossFrame && animatedCurrentPct >= thresholdPct - 0.5;

  const resolveSpr = spring({
    frame: Math.max(0, frame - phase5_resolveFrame),
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  // Progressive copy
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
            : 'LIMIT');
    }
  }

  const showConclusion = hasOverflow && frame >= phase4_crossFrame;
  const activeHeadline = showConclusion ? headline : neutralSubject;

  const activeEyebrow = showConclusion
    ? 'LIMIT EXCEEDED'
    : (eyebrow && eyebrow !== neutralSubject ? eyebrow : threshold_label.toUpperCase());

  // Consequence display
  const diffVal = Math.max(0, curVal - thresVal);
  const sampleDisplay = current_display || threshold_display || '';
  const hasDollarPrefix = sampleDisplay.trim().startsWith('$');
  const unitMatch = sampleDisplay.trim().match(/[a-zA-Z%]+$/);
  const unitSuffix = unitMatch ? ` ${unitMatch[0].toUpperCase()}` : '';
  const excessDisplay = hasDollarPrefix
    ? `+$${diffVal.toLocaleString()}`
    : `+${diffVal.toLocaleString()}${unitSuffix}`;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <ThresholdGraphicView
        theme={theme}
        isPortrait={isPortrait}
        width={width}
        height={height}
        activeEyebrow={activeEyebrow}
        activeHeadline={activeHeadline}
        neutralSubject={neutralSubject}
        fullHeadline={headline}
        showConclusion={showConclusion}
        phase1_setupFrame={phase1_setupFrame}
        phase2_limitValFrame={phase2_limitValFrame}
        phase4_crossFrame={phase4_crossFrame}
        phase5_resolveFrame={phase5_resolveFrame}
        headerSpr={headerSpr}
        markerLineSpr={markerLineSpr}
        limitValSpr={limitValSpr}
        threshold_label={threshold_label}
        threshold_display={threshold_display || `$${thresVal.toLocaleString()}`}
        thresVal={thresVal}
        thresholdPct={thresholdPct}
        animatedCurrentPct={animatedCurrentPct}
        animatedProgress={animatedProgress}
        current_display={current_display || `$${curVal.toLocaleString()}`}
        curVal={curVal}
        isCrossed={isCrossed}
        hasOverflow={hasOverflow}
        baseFillPct={baseFillPct}
        overflowFillPct={overflowFillPct}
        statusColor={statusColor}
        resolveSpr={resolveSpr}
        excessDisplay={excessDisplay}
      />
    </Layout>
  );
};

export interface ThresholdGroupMasterProps {
  scenes: GroupScene[];
  theme?: Partial<Theme>;
  durationInFrames: number;
}

export const ThresholdGroupMaster: React.FC<ThresholdGroupMasterProps> = ({
  scenes = [],
  theme: customTheme,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const s0 = scenes[0]?.props || {};
  const s1 = scenes[1]?.props || scenes[0]?.props || {};

  const curVal = Number(s1.current_value ?? s0.current_value) || 0;
  const thresVal = Number(s0.threshold_value ?? s1.threshold_value) || 0;
  const hasOverflow = curVal > thresVal;
  const statusColor = hasOverflow
    ? SEMANTIC_COLORS.threshold.danger
    : SEMANTIC_COLORS.threshold.safe;

  const threshold_label = s0.threshold_label || s1.threshold_label || 'Limit';
  const threshold_display = s0.threshold_display || s1.threshold_display || `$${thresVal.toLocaleString()}`;
  const current_display = s1.current_display || s0.current_display || `$${curVal.toLocaleString()}`;

  const thresholdPct = hasOverflow
    ? 50.0
    : Math.min(80, Math.max(25, (thresVal / (thresVal * 1.25)) * 100));

  const currentPct = hasOverflow
    ? Math.min(92, Math.max(10, (curVal / (thresVal * 2.0)) * 100))
    : Math.min(thresholdPct, Math.max(5, (curVal / (thresVal * 1.25)) * 100));

  // Multi-cue timing offsets
  const s0Dur = scenes[0]?.duration_frames || Math.round(durationInFrames / 2);
  const s1Dur = scenes[1]?.duration_frames || (durationInFrames - s0Dur);
  const s1Offset = s0Dur;

  const plan0 = scenes[0]?.animation_plan || scenes[0]?.props?.animation_plan;
  const plan1 = scenes[1]?.animation_plan || scenes[1]?.props?.animation_plan;

  const limitBeat = plan0?.beats?.find((b: any) => b.kind === 'threshold' || b.id.includes('limit'));
  const growBeat = plan1?.beats?.find((b: any) => b.id.includes('grow') || b.kind === 'number');
  const crossBeat = plan1?.beats?.find((b: any) => b.id.includes('cross') || b.kind === 'highlight');
  const resolveBeat = plan1?.beats?.find((b: any) => b.id.includes('resolve') || b.kind === 'resolve');

  const phase1_setupFrame = 0;
  const phase2_limitValFrame = limitBeat
    ? Math.max(0, limitBeat.start_frame + Math.round((limitBeat.end_frame - limitBeat.start_frame) * 0.35))
    : Math.round(s0Dur * 0.12);

  const phase3_growStartFrame = growBeat
    ? s1Offset + growBeat.start_frame
    : s1Offset + Math.round(s1Dur * 0.25);
  const phase3_growEndFrame = growBeat
    ? s1Offset + growBeat.end_frame
    : s1Offset + Math.round(s1Dur * 0.70);

  const phase4_crossFrame = crossBeat
    ? s1Offset + crossBeat.start_frame
    : phase3_growEndFrame + 3;
  const phase5_resolveFrame = resolveBeat
    ? s1Offset + resolveBeat.start_frame
    : s1Offset + Math.round(s1Dur * 0.82);

  // Springs (Continuous across the whole group timeline)
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

  const limitValSpr = spring({
    frame: Math.max(0, frame - phase2_limitValFrame),
    fps,
    config: { damping: 14, stiffness: 110 },
  });

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
  const animatedProgress = Math.min(1, Math.max(0, (growProgress * 0.7 + smoothedGrow * 0.3)));
  const animatedCurrentPct = (frame < phase3_growStartFrame)
    ? 0
    : Math.min(currentPct, animatedProgress * currentPct);

  const baseFillPct = Math.min(animatedCurrentPct, thresholdPct);
  const overflowFillPct = Math.max(0, animatedCurrentPct - thresholdPct);

  const isCrossed = hasOverflow && frame >= phase4_crossFrame && animatedCurrentPct >= thresholdPct - 0.5;

  const resolveSpr = spring({
    frame: Math.max(0, frame - phase5_resolveFrame),
    fps,
    config: { damping: 14, stiffness: 120 },
  });

  // Headlines
  const headline0 = s0.headline || s0.eyebrow || 'THRESHOLD';
  const headline1 = s1.headline || headline0;
  const isConclusionHeadline = /\b(?:exceeds?|exceeded|over\s+limit|above\s+limit|beyond\s+limit)\b/i.test(headline1);
  let neutralSubject = headline0;
  if (isConclusionHeadline) {
    neutralSubject = headline1
      .replace(/\b(?:damage\s+exceeds\s+limit|exceeds?\s+(?:policy\s+)?limit|exceeded)\b/gi, '')
      .trim();
    if (!neutralSubject || neutralSubject.length < 2) {
      neutralSubject = headline0 || 'LIMIT';
    }
  }

  const showConclusion = hasOverflow && frame >= phase4_crossFrame;
  const activeHeadline = showConclusion ? headline1 : neutralSubject;
  const activeEyebrow = showConclusion
    ? 'LIMIT EXCEEDED'
    : (s0.eyebrow && s0.eyebrow !== neutralSubject ? s0.eyebrow : threshold_label.toUpperCase());

  // Consequence display
  const diffVal = Math.max(0, curVal - thresVal);
  const sampleDisplay = current_display || threshold_display || '';
  const hasDollarPrefix = sampleDisplay.trim().startsWith('$');
  const unitMatch = sampleDisplay.trim().match(/[a-zA-Z%]+$/);
  const unitSuffix = unitMatch ? ` ${unitMatch[0].toUpperCase()}` : '';
  const excessDisplay = hasDollarPrefix
    ? `+$${diffVal.toLocaleString()}`
    : `+${diffVal.toLocaleString()}${unitSuffix}`;

  return (
    <ThresholdGraphicView
      theme={theme}
      isPortrait={isPortrait}
      width={width}
      height={height}
      activeEyebrow={activeEyebrow}
      activeHeadline={activeHeadline}
      neutralSubject={neutralSubject}
      fullHeadline={headline1}
      showConclusion={showConclusion}
      phase1_setupFrame={phase1_setupFrame}
      phase2_limitValFrame={phase2_limitValFrame}
      phase4_crossFrame={phase4_crossFrame}
      phase5_resolveFrame={phase5_resolveFrame}
      headerSpr={headerSpr}
      markerLineSpr={markerLineSpr}
      limitValSpr={limitValSpr}
      threshold_label={threshold_label}
      threshold_display={threshold_display}
      thresVal={thresVal}
      thresholdPct={thresholdPct}
      animatedCurrentPct={animatedCurrentPct}
      animatedProgress={animatedProgress}
      current_display={current_display}
      curVal={curVal}
      isCrossed={isCrossed}
      hasOverflow={hasOverflow}
      baseFillPct={baseFillPct}
      overflowFillPct={overflowFillPct}
      statusColor={statusColor}
      resolveSpr={resolveSpr}
      excessDisplay={excessDisplay}
    />
  );
};
