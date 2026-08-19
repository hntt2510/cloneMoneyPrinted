import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, getItemFocusState } from '../layout';
import { resolveTheme } from '../theme/theme';
import { TimelineProps } from '../types';

export const TimelineTemplate: React.FC<TimelineProps> = ({
  headline,
  milestones = [],
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
  const items = milestones.length > 0 ? milestones : [
    { time_label: 'DAY 1', title: 'Incident Filed' },
    { time_label: 'DAY 3', title: 'Adjuster Assessment' },
    { time_label: 'DAY 7', title: 'Payment Disbursed' },
  ];

  // 1. Title Zone Layout (Guaranteed non-overlapping with track)
  const titleFit = fitText({
    text: headline,
    maxWidth: safe.titleZone.width * 0.9,
    maxHeight: safe.titleZone.height - 20,
    preferredFontSize: isPortrait ? 26 : 38,
    minimumFontSize: isPortrait ? 18 : 24,
    maxLines: 2,
    role: 'headline',
  });

  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // 2. Track & Slot Geometry
  const trackW = isPortrait ? 6 : Math.min(safe.chartZone.width * 0.92, 1080);
  const trackH = isPortrait ? Math.min(safe.chartZone.height * 0.82, 800) : 6;
  const trackLeft = isPortrait ? safe.chartZone.x + Math.round(safe.chartZone.width * 0.18) : safe.chartZone.x + (safe.chartZone.width - trackW) / 2;
  const trackTop = isPortrait ? safe.chartZone.y + Math.round(safe.chartZone.height * 0.08) : safe.chartZone.y + Math.round(safe.chartZone.height * 0.42);

  // Track entrance animation
  const trackSpr = spring({
    frame: Math.max(0, frame - 4),
    fps,
    config: { damping: 18, stiffness: 90 },
  });

  const numItems = items.length;
  const slotSize = isPortrait ? trackH / Math.max(1, numItems - 1) : trackW / numItems;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />

      {/* ZONE 1: TOP TITLE ZONE */}
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
        {eyebrow && (
          <div
            style={{
              fontSize: isPortrait ? 12 : 14,
              fontWeight: 800,
              letterSpacing: '0.14em',
              color: theme.accent,
              textTransform: 'uppercase',
              marginBottom: 4,
            }}
          >
            {eyebrow}
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

      {/* ZONE 2 & 3: TRACK AND MILESTONE SLOTS */}
      <div
        style={{
          position: 'absolute',
          left: trackLeft,
          top: trackTop,
          width: trackW,
          height: trackH,
          zIndex: 5,
        }}
      >
        {/* Track Line Background */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: isPortrait ? 6 : '100%',
            height: isPortrait ? '100%' : 6,
            backgroundColor: theme.surfaceBorder,
            borderRadius: 3,
          }}
        />

        {/* Track Progress Fill */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: isPortrait ? 6 : `${trackSpr * 100}%`,
            height: isPortrait ? `${trackSpr * 100}%` : 6,
            backgroundColor: theme.primary,
            borderRadius: 3,
            boxShadow: `0 0 12px ${theme.primary}80`,
          }}
        />

        {/* Milestones with Slot Containment */}
        {items.map((m, idx) => {
          const focus = getItemFocusState(idx, frame, durationInFrames, animation_plan, numItems);

          // Node center position along track
          const posPct = numItems > 1 ? idx / (numItems - 1) : 0.5;
          const nodeX = isPortrait ? 3 : posPct * trackW;
          const nodeY = isPortrait ? posPct * trackH : 3;

          // Milestone reveal spring
          const revealDelay = 10 + idx * Math.max(8, Math.floor((durationInFrames * 0.45) / numItems));
          const nodeSpr = spring({
            frame: Math.max(0, frame - revealDelay),
            fps,
            config: { damping: 14, stiffness: 120 },
          });

          // Text fitting for milestone title and time label
          const maxLabelWidth = isPortrait
            ? safe.chartZone.width * 0.65
            : Math.max(160, Math.floor(trackW / numItems) - 16);

          const timeFit = fitText({
            text: m.time_label || `STEP ${idx + 1}`,
            maxWidth: maxLabelWidth,
            preferredFontSize: isPortrait ? 13 : 15,
            fontWeight: 800,
            role: 'milestone_time',
          });

          const titleFitRes = fitText({
            text: m.title || '',
            maxWidth: maxLabelWidth,
            maxHeight: 52,
            preferredFontSize: isPortrait ? 16 : 20,
            minimumFontSize: 13,
            maxLines: 2,
            fontWeight: 800,
            role: 'milestone_title',
          });

          return (
            <div
              key={`milestone-${idx}`}
              style={{
                position: 'absolute',
                left: nodeX,
                top: nodeY,
                opacity: nodeSpr,
                transform: `scale(${interpolate(nodeSpr, [0, 1], [0.6, 1]) * focus.scale})`,
              }}
            >
              {/* Milestone Node Dot */}
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  width: focus.isActive ? 28 : 22,
                  height: focus.isActive ? 28 : 22,
                  transform: 'translate(-50%, -50%)',
                  backgroundColor: focus.isActive ? theme.accent : theme.surface,
                  border: `3px solid ${focus.isActive ? theme.text : theme.primary}`,
                  borderRadius: '50%',
                  boxShadow: focus.isActive
                    ? `0 0 18px ${theme.accent}, 0 0 8px #ffffff`
                    : `0 0 8px ${theme.primary}66`,
                  transition: 'all 0.2s ease',
                  zIndex: 2,
                }}
              />

              {/* Milestone Slot Bounded Label Card */}
              <div
                style={{
                  position: 'absolute',
                  left: isPortrait ? 32 : -maxLabelWidth / 2,
                  top: isPortrait
                    ? -titleFitRes.height / 2 - 8
                    : 28,
                  width: maxLabelWidth,
                  textAlign: isPortrait ? 'left' : 'center',
                  backgroundColor: focus.isActive ? theme.surface : 'transparent',
                  padding: focus.isActive ? '8px 12px' : '4px 6px',
                  borderRadius: 10,
                  border: `1px solid ${focus.isActive ? theme.surfaceBorder : 'transparent'}`,
                  boxShadow: focus.isActive ? '0 4px 16px rgba(0,0,0,0.3)' : 'none',
                  boxSizing: 'border-box',
                  opacity: focus.opacity,
                  transition: 'opacity 0.2s ease',
                }}
              >
                {/* Time Label (e.g. DAY 1, DAY 3, DAY 7) */}
                <div
                  style={{
                    fontSize: timeFit.fontSize,
                    fontWeight: 900,
                    color: focus.isActive ? theme.accent : theme.muted,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    marginBottom: 3,
                  }}
                >
                  {timeFit.lines.join(' ')}
                </div>

                {/* Milestone Title (e.g. Incident Filed, Adjuster Assessment) */}
                <div
                  style={{
                    fontSize: titleFitRes.fontSize,
                    lineHeight: `${titleFitRes.lineHeight}px`,
                    fontWeight: focus.isActive ? 900 : 700,
                    color: focus.isActive ? '#ffffff' : theme.text,
                    letterSpacing: '-0.01em',
                    wordBreak: 'break-word',
                  }}
                >
                  {titleFitRes.lines.map((ln, lineIdx) => (
                    <div key={lineIdx}>{ln}</div>
                  ))}
                </div>

                {/* Optional Description */}
                {m.description && (
                  <div
                    style={{
                      fontSize: Math.max(11, titleFitRes.fontSize * 0.75),
                      color: theme.muted,
                      marginTop: 4,
                      lineHeight: 1.25,
                    }}
                  >
                    {m.description}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Layout>
  );
};
