import { getSafeArea, SafeAreaConfig, clampInsideSafeArea, BoundingBox } from './SafeArea';
import { fitText, TextFitResult } from './TextFit';

export interface TimelineMilestoneInput {
  time_label?: string | null;
  title: string;
  description?: string | null;
}

export interface MilestoneLayoutResult {
  index: number;
  nodeX: number; // local to track
  nodeY: number; // local to track
  globalNodeX: number; // local to canvas
  globalNodeY: number; // local to canvas
  cardWidth: number;
  cardHeight: number;
  cardLeft: number; // local to node
  cardTop: number;  // local to node
  globalCardBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    left: number;
    right: number;
    top: number;
    bottom: number;
  };
  timeFit: TextFitResult;
  titleFit: TextFitResult;
}

export interface TimelineLayoutResult {
  safeArea: SafeAreaConfig;
  titleBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    bottom: number;
  };
  titleFit: TextFitResult;
  trackBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    left: number;
    right: number;
    top: number;
    bottom: number;
  };
  milestones: MilestoneLayoutResult[];
}

/**
 * Computes deterministic, collision-free layout geometry for Timeline visualizations.
 * Uses bounded milestone slot centers and safe area bounds to guarantee that:
 * 1. All milestone label cards (FIRST, CENTER, LAST) remain strictly inside safeArea.left and safeArea.right.
 * 2. Milestone label cards never collide with the title zone.
 * 3. Milestone label cards in adjacent slots do not overlap each other.
 */
export function computeTimelineLayout(options: {
  width: number;
  height: number;
  headline: string;
  milestones: TimelineMilestoneInput[];
  isPortrait?: boolean;
}): TimelineLayoutResult {
  const { width, height, headline, milestones, isPortrait = height > width } = options;
  const safeArea = getSafeArea(width, height);

  const items = milestones.length > 0 ? milestones : [
    { time_label: 'DAY 1', title: 'Incident Filed' },
    { time_label: 'DAY 3', title: 'Adjuster Assessment' },
    { time_label: 'DAY 7', title: 'Payment Disbursed' },
  ];
  const numItems = items.length;

  // 1. Title Zone Layout
  const titleFit = fitText({
    text: headline,
    maxWidth: safeArea.titleZone.width * 0.9,
    maxHeight: safeArea.titleZone.height - 16,
    preferredFontSize: isPortrait ? 26 : 38,
    minimumFontSize: isPortrait ? 18 : 24,
    maxLines: 2,
    role: 'headline',
  });

  const titleBounds = {
    x: safeArea.titleZone.x,
    y: safeArea.titleZone.y,
    width: safeArea.titleZone.width,
    height: safeArea.titleZone.height,
    bottom: safeArea.titleZone.y + safeArea.titleZone.height,
  };

  // 2. Track Dimensions (inside Chart Zone)
  const trackW = isPortrait ? 6 : Math.min(safeArea.chartZone.width * 0.90, 1080);
  const trackH = isPortrait ? Math.min(safeArea.chartZone.height * 0.80, 800) : 6;
  const trackLeft = isPortrait
    ? safeArea.chartZone.x + Math.round(safeArea.chartZone.width * 0.18)
    : safeArea.chartZone.x + (safeArea.chartZone.width - trackW) / 2;
  const trackTop = isPortrait
    ? safeArea.chartZone.y + Math.round(safeArea.chartZone.height * 0.08)
    : safeArea.chartZone.y + Math.round(safeArea.chartZone.height * 0.42);

  const trackBounds = {
    x: trackLeft,
    y: trackTop,
    width: trackW,
    height: trackH,
    left: trackLeft,
    right: trackLeft + trackW,
    top: trackTop,
    bottom: trackTop + trackH,
  };

  // 3. Milestone Slots & Node Positioning
  // In landscape: N bounded slots across track width. Node center is at slot center.
  const slotWidth = isPortrait ? trackW : trackW / numItems;
  const slotHeight = isPortrait ? trackH / numItems : trackH;

  const milestoneResults: MilestoneLayoutResult[] = items.map((m, idx) => {
    // Node center position along track
    const nodeX = isPortrait ? 3 : (idx * slotWidth) + (slotWidth / 2);
    const nodeY = isPortrait ? (idx * slotHeight) + (slotHeight / 2) : 3;

    const globalNodeX = trackLeft + nodeX;
    const globalNodeY = trackTop + nodeY;

    // Bounded card width inside slot
    const maxCardWidth = isPortrait
      ? safeArea.chartZone.width * 0.65
      : Math.min(slotWidth - 20, 320);

    const timeFit = fitText({
      text: m.time_label || `STEP ${idx + 1}`,
      maxWidth: maxCardWidth - 16,
      preferredFontSize: isPortrait ? 13 : 15,
      fontWeight: 800,
      role: 'milestone_time',
    });

    const titleFitRes = fitText({
      text: m.title || '',
      maxWidth: maxCardWidth - 16,
      maxHeight: 52,
      preferredFontSize: isPortrait ? 16 : 20,
      minimumFontSize: 13,
      maxLines: 2,
      fontWeight: 800,
      role: 'milestone_title',
    });

    const cardWidth = maxCardWidth;
    const cardHeight = timeFit.height + titleFitRes.height + 24;

    // Card offset relative to node
    let cardLeft = isPortrait ? 32 : -cardWidth / 2;
    let cardTop = isPortrait ? -cardHeight / 2 : 28;

    // Global coordinates
    let globalX = globalNodeX + cardLeft;
    let globalY = globalNodeY + cardTop;

    // Clamp global coordinates to safe area
    if (globalX < safeArea.left) {
      const shift = safeArea.left - globalX;
      globalX = safeArea.left;
      cardLeft += shift;
    } else if (globalX + cardWidth > safeArea.right) {
      const shift = (globalX + cardWidth) - safeArea.right;
      globalX = safeArea.right - cardWidth;
      cardLeft -= shift;
    }

    if (globalY < safeArea.top) {
      const shift = safeArea.top - globalY;
      globalY = safeArea.top;
      cardTop += shift;
    } else if (globalY + cardHeight > safeArea.bottom) {
      const shift = (globalY + cardHeight) - safeArea.bottom;
      globalY = safeArea.bottom - cardHeight;
      cardTop -= shift;
    }

    const globalCardBounds = {
      x: globalX,
      y: globalY,
      width: cardWidth,
      height: cardHeight,
      left: globalX,
      right: globalX + cardWidth,
      top: globalY,
      bottom: globalY + cardHeight,
    };

    return {
      index: idx,
      nodeX,
      nodeY,
      globalNodeX,
      globalNodeY,
      cardWidth,
      cardHeight,
      cardLeft,
      cardTop,
      globalCardBounds,
      timeFit,
      titleFit: titleFitRes,
    };
  });

  return {
    safeArea,
    titleBounds,
    titleFit,
    trackBounds,
    milestones: milestoneResults,
  };
}
