import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { getSafeArea, fitText, getItemFocusState, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { WaterfallProps } from '../types';

export const WaterfallTemplate: React.FC<WaterfallProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const safe = getSafeArea(width, height);

  const startVal = Number(props.start_value) || 100;
  const endVal = Number(props.end_value) || 110;
  const rawSteps = props.steps || [
    { label: 'State Filing Fee', delta: 30, display_value: '+$30' },
    { label: 'Safe Driver Discount', delta: -20, display_value: '-$20' },
  ];

  // 1. Compute Cumulative Running Levels and Geometry
  let currentRunning = startVal;
  const computedSteps = rawSteps.map((stp) => {
    const prev = currentRunning;
    const delta = Number(stp.delta) || 0;
    currentRunning += delta;
    return {
      ...stp,
      prevLevel: prev,
      delta,
      newLevel: currentRunning,
      isPositive: delta >= 0,
    };
  });

  const allLevels = [0, startVal, endVal, ...computedSteps.map((s) => s.prevLevel), ...computedSteps.map((s) => s.newLevel)];
  const maxLevel = Math.max(...allLevels, 10);
  const minLevel = Math.min(0, ...allLevels);
  const range = maxLevel - minLevel || 1;

  // 2. Total Columns: 1 (Start) + M (Steps) + 1 (Final Total)
  const totalCols = 2 + computedSteps.length;

  // Chart Canvas Dimensions strictly inside Safe Area Chart Zone
  const chartWidth = isPortrait ? safe.chartZone.width * 0.94 : Math.min(safe.chartZone.width * 0.88, 960);
  const chartHeight = isPortrait ? safe.chartZone.height * 0.62 : safe.chartZone.height * 0.68;
  const chartLeft = safe.chartZone.x + (safe.chartZone.width - chartWidth) / 2;
  const chartTop = safe.chartZone.y + Math.round(safe.chartZone.height * 0.05);

  const plotPaddingX = isPortrait ? 20 : 36;
  const plotPaddingBottom = isPortrait ? 48 : 58;
  const plotPaddingTop = isPortrait ? 32 : 40;
  const plotW = chartWidth - plotPaddingX * 2;
  const plotH = chartHeight - plotPaddingBottom - plotPaddingTop;

  const colWidth = Math.min(plotW / (totalCols * 1.35), isPortrait ? 60 : 100);
  const colGap = (plotW - totalCols * colWidth) / Math.max(1, totalCols - 1);

  // 3. Title Zone Layout
  const titleFit = fitText({
    text: props.headline,
    maxWidth: safe.titleZone.width * 0.9,
    maxHeight: safe.titleZone.height - 16,
    preferredFontSize: isPortrait ? 24 : 36,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Scale level value to Y pixel offset from bottom of plot area
  const levelToY = (level: number) => ((level - minLevel) / range) * plotH;

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />

      {/* ZONE 1: TITLE ZONE */}
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
        {props.eyebrow && (
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
            {props.eyebrow}
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

      {/* ZONE 2: WATERFALL CHART CONTAINER */}
      <div
        style={{
          position: 'absolute',
          left: chartLeft,
          top: chartTop,
          width: chartWidth,
          height: chartHeight,
          backgroundColor: theme.surface,
          border: `1.5px solid ${theme.surfaceBorder}`,
          borderRadius: 20,
          boxShadow: '0 12px 36px rgba(0,0,0,0.35)',
          overflow: 'visible',
          zIndex: 5,
        }}
      >
        {/* Baseline Line */}
        <div
          style={{
            position: 'absolute',
            left: plotPaddingX - 8,
            right: plotPaddingX - 8,
            bottom: plotPaddingBottom,
            height: 2,
            backgroundColor: theme.surfaceBorder,
          }}
        />

        {/* 1. START COLUMN (Index 0) */}
        {(() => {
          const focus = getItemFocusState(0, frame, durationInFrames, props.animation_plan, totalCols);
          const colSpr = spring({
            frame: Math.max(0, frame - 8),
            fps,
            config: { damping: 15, stiffness: 100 },
          });

          const colLeft = plotPaddingX;
          const barH = levelToY(startVal);
          const startColor = SEMANTIC_COLORS.waterfall.start;

          // Clamped value label bounds
          const valFit = fitText({
            text: `$${startVal.toLocaleString()}`,
            maxWidth: colWidth * 1.5,
            preferredFontSize: isPortrait ? 13 : 15,
            fontWeight: 900,
            role: 'hero_value',
          });

          const lblFit = fitText({
            text: props.start_label || 'Base Quote',
            maxWidth: Math.max(colWidth * 1.2, 100),
            preferredFontSize: isPortrait ? 11 : 13,
            fontWeight: 800,
            role: 'chart_label',
          });

          return (
            <div
              key="waterfall-start"
              style={{
                position: 'absolute',
                left: colLeft,
                bottom: plotPaddingBottom,
                width: colWidth,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: colSpr * focus.opacity,
                transform: `scale(${focus.scale})`,
                transition: 'opacity 0.2s ease',
              }}
            >
              {/* Value Label above column */}
              <div
                style={{
                  position: 'absolute',
                  bottom: barH * colSpr + 6,
                  fontSize: valFit.fontSize,
                  fontWeight: 900,
                  color: focus.isActive ? '#ffffff' : theme.text,
                  whiteSpace: 'nowrap',
                  textAlign: 'center',
                  textShadow: focus.isActive ? `0 0 10px ${startColor}` : 'none',
                }}
              >
                {valFit.lines[0]}
              </div>

              {/* Start Bar Block */}
              <div
                style={{
                  width: '100%',
                  height: Math.max(4, barH * colSpr),
                  backgroundColor: startColor,
                  borderRadius: '6px 6px 0 0',
                  boxShadow: focus.isActive
                    ? `0 0 18px ${startColor}99`
                    : `0 0 10px ${startColor}40`,
                }}
              />

              {/* Category Label below baseline */}
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  marginTop: 8,
                  fontSize: lblFit.fontSize,
                  fontWeight: 800,
                  color: focus.isActive ? theme.text : theme.muted,
                  textAlign: 'center',
                  width: Math.max(colWidth * 1.2, 100),
                  wordBreak: 'break-word',
                }}
              >
                {lblFit.lines.map((ln, i) => (
                  <div key={i}>{ln}</div>
                ))}
              </div>

              {/* Connecting line to Next Column */}
              <div
                style={{
                  position: 'absolute',
                  left: colWidth,
                  bottom: barH,
                  width: colGap,
                  height: 1.5,
                  backgroundColor: SEMANTIC_COLORS.waterfall.connector,
                  borderTop: '1.5px dashed rgba(255,255,255,0.3)',
                  opacity: colSpr,
                }}
              />
            </div>
          );
        })()}

        {/* 2. DELTA STEP COLUMNS */}
        {computedSteps.map((step, idx) => {
          const colIndex = idx + 1;
          const focus = getItemFocusState(colIndex, frame, durationInFrames, props.animation_plan, totalCols);

          const delay = 12 + idx * Math.max(8, Math.floor((durationInFrames * 0.45) / totalCols));
          const stepSpr = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 15, stiffness: 100 },
          });

          const colLeft = plotPaddingX + colIndex * (colWidth + colGap);
          const lowerVal = Math.min(step.prevLevel, step.newLevel);
          const bottomOffset = plotPaddingBottom + levelToY(lowerVal);
          const deltaH = (Math.abs(step.delta) / range) * plotH;
          const barColor = step.isPositive
            ? SEMANTIC_COLORS.waterfall.positive
            : SEMANTIC_COLORS.waterfall.negative;

          const valFit = fitText({
            text: step.display_value || `${step.isPositive ? '+' : ''}$${Math.abs(step.delta)}`,
            maxWidth: colWidth * 1.4,
            preferredFontSize: isPortrait ? 12 : 14,
            fontWeight: 900,
            role: 'hero_value',
          });

          const lblFit = fitText({
            text: step.label,
            maxWidth: Math.max(colWidth * 1.25, 90),
            preferredFontSize: isPortrait ? 10 : 12,
            fontWeight: 800,
            role: 'chart_label',
          });

          const isLastStep = idx === computedSteps.length - 1;
          const nextLevelY = levelToY(step.newLevel);

          return (
            <div
              key={`step-${idx}`}
              style={{
                position: 'absolute',
                left: colLeft,
                bottom: bottomOffset,
                width: colWidth,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: stepSpr * focus.opacity,
                transform: `scale(${focus.scale})`,
                transition: 'opacity 0.2s ease',
              }}
            >
              {/* Delta Value Label */}
              <div
                style={{
                  position: 'absolute',
                  bottom: deltaH + 4,
                  fontSize: valFit.fontSize,
                  fontWeight: 900,
                  color: barColor,
                  whiteSpace: 'nowrap',
                  textAlign: 'center',
                  textShadow: focus.isActive ? `0 0 10px ${barColor}` : 'none',
                }}
              >
                {valFit.lines[0]}
              </div>

              {/* Floating Delta Bar */}
              <div
                style={{
                  width: '100%',
                  height: Math.max(6, deltaH * stepSpr),
                  backgroundColor: barColor,
                  borderRadius: 6,
                  boxShadow: focus.isActive
                    ? `0 0 16px ${barColor}99`
                    : `0 0 8px ${barColor}40`,
                }}
              />

              {/* Step Label below baseline */}
              <div
                style={{
                  position: 'absolute',
                  top: plotH - levelToY(lowerVal) + 8,
                  fontSize: lblFit.fontSize,
                  fontWeight: 800,
                  color: focus.isActive ? theme.text : theme.muted,
                  textAlign: 'center',
                  width: Math.max(colWidth * 1.25, 90),
                  wordBreak: 'break-word',
                }}
              >
                {lblFit.lines.map((ln, i) => (
                  <div key={i}>{ln}</div>
                ))}
              </div>

              {/* Connector line to next column */}
              <div
                style={{
                  position: 'absolute',
                  left: colWidth,
                  bottom: step.isPositive ? deltaH : 0,
                  width: colGap,
                  height: 1.5,
                  backgroundColor: SEMANTIC_COLORS.waterfall.connector,
                  borderTop: '1.5px dashed rgba(255,255,255,0.3)',
                  opacity: stepSpr,
                }}
              />
            </div>
          );
        })}

        {/* 3. FINAL TOTAL COLUMN (Index totalCols - 1) */}
        {(() => {
          const finalIndex = totalCols - 1;
          const focus = getItemFocusState(finalIndex, frame, durationInFrames, props.animation_plan, totalCols);

          const finalSpr = spring({
            frame: Math.max(0, frame - Math.round(durationInFrames * 0.62)),
            fps,
            config: { damping: 14, stiffness: 120 },
          });

          const finalLeft = plotPaddingX + finalIndex * (colWidth + colGap);
          const barH = levelToY(endVal);
          const finalColor = SEMANTIC_COLORS.waterfall.final;

          // Safe bounded value fit
          const valFit = fitText({
            text: `$${endVal.toLocaleString()}`,
            maxWidth: colWidth * 1.4,
            preferredFontSize: isPortrait ? 13 : 15,
            fontWeight: 900,
            role: 'hero_value',
          });

          // Final label bounds strictly clamped within plot right edge
          const lblFit = fitText({
            text: props.end_label || 'Final Premium',
            maxWidth: Math.max(colWidth * 1.2, 100),
            preferredFontSize: isPortrait ? 11 : 13,
            fontWeight: 800,
            role: 'chart_label',
          });

          return (
            <div
              key="waterfall-final"
              style={{
                position: 'absolute',
                left: finalLeft,
                bottom: plotPaddingBottom,
                width: colWidth,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                opacity: finalSpr * focus.opacity,
                transform: `scale(${focus.scale})`,
                transition: 'opacity 0.2s ease',
              }}
            >
              {/* Final Value Label ($110) */}
              <div
                style={{
                  position: 'absolute',
                  bottom: barH * finalSpr + 6,
                  fontSize: valFit.fontSize,
                  fontWeight: 900,
                  color: focus.isActive ? '#ffffff' : theme.accent,
                  whiteSpace: 'nowrap',
                  textAlign: 'center',
                  textShadow: focus.isActive ? `0 0 12px ${finalColor}` : 'none',
                }}
              >
                {valFit.lines[0]}
              </div>

              {/* Final Total Bar */}
              <div
                style={{
                  width: '100%',
                  height: Math.max(4, barH * finalSpr),
                  backgroundColor: finalColor,
                  borderRadius: '6px 6px 0 0',
                  boxShadow: focus.isActive
                    ? `0 0 20px ${finalColor}`
                    : `0 0 12px ${finalColor}66`,
                }}
              />

              {/* Final Category Label ("Final Premium") */}
              <div
                style={{
                  position: 'absolute',
                  top: '100%',
                  marginTop: 8,
                  fontSize: lblFit.fontSize,
                  fontWeight: 900,
                  color: focus.isActive ? theme.text : theme.text,
                  textAlign: 'center',
                  width: Math.max(colWidth * 1.2, 100),
                  wordBreak: 'break-word',
                }}
              >
                {lblFit.lines.map((ln, i) => (
                  <div key={i}>{ln}</div>
                ))}
              </div>
            </div>
          );
        })()}
      </div>
    </Layout>
  );
};
