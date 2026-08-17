import React from 'react';
import { interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion';
import { Layout } from '../components/Layout';
import { resolveTheme } from '../theme/theme';
import { TextProps, Theme } from '../types';

export const TextTemplate: React.FC<TextProps> = ({
  headline,
  subheadline,
  style_variant = 'bold',
  theme: customTheme,
  isGrouped = false,
  isFirstInGroup = true,
  animation_plan,
}) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const theme = resolveTheme(customTheme);
  const isPortrait = height > width;

  const isContinuous = isGrouped && !isFirstInGroup;

  const spr = spring({
    frame: isContinuous ? 100 : frame,
    fps,
    config: { damping: 13, stiffness: 95, mass: 0.8 },
  });

  const titleOpacity = isContinuous ? 1 : interpolate(spr, [0, 1], [0, 1]);
  const titleScale = isContinuous ? 1 : interpolate(spr, [0, 1], [0.9, 1]);
  const titleTranslateY = isContinuous ? 0 : interpolate(spr, [0, 1], [24, 0]);

  const lineSpr = spring({
    frame: Math.max(0, (isContinuous ? 100 : frame) - 6),
    fps,
    config: { damping: 14, stiffness: 90, mass: 0.9 },
  });
  const lineWidthPct = isContinuous ? 100 : interpolate(lineSpr, [0, 1], [0, 100]);

  const fontSize = isPortrait ? width * 0.095 : width * 0.058;
  const subFontSize = fontSize * 0.45;

  return (
    <Layout theme={theme} isGrouped={isGrouped}>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          textAlign: 'center',
          maxWidth: '90%',
          opacity: titleOpacity,
          transform: `scale(${titleScale}) translateY(${titleTranslateY}px)`,
        }}
      >
        <h1
          style={{
            margin: 0,
            fontSize: Math.min(96, Math.max(36, Math.round(fontSize))),
            fontWeight: 900,
            color: theme.text,
            letterSpacing: '-0.03em',
            lineHeight: 1.15,
            textTransform: 'uppercase',
            wordBreak: 'break-word',
          }}
        >
          {animation_plan?.beats && animation_plan.beats.length > 1 ? (
            animation_plan.beats.map((beat, i) => {
              const isActive = frame >= beat.start_frame;
              const emphasisSpring = spring({
                frame: Math.max(0, frame - beat.start_frame),
                fps,
                config: { damping: 10, stiffness: 100 },
              });
              const s = beat.emphasis ? 1 + interpolate(emphasisSpring, [0, 1], [0, 0.1]) : 1;
              return (
                <span
                  key={beat.id}
                  style={{
                    opacity: isActive ? 1 : 0.1,
                    display: 'inline-block',
                    marginRight: '0.25em',
                    transform: `scale(${isActive ? s : 1})`,
                    color: beat.emphasis ? theme.accent : theme.text,
                    transition: 'opacity 0.2s',
                  }}
                >
                  {beat.text}
                </span>
              );
            })
          ) : (
            headline
          )}
        </h1>

        {/* Accent Underline */}
        <div
          style={{
            width: `${lineWidthPct * 0.4}%`,
            height: 6,
            backgroundColor: theme.accent,
            borderRadius: 3,
            marginTop: 20,
            marginBottom: subheadline ? 20 : 0,
            boxShadow: `0 0 16px ${theme.accent}80`,
          }}
        />

        {subheadline && (
          <p
            style={{
              margin: 0,
              fontSize: Math.min(42, Math.max(20, Math.round(subFontSize))),
              fontWeight: 600,
              color: theme.muted,
              lineHeight: 1.35,
              maxWidth: '85%',
            }}
          >
            {subheadline}
          </p>
        )}
      </div>
    </Layout>
  );
};
