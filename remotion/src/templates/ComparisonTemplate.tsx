import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { DividerReveal, SlideIn, MaskReveal } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { ComparisonProps } from '../types';

export const ComparisonTemplate: React.FC<ComparisonProps> = ({
  headline, items = [], subtext,
  theme: customTheme, isGrouped = false, isFirstInGroup = true, animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  if (items.length === 2) {
    // split_compare layout
    const item0Beat = animation_plan?.beats?.find(b => b.data_ref === 'item_0');
    const item1Beat = animation_plan?.beats?.find(b => b.data_ref === 'item_1');
    const dividerBeat = animation_plan?.beats?.find(b => b.kind === 'split');
    const takeawayBeat = animation_plan?.beats?.find(b => b.kind === 'takeaway');

    const isContinuous = isGrouped && !isFirstInGroup;
    const i0Start = isContinuous ? 0 : (item0Beat?.start_frame ?? 0);
    const divStart = isContinuous ? 0 : (dividerBeat?.start_frame ?? i0Start + 15);
    const i1Start = isContinuous ? 0 : (item1Beat?.start_frame ?? divStart + 10);
    const takeStart = isContinuous ? 0 : (takeawayBeat?.start_frame ?? i1Start + 15);

    const isLongValue0 = (items[0]?.value?.length ?? 0) > 8;
    const isLongValue1 = (items[1]?.value?.length ?? 0) > 8;
    const isLongValue = isLongValue0 || isLongValue1;

    const labelSize = isPortrait ? (isLongValue ? 20 : 24) : (isLongValue ? 24 : 32);
    const valueSize0 = isLongValue0 ? (isPortrait ? 24 : 36) : (isPortrait ? 56 : 72);
    const valueSize1 = isLongValue1 ? (isPortrait ? 24 : 36) : (isPortrait ? 56 : 72);

    return (
      <Layout theme={theme} isGrouped={isGrouped}>
        <Background variant="split_tone" theme={theme} subtle_motion />
        
        {/* Headline */}
        <div style={{
          position: 'absolute', top: '10%', width: '100%',
          textAlign: 'center', fontSize: isPortrait ? 32 : 48, fontWeight: 800, color: theme.text,
        }}>
          {headline}
        </div>

        {/* Left / Top Side */}
        <div style={{
          position: 'absolute',
          top: isPortrait ? '25%' : '35%',
          left: isPortrait ? '10%' : '15%',
          width: isPortrait ? '80%' : '32%',
          textAlign: isPortrait ? 'center' : 'left',
        }}>
          {frame >= i0Start && (
            <SlideIn startFrame={i0Start} distance={10}>
              <div style={{ fontSize: labelSize, fontWeight: 700, color: items[0].highlight ? theme.accent : theme.muted, textTransform: 'uppercase', marginBottom: 16, letterSpacing: '0.08em' }}>
                {items[0].label}
              </div>
              <div style={{ fontSize: valueSize0, fontWeight: isLongValue0 ? 700 : 900, color: items[0].highlight ? theme.accent : theme.text, lineHeight: isLongValue0 ? 1.3 : 1.1 }}>
                {items[0].value}
              </div>
            </SlideIn>
          )}
        </div>

        {/* Divider */}
        {frame >= divStart && (
          isPortrait ? (
            <div style={{ position: 'absolute', top: '50%', left: '20%', right: '20%', height: 2, background: theme.surfaceBorder }}>
              <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', background: theme.background, padding: '4px 8px', color: theme.muted, fontWeight: 'bold' }}>VS</div>
            </div>
          ) : (
            <DividerReveal startFrame={divStart} theme={theme} label="VS" />
          )
        )}

        {/* Right / Bottom Side */}
        <div style={{
          position: 'absolute',
          top: isPortrait ? '65%' : '35%',
          right: isPortrait ? undefined : '15%',
          left: isPortrait ? '10%' : undefined,
          width: isPortrait ? '80%' : '32%',
          textAlign: isPortrait ? 'center' : 'right',
        }}>
          {frame >= i1Start && (
            <SlideIn startFrame={i1Start} distance={10}>
              <div style={{ fontSize: labelSize, fontWeight: 700, color: items[1].highlight ? theme.accent : theme.muted, textTransform: 'uppercase', marginBottom: 16, letterSpacing: '0.08em' }}>
                {items[1].label}
              </div>
              <div style={{ fontSize: valueSize1, fontWeight: isLongValue1 ? 700 : 900, color: items[1].highlight ? theme.accent : theme.text, lineHeight: isLongValue1 ? 1.3 : 1.1 }}>
                {items[1].value}
              </div>
            </SlideIn>
          )}
        </div>
      </Layout>
    );
  }

  // 3+ items: stacked_breakdown
  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />
      <div style={{
        position: 'absolute', top: '10%', width: '100%',
        textAlign: 'center', fontSize: isPortrait ? 32 : 48, fontWeight: 800, color: theme.text,
      }}>
        {headline}
      </div>
      
      <div style={{
        position: 'absolute', top: '25%', left: '10%', right: '10%',
        display: 'flex', flexDirection: 'column', gap: 24,
      }}>
        {items.map((item, idx) => {
          const beat = animation_plan?.beats?.find(b => b.data_ref === `item_${idx}`);
          const startFrame = beat?.start_frame ?? (idx * 15);
          
          if (frame < startFrame) return null;

          return (
            <SlideIn key={idx} startFrame={startFrame} distance={15}>
              <div style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '20px 24px', backgroundColor: theme.surface,
                borderRadius: 16, borderLeft: item.highlight ? `6px solid ${theme.accent}` : `1px solid ${theme.surfaceBorder}`,
              }}>
                <div style={{ fontSize: isPortrait ? 20 : 28, fontWeight: 700, color: theme.muted }}>{item.label}</div>
                <div style={{ fontSize: isPortrait ? 28 : 40, fontWeight: 900, color: item.highlight ? theme.accent : theme.text }}>{item.value}</div>
              </div>
            </SlideIn>
          );
        })}
      </div>
    </Layout>
  );
};
