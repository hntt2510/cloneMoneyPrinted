import React from 'react';
import { interpolate, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { SlideIn, ScalePop } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { TimelineProps } from '../types';

export const TimelineTemplate: React.FC<TimelineProps> = ({
  headline, milestones, theme: customTheme, isGrouped = false, animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  // Track-based V2:
  // Horizontal track for landscape, vertical for portrait.

  const trackW = isPortrait ? 6 : width * 0.7;
  const trackH = isPortrait ? height * 0.6 : 6;
  const trackLeft = isPortrait ? width * 0.15 : (width - trackW) / 2;
  const trackTop = isPortrait ? (height - trackH) / 2 : height * 0.6;
  
  const lastBeat = animation_plan?.beats?.find(b => b.data_ref === `m_${milestones.length - 1}`);
  const trackEndFrame = lastBeat?.start_frame ?? 60;
  const trackProgress = interpolate(frame, [0, trackEndFrame], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />
      
      <SlideIn startFrame={0}>
        <div style={{ position: 'absolute', top: '10%', width: '100%', textAlign: 'center', fontSize: isPortrait ? 32 : 48, fontWeight: 800, color: theme.text }}>
          {headline}
        </div>
      </SlideIn>

      <div style={{ position: 'absolute', left: trackLeft, top: trackTop, width: trackW, height: trackH }}>
        {/* Track Base */}
        <div style={{
          position: 'absolute', top: 0, left: 0,
          width: isPortrait ? '100%' : `${trackProgress * 100}%`,
          height: isPortrait ? `${trackProgress * 100}%` : '100%',
          backgroundColor: theme.surfaceBorder,
        }}>
          <div style={{ width: '100%', height: '100%', backgroundColor: theme.primary }} />
        </div>

        {/* Milestones */}
        {milestones.map((m, idx) => {
          const beat = animation_plan?.beats?.find(b => b.data_ref === `m_${idx}`);
          const startFrame = beat?.start_frame ?? (15 + idx * 15);
          
          if (frame < startFrame) return null;
          
          const posPct = idx / Math.max(1, milestones.length - 1);
          const dotLeft = isPortrait ? 3 : posPct * trackW;
          const dotTop = isPortrait ? posPct * trackH : 3;

          return (
            <div key={`m-${idx}`} style={{ position: 'absolute', left: dotLeft, top: dotTop }}>
              {/* Dot */}
              <ScalePop startFrame={startFrame} boost={0.2}>
                <div style={{
                  position: 'absolute', left: 0, top: 0, width: 24, height: 24,
                  transform: 'translate(-50%, -50%)',
                  backgroundColor: m.is_active ? theme.accent : theme.surface,
                  border: `4px solid ${m.is_active ? theme.background : theme.primary}`,
                  borderRadius: '50%',
                  boxShadow: m.is_active ? `0 0 12px ${theme.accent}80` : 'none',
                }} />
              </ScalePop>
              
              {/* Label */}
              <SlideIn startFrame={startFrame + 5} distance={10}>
                <div style={{
                  position: 'absolute',
                  left: isPortrait ? 32 : -100,
                  top: isPortrait ? -20 : (m.is_active ? -80 : 32),
                  width: isPortrait ? width * 0.7 : 200,
                  textAlign: isPortrait ? 'left' : 'center',
                }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: m.is_active ? theme.accent : theme.muted }}>{m.time_label}</div>
                  <div style={{ fontSize: 24, fontWeight: 800, color: theme.text }}>{m.title}</div>
                </div>
              </SlideIn>
            </div>
          );
        })}
      </div>
    </Layout>
  );
};
