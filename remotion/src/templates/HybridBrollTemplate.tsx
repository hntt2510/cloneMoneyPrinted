import React from 'react';
import { Img, interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { CameraPush, StatBadge } from '../components/EditorialPrimitives';
import { Layout } from '../components/Layout';
import { ProgressiveText } from '../components/ProgressiveText';
import { fitText } from '../layout';
import { resolveTheme } from '../theme/theme';
import { HybridAssetProps } from '../types';

export const HybridBrollTemplate: React.FC<HybridAssetProps> = ({
  headline,
  asset_path,
  data_panel = {},
  layout = 'asset_left_data_right',
  eyebrow,
  asset_mode = 'video',
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

  const normalizedAssetSrc = (() => {
    if (!asset_path) return '';
    const clean = asset_path.trim();
    if (clean.startsWith('http://') || clean.startsWith('https://') || clean.startsWith('data:')) {
      return clean;
    }
    try {
      return staticFile(clean);
    } catch {
      return clean;
    }
  })();

  const panelSpr = spring({
    frame: Math.max(0, frame - 5),
    fps,
    config: { damping: 16, stiffness: 110 },
  });

  const isLeftAsset = layout.includes('left') || layout === 'asset_left_data_right';

  const panelWidth = width * (isPortrait ? 0.90 : 0.44);
  const panelHeight = height * (isPortrait ? 0.45 : 0.72);

  const titleFit = fitText({
    text: headline,
    maxWidth: panelWidth * 0.9,
    maxHeight: 90,
    preferredFontSize: isPortrait ? 22 : 30,
    minimumFontSize: isPortrait ? 16 : 20,
    maxLines: 2,
    role: 'headline',
  });

  // Data panel values
  const panelVal = data_panel.value || data_panel.amount || data_panel.display_value || '';
  const panelLabel = data_panel.label || data_panel.context_label || eyebrow || '';

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant="asset_blur" theme={theme} />

      <CameraPush scaleTo={1.025}>
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            display: 'flex',
            flexDirection: isPortrait ? 'column' : (isLeftAsset ? 'row' : 'row-reverse'),
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: isPortrait ? '24px 20px' : '40px 60px',
            boxSizing: 'border-box',
            gap: isPortrait ? 20 : 40,
          }}
        >
          {/* Asset Frame (Video / Image) */}
          <div
            style={{
              flex: 1,
              width: isPortrait ? '100%' : '50%',
              height: isPortrait ? '45%' : '80%',
              borderRadius: 24,
              overflow: 'hidden',
              border: `2px solid ${theme.surfaceBorder}`,
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              position: 'relative',
              backgroundColor: theme.surface,
            }}
          >
            {normalizedAssetSrc && (normalizedAssetSrc.endsWith('.mp4') || asset_mode === 'video') ? (
              <OffthreadVideo
                src={normalizedAssetSrc}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                volume={0}
              />
            ) : normalizedAssetSrc ? (
              <Img
                src={normalizedAssetSrc}
                style={{ width: '100%', height: '100%', objectFit: 'cover' }}
              />
            ) : (
              <div
                style={{
                  width: '100%',
                  height: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: theme.surface,
                  color: theme.muted,
                  fontSize: 16,
                  fontWeight: 700,
                }}
              >
                EVIDENCE MEDIA
              </div>
            )}
          </div>

          {/* Grounded Data Card Panel */}
          <div
            style={{
              width: panelWidth,
              padding: isPortrait ? '20px 24px' : '32px 36px',
              borderRadius: 24,
              backgroundColor: `${theme.surface}E6`,
              border: `1.5px solid ${theme.surfaceBorder}`,
              boxShadow: `0 12px 40px rgba(0,0,0,0.4), 0 0 24px ${theme.primary}22`,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-start',
              opacity: panelSpr,
              transform: `translateY(${interpolate(panelSpr, [0, 1], [20, 0])}px)`,
              boxSizing: 'border-box',
            }}
          >
            {eyebrow && (
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  letterSpacing: '0.12em',
                  color: theme.accent,
                  textTransform: 'uppercase',
                  marginBottom: 6,
                }}
              >
                {eyebrow}
              </div>
            )}

            <h2
              style={{
                margin: '0 0 16px 0',
                fontSize: titleFit.fontSize,
                lineHeight: `${titleFit.lineHeight}px`,
                fontWeight: 800,
                color: theme.text,
                letterSpacing: '-0.02em',
              }}
            >
              <ProgressiveText
                text={headline}
                startFrame={0}
                endFrame={Math.round(durationInFrames * 0.3)}
                fontSize={titleFit.fontSize}
                lineHeight={`${titleFit.lineHeight}px`}
                color={theme.text}
                fontWeight={800}
                maxWidth={panelWidth * 0.9}
              />
            </h2>

            {/* Primary Grounded Metric in Panel */}
            {panelVal && (
              <div style={{ marginTop: 8, marginBottom: 12 }}>
                <span
                  style={{
                    fontSize: isPortrait ? 38 : 52,
                    fontWeight: 900,
                    color: theme.primary,
                    letterSpacing: '-0.02em',
                    lineHeight: 1.05,
                  }}
                >
                  {panelVal}
                </span>
                {panelLabel && (
                  <div
                    style={{
                      fontSize: 13,
                      fontWeight: 800,
                      color: theme.muted,
                      textTransform: 'uppercase',
                      letterSpacing: '0.10em',
                      marginTop: 4,
                    }}
                  >
                    {panelLabel}
                  </div>
                )}
              </div>
            )}

            {subtext && (
              <p
                style={{
                  margin: '8px 0 0 0',
                  fontSize: 14,
                  fontWeight: 600,
                  color: theme.muted,
                  lineHeight: 1.4,
                }}
              >
                {subtext}
              </p>
            )}
          </div>
        </div>
      </CameraPush>
    </Layout>
  );
};
