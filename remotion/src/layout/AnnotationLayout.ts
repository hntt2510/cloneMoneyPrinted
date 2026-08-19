/**
 * Smart annotation positioning and edge-flipping layout engine.
 * Ensures callout annotations, data tags, and leader lines remain inside safe boundaries.
 */

import { SafeAreaConfig } from './SafeArea';

export interface AnnotationPlacement {
  x: number;
  y: number;
  width: number;
  height: number;
  placement: 'top' | 'bottom' | 'left' | 'right' | 'top_right' | 'top_left' | 'bottom_right' | 'bottom_left';
  leaderLine?: {
    startX: number;
    startY: number;
    endX: number;
    endY: number;
  };
}

export interface AnnotationOptions {
  anchorX: number;
  anchorY: number;
  width: number;
  height: number;
  safeArea: SafeAreaConfig;
  preferredPlacement?: 'top' | 'bottom' | 'left' | 'right' | 'top_right' | 'top_left';
  offset?: number;
}

export function computeAnnotationLayout(options: AnnotationOptions): AnnotationPlacement {
  const { anchorX, anchorY, width, height, safeArea, preferredPlacement = 'top', offset = 16 } = options;

  let placement = preferredPlacement;
  let targetX = anchorX;
  let targetY = anchorY;

  // Horizontal check and flip
  if (placement.includes('right') || placement === 'right') {
    if (anchorX + offset + width > safeArea.right) {
      // Flip to left
      placement = placement.replace('right', 'left') as any;
    }
  } else if (placement.includes('left') || placement === 'left') {
    if (anchorX - offset - width < safeArea.left) {
      // Flip to right
      placement = placement.replace('left', 'right') as any;
    }
  }

  // Vertical check and flip
  if (placement.includes('top') || placement === 'top') {
    if (anchorY - offset - height < safeArea.top) {
      // Flip to bottom
      placement = placement.replace('top', 'bottom') as any;
    }
  } else if (placement.includes('bottom') || placement === 'bottom') {
    if (anchorY + offset + height > safeArea.bottom) {
      // Flip to top
      placement = placement.replace('bottom', 'top') as any;
    }
  }

  // Resolve final coordinates
  switch (placement) {
    case 'top':
      targetX = anchorX - width / 2;
      targetY = anchorY - offset - height;
      break;
    case 'bottom':
      targetX = anchorX - width / 2;
      targetY = anchorY + offset;
      break;
    case 'left':
      targetX = anchorX - offset - width;
      targetY = anchorY - height / 2;
      break;
    case 'right':
      targetX = anchorX + offset;
      targetY = anchorY - height / 2;
      break;
    case 'top_right':
      targetX = anchorX + offset;
      targetY = anchorY - offset - height;
      break;
    case 'top_left':
      targetX = anchorX - offset - width;
      targetY = anchorY - offset - height;
      break;
    default:
      targetX = anchorX - width / 2;
      targetY = anchorY - offset - height;
      break;
  }

  // Final hard clamp within safe area
  targetX = Math.max(safeArea.left, Math.min(targetX, safeArea.right - width));
  targetY = Math.max(safeArea.top, Math.min(targetY, safeArea.bottom - height));

  return {
    x: targetX,
    y: targetY,
    width,
    height,
    placement: placement as any,
    leaderLine: {
      startX: anchorX,
      startY: anchorY,
      endX: targetX + width / 2,
      endY: targetY + (placement.includes('top') ? height : 0),
    },
  };
}
