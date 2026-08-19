import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { computeWaterfallLayout, getItemFocusState, SEMANTIC_COLORS } from '../layout';
import { resolveTheme } from '../theme/theme';
import { WaterfallProps } from '../types';

export const WaterfallTemplate: React.FC<WaterfallProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(props.theme);
  const isPortrait = height > width;

  // 1. Compute Deterministic Waterfall Layout
  const layout = computeWaterfallLayout({
    width,
    height,
    headline: props.headline,
    startValue: Number(props.start_value) || 100,
    startLabel: props.start_label || 'Base Quote',
    steps: props.steps,
    endValue: Number(props.end_value) || 110,
    endLabel: props.end_label || 'Final Premium',
    isPortrait,
  });

  const { titleBounds, titleFit, chartContainerBounds, columns, connectors } = layout;

  const headerSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  const totalCols = columns.length;

  return (
    <Layout theme={theme} isGrouped={props.isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />

      {/* ZONE 1: TITLE ZONE */}
      <div
        style={{
          position: 'absolute',
          left: titleBounds.x,
          top: titleBounds.y,
          width: titleBounds.width,
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
            maxWidth: titleBounds.width * 0.9,
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
          left: chartContainerBounds.x,
          top: chartContainerBounds.y,
          width: chartContainerBounds.width,
          height: chartContainerBounds.height,
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
            left: 28,
            right: 28,
            bottom: isPortrait ? 48 : 58,
            height: 2,
            backgroundColor: theme.surfaceBorder,
          }}
        />

        {/* Render Columns */}
        {columns.map((col) => {
          const idx = col.index;
          const focus = getItemFocusState(idx, frame, durationInFrames, props.animation_plan, totalCols);

          const delay = 8 + idx * Math.max(8, Math.floor((durationInFrames * 0.45) / totalCols));
          const colSpr = spring({
            frame: Math.max(0, frame - delay),
            fps,
            config: { damping: 15, stiffness: 100 },
          });

          const localBarX = col.barBounds.x - chartContainerBounds.x;
          const localBarY = col.barBounds.y - chartContainerBounds.y;
          const localValX = col.valueBounds.x - chartContainerBounds.x;
          const localValY = col.valueBounds.y - chartContainerBounds.y;
          const localLblX = col.labelBounds.x - chartContainerBounds.x;
          const localLblY = col.labelBounds.y - chartContainerBounds.y;

          return (
            <React.Fragment key={`col-${idx}`}>
              {/* Value Label above column */}
              <div
                style={{
                  position: 'absolute',
                  left: localValX,
                  top: localValY,
                  width: col.valueBounds.width,
                  fontSize: isPortrait ? 13 : 15,
                  fontWeight: 900,
                  color: focus.isActive ? '#ffffff' : col.color,
                  textAlign: 'center',
                  opacity: colSpr * focus.opacity,
                  textShadow: focus.isActive ? `0 0 10px ${col.color}` : 'none',
                  transform: `scale(${focus.scale})`,
                  transition: 'opacity 0.2s ease',
                  zIndex: 4,
                }}
              >
                {col.displayValue}
              </div>

              {/* Bar Block */}
              <div
                style={{
                  position: 'absolute',
                  left: localBarX,
                  top: localBarY,
                  width: col.barBounds.width,
                  height: Math.max(4, col.barBounds.height * colSpr),
                  backgroundColor: col.color,
                  borderRadius: col.type === 'step' ? 6 : '6px 6px 0 0',
                  boxShadow: focus.isActive
                    ? `0 0 18px ${col.color}99`
                    : `0 0 10px ${col.color}40`,
                  opacity: colSpr * focus.opacity,
                  transform: `scale(${focus.scale})`,
                  transition: 'opacity 0.2s ease',
                  zIndex: 3,
                }}
              />

              {/* Category Label below baseline */}
              <div
                style={{
                  position: 'absolute',
                  left: localLblX,
                  top: localLblY,
                  width: col.labelBounds.width,
                  fontSize: isPortrait ? 11 : 13,
                  fontWeight: col.type === 'final' ? 900 : 800,
                  color: focus.isActive ? '#ffffff' : col.type === 'final' ? theme.text : theme.muted,
                  textAlign: 'center',
                  opacity: colSpr * focus.opacity,
                  wordBreak: 'break-word',
                  transition: 'opacity 0.2s ease',
                  zIndex: 4,
                }}
              >
                {col.label}
              </div>
            </React.Fragment>
          );
        })}

        {/* Connectors */}
        {connectors.map((c, idx) => {
          const startX = c.startX - chartContainerBounds.x;
          const startY = c.startY - chartContainerBounds.y;
          const endX = c.endX - chartContainerBounds.x;
          const connW = endX - startX;

          return (
            <div
              key={`conn-${idx}`}
              style={{
                position: 'absolute',
                left: startX,
                top: startY,
                width: connW,
                height: 1.5,
                backgroundColor: SEMANTIC_COLORS.waterfall.connector,
                borderTop: '1.5px dashed rgba(255,255,255,0.3)',
                zIndex: 2,
              }}
            />
          );
        })}
      </div>
    </Layout>
  );
};
