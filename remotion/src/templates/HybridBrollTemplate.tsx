import React from 'react';
import { Img, interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { CameraPush } from '../components/EditorialPrimitives';
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

  // ---------------------------------------------------------------------------
  // 1. REBALANCED OPTICAL DIMENSIONS & POSITIONING
  // ---------------------------------------------------------------------------
  // Landscape: Asset 46%, Panel 42%, Gap 5%, Horizontal Padding 3.5% (Total 100%, COM = 51.0%)
  // Portrait: Asset 44% height, Panel 42% height, Gap 4% height, centered horizontally
  const isLeftAsset = layout.includes('left') || layout === 'asset_left_data_right';

  const assetWidth = width * (isPortrait ? 0.90 : 0.46);
  const assetHeight = height * (isPortrait ? 0.44 : 0.78);

  const panelWidth = width * (isPortrait ? 0.90 : 0.42);
  const panelHeight = height * (isPortrait ? 0.42 : 0.72);

  const gap = isPortrait ? height * 0.04 : width * 0.05;
  const paddingX = isPortrait ? width * 0.05 : width * 0.035;
  const paddingY = isPortrait ? height * 0.04 : height * 0.10;

  // ---------------------------------------------------------------------------
  // 2. 5-STAGE CHOREOGRAPHY TIMING
  // ---------------------------------------------------------------------------
  const setupBeat = animation_plan?.beats?.find((b) => b.kind === 'setup' || b.data_ref === 'eyebrow');
  const revealBeat = animation_plan?.beats?.find((b) => b.kind === 'reveal' || b.data_ref === 'headline');
  const numberBeat = animation_plan?.beats?.find((b) => b.kind === 'number' || b.data_ref === 'number');
  const highlightBeat = animation_plan?.beats?.find((b) => b.kind === 'highlight');
  const contextBeat = animation_plan?.beats?.find((b) => b.kind === 'phrase' || b.data_ref === 'context');

  // Stage 1: Container & Frame Entrance (frame 0..5)
  const containerSpr = spring({
    frame: Math.max(0, frame - 2),
    fps,
    config: { damping: 16, stiffness: 120 },
  });

  const assetSpr = spring({
    frame,
    fps,
    config: { damping: 16, stiffness: 110 },
  });

  // Stage 2: Concept / Headline (begins on concept phrase beat)
  const conceptStart = revealBeat
    ? revealBeat.start_frame
    : (setupBeat ? setupBeat.end_frame : Math.round(durationInFrames * 0.12));
  const conceptEnd = revealBeat
    ? revealBeat.end_frame
    : Math.max(conceptStart + 8, Math.round(durationInFrames * 0.32));

  // Stage 3: Number & Delta (begins on numeric phrase beat)
  const numberStart = numberBeat
    ? numberBeat.start_frame
    : (revealBeat ? revealBeat.end_frame : Math.round(durationInFrames * 0.35));
  const numberEnd = numberBeat
    ? numberBeat.end_frame
    : Math.max(numberStart + 15, Math.round(durationInFrames * 0.72));

  const numSpr = spring({
    frame: Math.max(0, frame - numberStart),
    fps,
    config: { damping: 14, stiffness: 130 },
  });

  // Stage 4: Supporting Qualifier / Subtext (begins on context beat)
  const contextStart = contextBeat
    ? contextBeat.start_frame
    : Math.max(numberEnd + 4, Math.round(durationInFrames * 0.75));

  const ctxSpr = spring({
    frame: Math.max(0, frame - contextStart),
    fps,
    config: { damping: 16, stiffness: 100 },
  });

  // Settle Pop on number highlight
  const popSpr = highlightBeat
    ? spring({ frame: Math.max(0, frame - highlightBeat.start_frame), fps, config: { damping: 8, stiffness: 200 } })
    : 0;
  const popScale = interpolate(popSpr, [0, 0.4, 1], [1, 1.04, 1]);

  // ---------------------------------------------------------------------------
  // 3. GROUNDED VALUES & COUNT-UP LOGIC
  // ---------------------------------------------------------------------------
  const panelVal = data_panel.value || data_panel.amount || data_panel.display_value || '';
  const panelLabel = data_panel.label || data_panel.context_label || eyebrow || '';
  const displayEyebrow = eyebrow || data_panel.eyebrow || 'METRIC';

  const rawValStr = (panelVal || '').toString();
  const rawNumericVal = data_panel.numeric_value !== undefined && data_panel.numeric_value !== null
    ? Number(data_panel.numeric_value)
    : (() => {
        const clean = rawValStr.replace(/[^0-9.]/g, '');
        const p = parseFloat(clean);
        return isNaN(p) ? null : p;
      })();

  const countProg = interpolate(frame, [numberStart, numberEnd], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const countEased = spring({
    frame: countProg * fps,
    fps,
    config: { damping: 18, stiffness: 80 },
  });

  const animatedValueStr = (() => {
    if (rawNumericVal === null || isNaN(rawNumericVal)) {
      return rawValStr;
    }
    if (frame < numberStart) {
      return '';
    }
    const currentNum = Math.round(countEased * rawNumericVal);
    const pfx = data_panel.prefix || (rawValStr.startsWith('$') ? '$' : '');
    let sfx = data_panel.suffix || '';
    if (!sfx) {
      if (rawValStr.endsWith('%')) sfx = '%';
      else if (rawValStr.endsWith('M')) sfx = 'M';
      else if (rawValStr.endsWith('K')) sfx = 'K';
      else if (rawValStr.endsWith('B')) sfx = 'B';
    }

    if (frame >= numberEnd) {
      return rawValStr;
    }
    return `${pfx}${currentNum.toLocaleString()}${sfx}`;
  })();

  // Delta configuration
  const deltaDir = data_panel.delta_direction || (data_panel.delta_display?.startsWith('+') ? 'positive' : data_panel.delta_display?.startsWith('-') ? 'negative' : 'neutral');
  const deltaColor = data_panel.delta_sentiment === 'negative'
    ? '#F87171'
    : data_panel.delta_sentiment === 'positive'
    ? '#34D399'
    : theme.accent;
  const deltaArrow = deltaDir === 'positive' ? '↑' : deltaDir === 'negative' ? '↓' : '';
  const deltaText = data_panel.delta_display || data_panel.delta_value || '';

  const titleFit = fitText({
    text: headline,
    maxWidth: panelWidth * 0.88,
    maxHeight: 90,
    preferredFontSize: isPortrait ? 22 : 30,
    minimumFontSize: isPortrait ? 16 : 20,
    maxLines: 2,
    role: 'headline',
  });

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
            justifyContent: 'center',
            padding: `${paddingY}px ${paddingX}px`,
            boxSizing: 'border-box',
            gap,
          }}
        >
          {/* Stage 1: Asset Frame (Left Footage / Evidence) */}
          <div
            style={{
              width: assetWidth,
              height: assetHeight,
              borderRadius: 24,
              overflow: 'hidden',
              border: `2px solid ${theme.surfaceBorder}`,
              boxShadow: '0 12px 36px rgba(0,0,0,0.55), 0 0 20px rgba(0,0,0,0.3)',
              position: 'relative',
              backgroundColor: theme.surface,
              opacity: assetSpr,
              transform: `translateY(${interpolate(assetSpr, [0, 1], [14, 0])}px)`,
              boxSizing: 'border-box',
              flexShrink: 0,
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
                  letterSpacing: '0.08em',
                }}
              >
                EVIDENCE MEDIA
              </div>
            )}
          </div>

          {/* Grounded Data Card Panel (Right Editorial Metric) */}
          <div
            style={{
              width: panelWidth,
              minHeight: isPortrait ? undefined : panelHeight,
              padding: isPortrait ? '20px 24px' : '32px 36px',
              borderRadius: 24,
              backgroundColor: `${theme.surface}E6`,
              border: `1.5px solid ${theme.surfaceBorder}`,
              boxShadow: `0 16px 48px rgba(0,0,0,0.45), 0 0 24px ${theme.primary}22`,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'center',
              alignItems: 'flex-start',
              opacity: containerSpr,
              transform: `translateY(${interpolate(containerSpr, [0, 1], [18, 0])}px)`,
              boxSizing: 'border-box',
              flexShrink: 0,
            }}
          >
            {/* Stage 1: Eyebrow Placeholder / Category */}
            {displayEyebrow && (
              <div
                style={{
                  fontSize: 12,
                  fontWeight: 800,
                  letterSpacing: '0.14em',
                  color: theme.accent,
                  textTransform: 'uppercase',
                  marginBottom: 8,
                }}
              >
                {displayEyebrow}
              </div>
            )}

            {/* Stage 2: Concept Headline Reveal on Concept Phrase Beat */}
            <h2
              style={{
                margin: '0 0 14px 0',
                fontSize: titleFit.fontSize,
                lineHeight: `${titleFit.lineHeight}px`,
                fontWeight: 800,
                color: theme.text,
                letterSpacing: '-0.02em',
                minHeight: titleFit.lineHeight,
              }}
            >
              {frame >= conceptStart ? (
                <ProgressiveText
                  text={headline}
                  startFrame={conceptStart}
                  endFrame={conceptEnd}
                  fontSize={titleFit.fontSize}
                  lineHeight={`${titleFit.lineHeight}px`}
                  color={theme.text}
                  fontWeight={800}
                  maxWidth={panelWidth * 0.88}
                  textAlign="left"
                />
              ) : (
                <span style={{ opacity: 0 }}>{headline}</span>
              )}
            </h2>

            {/* Stage 3: Grounded Metric Number Count-up on Numeric Narration Beat */}
            {panelVal && (
              <div
                style={{
                  marginTop: 6,
                  marginBottom: 10,
                  opacity: frame >= numberStart ? numSpr : 0,
                  transform: `scale(${frame >= numberStart ? interpolate(numSpr, [0, 1], [0.92, 1]) * popScale : 0.92})`,
                  transition: 'opacity 0.2s ease',
                  minHeight: isPortrait ? 44 : 58,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span
                    style={{
                      fontSize: isPortrait ? 38 : 52,
                      fontWeight: 900,
                      color: theme.primary,
                      letterSpacing: '-0.03em',
                      lineHeight: 1.05,
                      textShadow: `0 0 24px ${theme.primary}44`,
                    }}
                  >
                    {animatedValueStr || panelVal}
                  </span>

                  {/* Delta indicator if present */}
                  {deltaText && frame >= numberStart + 4 && (
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: '4px 10px',
                        borderRadius: 16,
                        backgroundColor: `${deltaColor}22`,
                        border: `1.2px solid ${deltaColor}`,
                        color: deltaColor,
                        fontSize: isPortrait ? 12 : 14,
                        fontWeight: 900,
                        boxShadow: `0 0 12px ${deltaColor}33`,
                      }}
                    >
                      {deltaArrow && <span>{deltaArrow}</span>}
                      <span>{deltaText}</span>
                    </div>
                  )}
                </div>

                {panelLabel && (
                  <div
                    style={{
                      fontSize: 12,
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

            {/* Stage 4: Supporting Qualifier / Context on Subsequent Beat */}
            {subtext && (
              <p
                style={{
                  margin: '8px 0 0 0',
                  fontSize: 14,
                  fontWeight: 600,
                  color: theme.muted,
                  lineHeight: 1.4,
                  opacity: frame >= contextStart ? ctxSpr : 0,
                  transform: `translateY(${frame >= contextStart ? interpolate(ctxSpr, [0, 1], [8, 0]) : 8}px)`,
                  transition: 'opacity 0.2s ease',
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
