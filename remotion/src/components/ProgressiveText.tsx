import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';

export interface ProgressiveTextProps {
  text: string;
  startFrame: number;
  endFrame: number;
  mode?: 'word' | 'phrase';
  color?: string;
  fontSize?: number | string;
  fontWeight?: number | string;
  lineHeight?: number | string;
  letterSpacing?: string;
  textTransform?: 'none' | 'capitalize' | 'uppercase' | 'lowercase';
  textAlign?: 'left' | 'center' | 'right';
  maxWidth?: number | string;
  style?: React.CSSProperties;
  className?: string;
}

/**
 * ProgressiveText reveals text word-by-word or phrase-by-phrase in sync with narration timing.
 * Uses smooth opacity, vertical translation, and blur-to-sharp settling (NO typewriter / NO character ticker).
 */
export const ProgressiveText: React.FC<ProgressiveTextProps> = ({
  text,
  startFrame,
  endFrame,
  mode = 'word',
  color,
  fontSize,
  fontWeight = 800,
  lineHeight,
  letterSpacing = '-0.02em',
  textTransform = 'none',
  textAlign = 'center',
  maxWidth,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (!text || !text.trim()) {
    return null;
  }

  const rawUnits = mode === 'phrase'
    ? text.split(/([,;:]|\s+-\s+)/).map((u) => u.trim()).filter(Boolean)
    : text.trim().split(/\s+/).filter(Boolean);

  const units = rawUnits.length > 0 ? rawUnits : [text.trim()];
  const numUnits = units.length;
  const totalFrames = Math.max(1, endFrame - startFrame);
  const stepFrames = numUnits > 1 ? totalFrames / numUnits : totalFrames;

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: textAlign === 'center' ? 'center' : textAlign === 'right' ? 'flex-end' : 'flex-start',
        alignItems: 'center',
        textAlign,
        color,
        fontSize,
        fontWeight,
        lineHeight,
        letterSpacing,
        textTransform,
        maxWidth,
        ...style,
      }}
    >
      {units.map((unit, idx) => {
        const unitStart = startFrame + Math.round(idx * stepFrames);
        const unitSpr = spring({
          frame: Math.max(0, frame - unitStart),
          fps,
          config: { damping: 15, stiffness: 130 },
        });

        const isVisible = frame >= unitStart;
        const opacity = isVisible ? interpolate(unitSpr, [0, 1], [0, 1]) : 0;
        const translateY = isVisible ? interpolate(unitSpr, [0, 1], [8, 0]) : 8;
        const blurAmount = isVisible ? interpolate(unitSpr, [0, 1], [4, 0]) : 4;
        const filter = blurAmount > 0.1 ? `blur(${blurAmount.toFixed(1)}px)` : 'none';

        return (
          <span
            key={`${unit}-${idx}`}
            style={{
              display: 'inline-block',
              marginRight: idx < numUnits - 1 ? '0.28em' : '0',
              opacity,
              transform: `translateY(${translateY}px)`,
              filter,
              visibility: isVisible ? 'visible' : 'hidden',
              whiteSpace: 'pre',
            }}
          >
            {unit}
          </span>
        );
      })}
    </div>
  );
};
