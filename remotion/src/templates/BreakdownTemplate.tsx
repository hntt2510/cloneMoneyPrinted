import React from 'react';
import { useCurrentFrame } from 'remotion';
import { Background } from '../components/Background';
import { Layout } from '../components/Layout';
import { SlideIn, SegmentedBar } from '../components/MotionPrimitives';
import { resolveTheme } from '../theme/theme';
import { ComparisonProps } from '../types';

export const BreakdownTemplate: React.FC<ComparisonProps> = ({
  headline, items = [], theme: customTheme, isGrouped = false, groupSceneIndex = 0,
}) => {
  const frame = useCurrentFrame();
  const theme = resolveTheme(customTheme);

  const total = items.reduce((sum, item) => sum + (item.numeric_value || 0), 0);
  
  // Define segments for the SegmentedBar
  const segments = items.map((item, idx) => ({
    value: item.numeric_value || 0,
    color: item.highlight ? theme.accent : theme.primary,
    label: item.label,
  }));

  // Determine what to show based on groupSceneIndex
  // 0: full bar + TOTAL label
  // 1: split off + YOU PAY label (for item 1 if 2 items)
  // 2: equation resolve

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="flat" theme={theme} subtle_motion />
      
      <SlideIn startFrame={0}>
        <div style={{ position: 'absolute', top: '15%', width: '100%', textAlign: 'center', fontSize: 48, fontWeight: 800, color: theme.text }}>
          {headline}
        </div>
      </SlideIn>

      <div style={{ position: 'absolute', top: '40%', left: '10%', right: '10%' }}>
        {groupSceneIndex === 0 && (
          <SlideIn startFrame={5}>
            <div style={{ textAlign: 'center', marginBottom: 16 }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: theme.muted, textTransform: 'uppercase' }}>TOTAL</div>
              <div style={{ fontSize: 48, fontWeight: 900, color: theme.text }}>{items[0]?.value}</div>
            </div>
            <SegmentedBar segments={[{value: total, color: theme.primary, label: 'TOTAL'}]} total={total} theme={theme} />
          </SlideIn>
        )}
        
        {groupSceneIndex === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
            <SlideIn startFrame={5}>
              <div style={{ textAlign: 'center', marginBottom: 16 }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: theme.accent, textTransform: 'uppercase' }}>{items[0]?.label}</div>
                <div style={{ fontSize: 48, fontWeight: 900, color: theme.accent }}>{items[0]?.value}</div>
              </div>
              <SegmentedBar segments={[segments[0]]} total={total} theme={theme} />
            </SlideIn>
          </div>
        )}
        
        {groupSceneIndex >= 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
            <SegmentedBar segments={segments} total={total} theme={theme} />
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 16 }}>
              {items.map((item, idx) => (
                <div key={idx} style={{ textAlign: 'center', flex: 1 }}>
                  <div style={{ fontSize: 20, fontWeight: 700, color: item.highlight ? theme.accent : theme.muted, textTransform: 'uppercase' }}>{item.label}</div>
                  <div style={{ fontSize: 32, fontWeight: 900, color: theme.text }}>{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
};
