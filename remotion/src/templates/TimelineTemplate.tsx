import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Header } from '../components/Header';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { Theme, TimelineProps } from '../types';

export const TimelineTemplate: React.FC<TimelineProps> = ({
  headline,
  milestones = [],
  highlight_index,
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
  animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height, durationInFrames } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;
  const validMilestones = milestones.slice(0, 5);
  const count = validMilestones.length;

  let lineStartFrame = isContinuous ? 0 : 8;
  const lineDuration = Math.max(20, Math.round(durationInFrames * (isContinuous ? 0.8 : 0.5)));
  
  const mBeats = animation_plan?.beats?.filter(b => b.kind === 'milestone') || [];
  
  let lineProgress = isContinuous
    ? 1
    : interpolate(frame, [lineStartFrame, lineStartFrame + lineDuration], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
      
  if (mBeats.length > 0) {
    const firstBeat = mBeats[0];
    const lastBeat = mBeats[mBeats.length - 1];
    lineProgress = interpolate(frame, [firstBeat.start_frame, lastBeat.start_frame], [0, 1], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Header headline={headline} theme={theme} isGrouped={isGrouped} isFirstInGroup={isFirstInGroup} />
      <div
        style={{
          position: 'relative',
          width: '92%',
          display: 'flex',
          flexDirection: isPortrait ? 'column' : 'row',
          justifyContent: 'space-between',
          alignItems: isPortrait ? 'flex-start' : 'center',
          gap: isPortrait ? Math.round(height * 0.04) : 0,
          marginTop: Math.round(height * 0.02),
        }}
      >
        {isPortrait ? (
          <div
            style={{
              position: 'absolute',
              left: 28,
              top: 20,
              bottom: 20,
              width: 4,
              backgroundColor: theme.border,
              zIndex: 0,
            }}
          >
            <div
              style={{
                width: '100%',
                height: `${lineProgress * 100}%`,
                backgroundColor: theme.accent,
              }}
            />
          </div>
        ) : (
          <div
            style={{
              position: 'absolute',
              top: 28,
              left: 30,
              right: 30,
              height: 4,
              backgroundColor: theme.border,
              zIndex: 0,
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${lineProgress * 100}%`,
                backgroundColor: theme.accent,
              }}
            />
          </div>
        )}

        {validMilestones.map((m, idx) => {
          let nodeDelay = isContinuous ? 0 : 10 + Math.round((idx / Math.max(1, count - 1)) * lineDuration * 0.8);
          if (mBeats[idx]) {
            nodeDelay = mBeats[idx].start_frame;
          }
          
          const spr = spring({
            frame: Math.max(0, frame - nodeDelay),
            fps,
            config: { damping: 12, stiffness: 100, mass: 0.8 },
          });

          const nodeScale = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
          const nodeOpacity = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
          const isHighlighted = highlight_index !== null && highlight_index !== undefined ? highlight_index === idx : !!m.is_active;

          return (
            <div
              key={idx}
              style={{
                opacity: nodeOpacity,
                transform: `scale(${nodeScale})`,
                display: 'flex',
                flexDirection: isPortrait ? 'row' : 'column',
                alignItems: isPortrait ? 'center' : 'center',
                zIndex: 1,
                gap: isPortrait ? 24 : 12,
                flex: isPortrait ? undefined : 1,
                textAlign: isPortrait ? 'left' : 'center',
              }}
            >
              <div
                style={{
                  width: isPortrait ? 56 : 64,
                  height: isPortrait ? 56 : 64,
                  borderRadius: '50%',
                  backgroundColor: isHighlighted ? theme.accent : theme.surface,
                  border: `3px solid ${isHighlighted ? theme.text : theme.primary}`,
                  color: isHighlighted ? theme.background : theme.text,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 900,
                  fontSize: isPortrait ? 18 : 20,
                  boxShadow: isHighlighted ? `0 0 24px ${theme.accent}` : undefined,
                  flexShrink: 0,
                }}
              >
                {idx + 1}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <div
                  style={{
                    fontSize: Math.min(28, Math.max(16, Math.round(width * 0.022))),
                    fontWeight: 800,
                    color: isHighlighted ? theme.accent : theme.text,
                    textTransform: 'uppercase',
                  }}
                >
                  {m.time_label}
                </div>
                <div
                  style={{
                    fontSize: Math.min(22, Math.max(14, Math.round(width * 0.018))),
                    fontWeight: 600,
                    color: theme.muted,
                    marginTop: 4,
                  }}
                >
                  {m.title}
                </div>
                {m.description && (
                  <div
                    style={{
                      fontSize: Math.min(18, Math.max(12, Math.round(width * 0.015))),
                      fontWeight: 400,
                      color: theme.muted,
                      marginTop: 2,
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
