import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { WaterfallProps } from '../types';

export const WaterfallTemplate: React.FC<WaterfallProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  const startVal = Number(props.start_value) || 100;
  const endVal = Number(props.end_value) || 100;
  const rawSteps = props.steps || [];

  // Compute running totals for positioning floating delta blocks
  let running = startVal;
  const computedSteps = rawSteps.map((stp) => {
    const prev = running;
    const delta = Number(stp.delta) || 0;
    running += delta;
    return {
      ...stp,
      prevLevel: prev,
      delta,
      newLevel: running,
      isPositive: delta >= 0,
    };
  });

  // Calculate global min and max for chart scale
  const allLevels = [0, startVal, endVal, ...computedSteps.map((s) => s.prevLevel), ...computedSteps.map((s) => s.newLevel)];
  const maxLevel = Math.max(...allLevels, 10);
  const minLevel = Math.min(0, ...allLevels);
  const range = maxLevel - minLevel || 1;

  // Chart dimensions
  const chartWidth = isPortrait ? width * 0.88 : Math.min(width * 0.75, 880);
  const chartHeight = isPortrait ? height * 0.45 : height * 0.48;

  // Column counts: 1 (start) + steps + 1 (final)
  const totalCols = 2 + computedSteps.length;
  const colWidth = Math.min(chartWidth / (totalCols * 1.35), isPortrait ? 56 : 90);
  const colGap = (chartWidth - totalCols * colWidth) / Math.max(1, totalCols - 1);

  // Entrance spring
  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Start bar spring
  const startSpr = spring({
    frame: Math.max(0, frame - 6),
    fps,
    config: { damping: 15, stiffness: 100 },
  });

  // Step springs
  const stepDelayBase = 12;
  const stepDelayStep = Math.max(4, Math.floor((durationInFrames * 0.45) / Math.max(1, computedSteps.length)));

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: isPortrait ? '36px 20px' : '44px 56px',
          boxSizing: 'border-box',
          position: 'relative',
        }}
      >
        {/* Header Section */}
        <div
          style={{
            textAlign: 'center',
            marginBottom: isPortrait ? 20 : 28,
            opacity: headerSpr,
            transform: `translateY(${interpolate(headerSpr, [0, 1], [16, 0])}px)`,
          }}
        >
          {props.eyebrow && (
            <div
              style={{
                fontSize: isPortrait ? 13 : 15,
                fontWeight: 800,
                letterSpacing: '0.15em',
                color: theme.accent,
                textTransform: 'uppercase',
                marginBottom: 6,
              }}
            >
              {props.eyebrow}
            </div>
          )}
          <div
            style={{
              fontSize: isPortrait ? 22 : 32,
              fontWeight: 900,
              color: theme.text,
              letterSpacing: '-0.02em',
              maxWidth: 780,
              lineHeight: 1.25,
            }}
          >
            {props.headline}
          </div>
        </div>

        {/* Waterfall Chart Canvas */}
        <div
          style={{
            width: chartWidth,
            height: chartHeight,
            position: 'relative',
            display: 'flex',
            alignItems: 'flex-end',
            backgroundColor: theme.surface,
            border: `1.5px solid ${theme.surfaceBorder}`,
            borderRadius: 20,
            padding: isPortrait ? '24px 16px 44px 16px' : '32px 32px 52px 32px',
            boxSizing: 'border-box',
            boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
          }}
        >
          {/* Baseline guide line */}
          <div
            style={{
              position: 'absolute',
              left: 24,
              right: 24,
              bottom: isPortrait ? 44 : 52,
              height: 1.5,
              backgroundColor: theme.surfaceBorder,
            }}
          />

          {/* 1. Starting Column */}
          {(() => {
            const barH = ((startVal - minLevel) / range) * (chartHeight - 80);
            return (
              <div
                style={{
                  position: 'absolute',
                  left: 24,
                  bottom: isPortrait ? 44 : 52,
                  width: colWidth,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                }}
              >
                {/* Value label */}
                <div
                  style={{
                    fontSize: isPortrait ? 12 : 14,
                    fontWeight: 900,
                    color: theme.accent,
                    marginBottom: 6,
                    opacity: startSpr,
                  }}
                >
                  ${startVal.toLocaleString()}
                </div>
                {/* Bar Block */}
                <div
                  style={{
                    width: '100%',
                    height: Math.max(4, barH * startSpr),
                    backgroundColor: theme.accent,
                    borderRadius: '8px 8px 0 0',
                    boxShadow: `0 0 16px ${theme.accent}66`,
                  }}
                />
                {/* Category label */}
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    marginTop: 8,
                    fontSize: isPortrait ? 10 : 12,
                    fontWeight: 800,
                    color: theme.muted,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {props.start_label || 'Start'}
                </div>
              </div>
            );
          })()}

          {/* 2. Floating Delta Steps */}
          {computedSteps.map((step, idx) => {
            const stepSpr = spring({
              frame: Math.max(0, frame - (stepDelayBase + idx * stepDelayStep)),
              fps,
              config: { damping: 15, stiffness: 100 },
            });

            const colLeft = 24 + (idx + 1) * (colWidth + colGap);
            const lowerVal = Math.min(step.prevLevel, step.newLevel);
            const deltaH = (Math.abs(step.delta) / range) * (chartHeight - 80);
            const bottomOffset = (isPortrait ? 44 : 52) + ((lowerVal - minLevel) / range) * (chartHeight - 80);
            const barColor = step.isPositive ? theme.positive : theme.negative;

            return (
              <div
                key={idx}
                style={{
                  position: 'absolute',
                  left: colLeft,
                  bottom: bottomOffset,
                  width: colWidth,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  opacity: stepSpr,
                  transform: `scaleY(${stepSpr})`,
                  transformOrigin: step.isPositive ? 'bottom' : 'top',
                }}
              >
                {/* Delta Value Label */}
                <div
                  style={{
                    fontSize: isPortrait ? 11 : 13,
                    fontWeight: 900,
                    color: barColor,
                    marginBottom: 4,
                  }}
                >
                  {step.display_value || `${step.isPositive ? '+' : ''}${step.delta}`}
                </div>
                {/* Floating Bar Block */}
                <div
                  style={{
                    width: '100%',
                    height: Math.max(6, deltaH),
                    backgroundColor: barColor,
                    borderRadius: 6,
                    boxShadow: `0 0 12px ${barColor}66`,
                  }}
                />
                {/* Step Label */}
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    marginTop: 8,
                    fontSize: isPortrait ? 10 : 12,
                    fontWeight: 800,
                    color: theme.muted,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                    maxWidth: colWidth * 1.4,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {step.label}
                </div>
              </div>
            );
          })}

          {/* 3. Final Total Column */}
          {(() => {
            const finalSpr = spring({
              frame: Math.max(0, frame - Math.round(durationInFrames * 0.65)),
              fps,
              config: { damping: 14, stiffness: 120 },
            });
            const finalLeft = 24 + (totalCols - 1) * (colWidth + colGap);
            const barH = ((endVal - minLevel) / range) * (chartHeight - 80);

            return (
              <div
                style={{
                  position: 'absolute',
                  left: finalLeft,
                  bottom: isPortrait ? 44 : 52,
                  width: colWidth,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  opacity: finalSpr,
                }}
              >
                <div
                  style={{
                    fontSize: isPortrait ? 12 : 14,
                    fontWeight: 900,
                    color: theme.accent,
                    marginBottom: 6,
                  }}
                >
                  ${endVal.toLocaleString()}
                </div>
                <div
                  style={{
                    width: '100%',
                    height: Math.max(4, barH * finalSpr),
                    backgroundColor: theme.accent,
                    borderRadius: '8px 8px 0 0',
                    boxShadow: `0 0 16px ${theme.accent}66`,
                  }}
                />
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    marginTop: 8,
                    fontSize: isPortrait ? 10 : 12,
                    fontWeight: 800,
                    color: theme.text,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {props.end_label || 'Final'}
                </div>
              </div>
            );
          })()}
        </div>
      </div>
    </Layout>
  );
};
