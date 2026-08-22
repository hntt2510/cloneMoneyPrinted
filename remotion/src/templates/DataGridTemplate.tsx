import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Background } from '../components/Background';
import { CameraPush } from '../components/EditorialPrimitives';
import { Layout } from '../components/Layout';
import { ProgressiveText } from '../components/ProgressiveText';
import { fitText } from '../layout';
import { resolveTheme } from '../theme/theme';
import { DataGridProps } from '../types';

export const DataGridTemplate: React.FC<DataGridProps> = ({
  headline,
  items = [],
  columns = 2,
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

  const bgTreatment = renderer_decision?.background_treatment || 'gradient_field';
  const itemCount = Math.max(1, items.length);

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

  // 2 columns desktop, 1 or 2 portrait
  const effectiveCols = isPortrait ? (itemCount <= 3 ? 1 : 2) : (itemCount > 4 ? 3 : 2);
  const gridWidth = width * (isPortrait ? 0.88 : 0.76);
  const gridTop = height * (isPortrait ? 0.24 : 0.32);

  const staggerStep = Math.min(8, Math.round((durationInFrames * 0.5) / itemCount));

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <Background variant={bgTreatment} theme={theme} subtle_motion />

      <CameraPush scaleTo={1.025}>
        {/* Title Zone */}
        <div
          style={{
            position: 'absolute',
            top: Math.round(height * (isPortrait ? 0.10 : 0.14)),
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

        {/* Grid Container */}
        <div
          style={{
            position: 'absolute',
            top: gridTop,
            left: (width - gridWidth) / 2,
            width: gridWidth,
            display: 'grid',
            gridTemplateColumns: `repeat(${effectiveCols}, 1fr)`,
            gap: isPortrait ? 14 : 20,
            zIndex: 5,
          }}
        >
          {items.map((item, index) => {
            const startF = 10 + index * staggerStep;
            const cardSpr = spring({
              frame: Math.max(0, frame - startF),
              fps,
              config: { damping: 15, stiffness: 120 },
            });

            // Count-up calculation
            const countProgress = interpolate(
              frame,
              [startF, startF + 25],
              [0, 1],
              { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
            );

            const displayValueStr = (() => {
              if (item.numeric_value === undefined || item.numeric_value === null || isNaN(item.numeric_value)) {
                return item.value;
              }
              const currentNum = Math.round(countProgress * item.numeric_value);
              const isDollar = item.value.startsWith('$');
              const isPct = item.value.endsWith('%');
              return `${isDollar ? '$' : ''}${currentNum.toLocaleString()}${isPct ? '%' : ''}${item.unit ? ` ${item.unit}` : ''}`;
            })();

            return (
              <div
                key={index}
                style={{
                  padding: isPortrait ? '14px 18px' : '18px 24px',
                  borderRadius: 16,
                  backgroundColor: `${theme.surface}CC`,
                  border: `1.5px solid ${item.highlight ? theme.accent : theme.surfaceBorder}`,
                  boxShadow: item.highlight
                    ? `0 0 24px ${theme.accent}33`
                    : '0 4px 20px rgba(0,0,0,0.25)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                  justifyContent: 'center',
                  opacity: cardSpr,
                  transform: `translateY(${interpolate(cardSpr, [0, 1], [18, 0])}px)`,
                }}
              >
                <span
                  style={{
                    fontSize: isPortrait ? 11 : 13,
                    fontWeight: 800,
                    color: theme.muted,
                    textTransform: 'uppercase',
                    letterSpacing: '0.10em',
                    marginBottom: 4,
                  }}
                >
                  {item.label}
                </span>
                <span
                  style={{
                    fontSize: isPortrait ? 24 : 32,
                    fontWeight: 900,
                    color: item.highlight ? theme.accent : theme.text,
                    letterSpacing: '-0.02em',
                    lineHeight: 1.1,
                  }}
                >
                  {displayValueStr}
                </span>
                {item.subtext && (
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: theme.muted,
                      marginTop: 4,
                    }}
                  >
                    {item.subtext}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </CameraPush>
    </Layout>
  );
};
