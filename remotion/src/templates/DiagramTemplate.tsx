import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { CameraPush, DataConnector } from '../components/EditorialPrimitives';
import { Layout } from '../components/Layout';
import { ProgressiveText } from '../components/ProgressiveText';
import { fitText } from '../layout';
import { resolveTheme } from '../theme/theme';
import { DiagramProps } from '../types';

export const DiagramTemplate: React.FC<DiagramProps> = ({
  headline,
  nodes = [],
  edges = [],
  eyebrow,
  subtext,
  theme: customTheme,
  isGrouped = false,
  animation_plan,
  renderer_decision,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const bgTreatment = renderer_decision?.background_treatment || 'soft_grid';
  const nodeCount = Math.max(1, nodes.length);

  // Setup header
  const titleFit = fitText({
    text: headline,
    maxWidth: width * 0.85,
    maxHeight: 100,
    preferredFontSize: isPortrait ? 24 : 34,
    minimumFontSize: isPortrait ? 18 : 22,
    maxLines: 2,
    role: 'headline',
  });

  const headerSpr = spring({
    frame: Math.max(0, frame - 2),
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  // Calculate timing slices for each node
  const availableFrames = durationInFrames - 20; // leave final hold
  const nodeDuration = Math.round(availableFrames / nodeCount);

  // Layout calculations
  const flowZoneWidth = width * (isPortrait ? 0.88 : 0.82);
  const flowZoneHeight = height * (isPortrait ? 0.58 : 0.40);
  const flowTop = height * (isPortrait ? 0.28 : 0.42);

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant={bgTreatment} theme={theme} subtle_motion />

      <CameraPush scaleTo={1.025}>
        {/* Title Zone */}
        <div
          style={{
            position: 'absolute',
            top: Math.round(height * (isPortrait ? 0.12 : 0.18)),
            left: (width - width * 0.85) / 2,
            width: width * 0.85,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            textAlign: 'center',
            opacity: headerSpr,
            transform: `translateY(${interpolate(headerSpr, [0, 1], [14, 0])}px)`,
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
                marginBottom: 6,
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
              display: 'flex',
              justifyContent: 'center',
            }}
          >
            <ProgressiveText
              text={headline}
              startFrame={0}
              endFrame={Math.round(durationInFrames * 0.25)}
              fontSize={titleFit.fontSize}
              lineHeight={`${titleFit.lineHeight}px`}
              color={theme.text}
              fontWeight={800}
              maxWidth={width * 0.85}
            />
          </h1>
        </div>

        {/* Nodes & Connectors Container */}
        <div
          style={{
            position: 'absolute',
            top: flowTop,
            left: (width - flowZoneWidth) / 2,
            width: flowZoneWidth,
            height: flowZoneHeight,
            display: 'flex',
            flexDirection: isPortrait ? 'column' : 'row',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: isPortrait ? 16 : 24,
            zIndex: 5,
          }}
        >
          {nodes.map((node, index) => {
            const startF = index * nodeDuration;
            const endF = startF + nodeDuration;

            const nodeSpr = spring({
              frame: Math.max(0, frame - startF),
              fps,
              config: { damping: 14, stiffness: 130 },
            });

            const isActive = frame >= startF;
            const isCurrent = frame >= startF && frame < endF;

            const nodeBg = isCurrent
              ? `${theme.primary}2A`
              : isActive
              ? `${theme.surface}CC`
              : `${theme.surface}44`;

            const borderColor = isCurrent
              ? theme.accent
              : isActive
              ? theme.surfaceBorder
              : `${theme.surfaceBorder}40`;

            return (
              <React.Fragment key={node.id}>
                {/* Node Card */}
                <div
                  style={{
                    flex: 1,
                    width: isPortrait ? '100%' : 'auto',
                    height: isPortrait ? 'auto' : 130,
                    padding: isPortrait ? '12px 20px' : '16px 20px',
                    borderRadius: 18,
                    backgroundColor: nodeBg,
                    border: `2px solid ${borderColor}`,
                    boxShadow: isCurrent
                      ? `0 0 28px ${theme.primary}55`
                      : isActive
                      ? `0 0 16px rgba(0,0,0,0.3)`
                      : 'none',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    textAlign: 'center',
                    opacity: nodeSpr,
                    transform: `scale(${interpolate(nodeSpr, [0, 1], [0.85, 1])})`,
                    transition: 'background-color 0.2s ease, border-color 0.2s ease',
                    position: 'relative',
                  }}
                >
                  {/* Step index badge */}
                  <div
                    style={{
                      position: 'absolute',
                      top: -10,
                      left: 16,
                      fontSize: 11,
                      fontWeight: 900,
                      color: isCurrent ? '#ffffff' : theme.muted,
                      backgroundColor: isCurrent ? theme.accent : theme.surfaceBorder,
                      padding: '2px 8px',
                      borderRadius: 10,
                      letterSpacing: '0.05em',
                    }}
                  >
                    {index + 1}
                  </div>

                  <span
                    style={{
                      fontSize: isPortrait ? 18 : 22,
                      fontWeight: 900,
                      color: isCurrent ? theme.primary : theme.text,
                      letterSpacing: '-0.01em',
                    }}
                  >
                    {node.label}
                  </span>

                  {node.sublabel && (
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: theme.muted,
                        marginTop: 4,
                        textTransform: 'uppercase',
                        letterSpacing: '0.08em',
                      }}
                    >
                      {node.sublabel}
                    </span>
                  )}
                </div>

                {/* Connector Arrow between nodes */}
                {index < nodeCount - 1 && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: frame >= endF ? theme.accent : theme.surfaceBorder,
                      fontSize: isPortrait ? 20 : 28,
                      fontWeight: 900,
                      opacity: interpolate(
                        frame,
                        [startF + nodeDuration * 0.5, endF],
                        [0.2, 1],
                        { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
                      ),
                      transform: isPortrait ? 'rotate(90deg)' : 'none',
                    }}
                  >
                    ➜
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      </CameraPush>
    </Layout>
  );
};
