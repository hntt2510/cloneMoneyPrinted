/**
 * Responsive layout and aspect-ratio adaptation engine.
 */

export interface ResponsiveConfig {
  width: number;
  height: number;
  isPortrait: boolean;
  isLandscape: boolean;
  isSquare: boolean;
  aspectRatio: '16:9' | '9:16' | '1:1' | string;
  fontScale: number;
  spacingScale: number;
  orientation: 'horizontal' | 'vertical';
  maxContentWidth: number;
  cardPadding: { x: number; y: number };
}

export function getResponsiveConfig(width: number, height: number): ResponsiveConfig {
  const isPortrait = height > width;
  const isSquare = Math.abs(width - height) < 4;
  const isLandscape = !isPortrait && !isSquare;
  const aspectRatio = isPortrait ? '9:16' : isSquare ? '1:1' : '16:9';

  const fontScale = isPortrait ? 0.85 : width >= 1920 ? 1.0 : 0.9;
  const spacingScale = isPortrait ? 0.75 : 1.0;
  const orientation = isPortrait ? 'vertical' : 'horizontal';
  const maxContentWidth = isPortrait ? Math.round(width * 0.90) : Math.min(Math.round(width * 0.85), 1200);

  const cardPadding = {
    x: isPortrait ? Math.round(width * 0.04) : Math.round(width * 0.035),
    y: isPortrait ? Math.round(height * 0.03) : Math.round(height * 0.035),
  };

  return {
    width,
    height,
    isPortrait,
    isLandscape,
    isSquare,
    aspectRatio,
    fontScale,
    spacingScale,
    orientation,
    maxContentWidth,
    cardPadding,
  };
}
