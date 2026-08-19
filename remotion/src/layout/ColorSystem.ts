/**
 * Deterministic Categorical and Semantic Color System for editorial motion graphics.
 * Guarantees distinct perceptual color distance, zero rainbow noise, and voice-synced highlighting.
 */

import { MotionAnimationPlan } from '../types';

export const CATEGORICAL_PALETTE = [
  '#3B82F6', // 0: Vibrant Blue
  '#2DD4BF', // 1: Crisp Teal
  '#FB923C', // 2: Warm Orange
  '#A78BFA', // 3: Soft Purple
  '#34D399', // 4: Emerald Green
  '#FBBF24', // 5: Golden Amber
  '#F472B6', // 6: Rose Pink
  '#38BDF8', // 7: Sky Blue
];

export const SEMANTIC_COLORS = {
  waterfall: {
    start: '#3B82F6',
    positive: '#10B981',
    negative: '#EF4444',
    final: '#8B5CF6',
    connector: 'rgba(255, 255, 255, 0.25)',
  },
  threshold: {
    safe: '#10B981',
    warning: '#F59E0B',
    danger: '#EF4444',
    limitMarker: '#60A5FA',
  },
  gauge: {
    progress: '#2DD4BF',
    risk: '#EF4444',
    neutral: '#3B82F6',
  },
  beforeAfter: {
    before: '#94A3B8',
    after: '#60A5FA',
  },
};

/**
 * Standard category dictionary for consistent cross-scene and cross-template color identity.
 */
const STANDARD_LABEL_COLOR_MAP: Record<string, string> = {
  // Plan Tiers
  PREMIUM: '#3B82F6',
  STANDARD: '#2DD4BF',
  BASIC: '#FB923C',
  ENTERPRISE: '#A78BFA',
  PRO: '#3B82F6',
  FREE: '#94A3B8',

  // Insurance Coverages
  COMPREHENSIVE: '#3B82F6',
  'COLLISION ONLY': '#2DD4BF',
  COLLISION: '#2DD4BF',
  LIABILITY: '#A78BFA',
  UNINSURED: '#FB923C',

  // Comparison items
  'PLAN A': '#3B82F6',
  'PLAN B': '#2DD4BF',
  'PLAN C': '#FB923C',
  'PLAN D': '#A78BFA',

  // Ranked Claims
  'REAR-END COLLISIONS': '#3B82F6',
  'INTERSECTION T-BONES': '#2DD4BF',
  'SINGLE-VEHICLE RUNOFF': '#FB923C',
  'PARKING LOT SCRAPES': '#A78BFA',
};

/**
 * Curated palette indices for small category sets (2 to 5 items) to maximize perceptual separation.
 */
const PALETTE_DISTRIBUTION_MAP: Record<number, number[]> = {
  2: [0, 2],       // Blue, Orange
  3: [0, 1, 2],    // Blue, Teal, Orange
  4: [0, 1, 2, 3], // Blue, Teal, Orange, Purple
  5: [0, 1, 5, 3, 4], // Blue, Teal, Amber, Purple, Emerald
};

export interface ResolveCategoryColorOptions {
  label?: string | null;
  index: number;
  totalCategories?: number;
  semanticRole?: 'positive' | 'negative' | 'start' | 'final' | 'threshold' | 'neutral';
}

/**
 * Resolves a categorical color deterministically with high perceptual distance.
 */
export function resolveCategoryColor(options: ResolveCategoryColorOptions): string {
  const { label, index, totalCategories = 3, semanticRole } = options;

  // 1. Semantic override if explicitly specified
  if (semanticRole === 'positive') return SEMANTIC_COLORS.waterfall.positive;
  if (semanticRole === 'negative') return SEMANTIC_COLORS.waterfall.negative;
  if (semanticRole === 'start') return SEMANTIC_COLORS.waterfall.start;
  if (semanticRole === 'final') return SEMANTIC_COLORS.waterfall.final;

  // 2. Recognized dictionary label mapping
  if (label) {
    const norm = label.trim().toUpperCase();
    if (STANDARD_LABEL_COLOR_MAP[norm]) {
      return STANDARD_LABEL_COLOR_MAP[norm];
    }
  }

  // 3. Spaced palette selection
  const dist = PALETTE_DISTRIBUTION_MAP[totalCategories];
  if (dist && index < dist.length) {
    return CATEGORICAL_PALETTE[dist[index]];
  }

  return CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length];
}

export interface ItemFocusState {
  isActive: boolean;
  isPast: boolean;
  isSettled: boolean;
  opacity: number;
  scale: number;
  glowIntensity: number;
  isMuted: boolean;
}

/**
 * Calculates voice-synced active focus and settlement states for items in a sequence.
 */
export function getItemFocusState(
  itemIndex: number,
  frame: number,
  durationInFrames: number,
  animationPlan?: MotionAnimationPlan | null,
  totalItems: number = 3
): ItemFocusState {
  const finalHoldStart = Math.round(durationInFrames * 0.82);
  const isSettled = frame >= finalHoldStart;

  // Check if explicit kinetic beats exist
  if (animationPlan?.beats && animationPlan.beats.length > 0) {
    const itemBeats = animationPlan.beats.filter(
      (b) =>
        b.data_ref === `slice_${itemIndex}` ||
        b.data_ref === `bar_${itemIndex}` ||
        b.data_ref === `m_${itemIndex}` ||
        b.data_ref === `step_${itemIndex}` ||
        b.data_ref === `item_${itemIndex}`
    );

    if (itemBeats.length > 0) {
      const activeBeat = itemBeats.find((b) => frame >= b.start_frame && frame < b.end_frame);
      const isPast = frame >= itemBeats[itemBeats.length - 1].end_frame;
      const isActive = Boolean(activeBeat);

      if (isSettled) {
        return {
          isActive: false,
          isPast: true,
          isSettled: true,
          opacity: 1.0,
          scale: 1.0,
          glowIntensity: 0.0,
          isMuted: false,
        };
      }

      if (isActive) {
        return {
          isActive: true,
          isPast: false,
          isSettled: false,
          opacity: 1.0,
          scale: 1.05,
          glowIntensity: 0.8,
          isMuted: false,
        };
      }

      return {
        isActive: false,
        isPast,
        isSettled: false,
        opacity: isPast ? 0.78 : 0.45,
        scale: 1.0,
        glowIntensity: 0.0,
        isMuted: true,
      };
    }
  }

  // Deterministic intra-cue distribution fallback
  const introFrames = Math.round(durationInFrames * 0.15);
  const activeDuration = finalHoldStart - introFrames;
  const itemSlotFrames = Math.max(8, Math.floor(activeDuration / Math.max(1, totalItems)));

  const itemStart = introFrames + itemIndex * itemSlotFrames;
  const itemEnd = itemStart + itemSlotFrames;

  if (isSettled) {
    return {
      isActive: false,
      isPast: true,
      isSettled: true,
      opacity: 1.0,
      scale: 1.0,
      glowIntensity: 0.0,
      isMuted: false,
    };
  }

  const isActive = frame >= itemStart && frame < itemEnd;
  const isPast = frame >= itemEnd;

  return {
    isActive,
    isPast,
    isSettled: false,
    opacity: isActive ? 1.0 : isPast ? 0.78 : 0.45,
    scale: isActive ? 1.04 : 1.0,
    glowIntensity: isActive ? 0.6 : 0.0,
    isMuted: !isActive,
  };
}
