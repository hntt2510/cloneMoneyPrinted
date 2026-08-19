/**
 * Safe Area and Content Zone partitioning for editorial motion graphics.
 * Guarantees that all essential text, geometry, legends, and milestone nodes
 * remain strictly inside safe content boundaries across all aspect ratios.
 */

export interface ContentZone {
  x: number;
  y: number;
  width: number;
  height: number;
  right: number;
  bottom: number;
}

export interface SafeAreaConfig {
  width: number;
  height: number;
  left: number;
  top: number;
  right: number;
  bottom: number;
  contentWidth: number;
  contentHeight: number;
  isPortrait: boolean;
  aspectRatio: '16:9' | '9:16' | '1:1' | string;
  titleZone: ContentZone;
  chartZone: ContentZone;
  annotationZone: ContentZone;
  footerZone: ContentZone;
}

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
  right?: number;
  bottom?: number;
}

/**
 * Computes canonical safe area and content zone partitions for a given video configuration.
 */
export function getSafeArea(width: number, height: number): SafeAreaConfig {
  const isPortrait = height > width;
  const isSquare = Math.abs(width - height) < 2;
  const aspectRatio = isPortrait ? '9:16' : isSquare ? '1:1' : '16:9';

  // Canonical safe margins: 5% - 7% horizontally, 6% - 8% vertically
  const marginX = isPortrait ? Math.round(width * 0.06) : Math.round(width * 0.055);
  const marginY = isPortrait ? Math.round(height * 0.065) : Math.round(height * 0.06);

  const left = marginX;
  const top = marginY;
  const right = width - marginX;
  const bottom = height - marginY;
  const contentWidth = right - left;
  const contentHeight = bottom - top;

  // Zone Partitioning
  // Title Zone: Top 18-24% of content height
  const titleH = isPortrait ? Math.round(contentHeight * 0.22) : Math.round(contentHeight * 0.20);
  const titleZone: ContentZone = {
    x: left,
    y: top,
    width: contentWidth,
    height: titleH,
    right,
    bottom: top + titleH,
  };

  // Footer / Legend Zone: Bottom 10-15% of content height
  const footerH = isPortrait ? Math.round(contentHeight * 0.15) : Math.round(contentHeight * 0.12);
  const footerZone: ContentZone = {
    x: left,
    y: bottom - footerH,
    width: contentWidth,
    height: footerH,
    right,
    bottom,
  };

  // Chart Zone: Middle 60-70% of content height
  const chartY = top + titleH + Math.round(contentHeight * 0.02);
  const chartH = footerZone.y - chartY - Math.round(contentHeight * 0.02);
  const chartZone: ContentZone = {
    x: left,
    y: chartY,
    width: contentWidth,
    height: Math.max(100, chartH),
    right,
    bottom: chartY + Math.max(100, chartH),
  };

  // Annotation Zone: Overlay area within chartZone and safeArea
  const annotationZone: ContentZone = {
    x: left + Math.round(contentWidth * 0.02),
    y: chartY,
    width: contentWidth * 0.96,
    height: chartH,
    right: right - Math.round(contentWidth * 0.02),
    bottom: chartZone.bottom,
  };

  return {
    width,
    height,
    left,
    top,
    right,
    bottom,
    contentWidth,
    contentHeight,
    isPortrait,
    aspectRatio,
    titleZone,
    chartZone,
    annotationZone,
    footerZone,
  };
}

/**
 * Clamps a box or element coordinates so that it remains strictly inside the safe area.
 */
export function clampInsideSafeArea(
  box: BoundingBox,
  safeArea: SafeAreaConfig,
  padding: number = 0
): BoundingBox {
  const minX = safeArea.left + padding;
  const maxX = safeArea.right - padding - box.width;
  const minY = safeArea.top + padding;
  const maxY = safeArea.bottom - padding - box.height;

  const clampedX = Math.max(minX, Math.min(box.x, maxX));
  const clampedY = Math.max(minY, Math.min(box.y, maxY));

  return {
    x: clampedX,
    y: clampedY,
    width: box.width,
    height: box.height,
  };
}

/**
 * Checks whether a box is completely contained within the safe area.
 */
export function isInsideSafeArea(
  box: BoundingBox,
  safeArea: SafeAreaConfig,
  tolerance: number = 1
): boolean {
  return (
    box.x >= safeArea.left - tolerance &&
    box.y >= safeArea.top - tolerance &&
    box.x + box.width <= safeArea.right + tolerance &&
    box.y + box.height <= safeArea.bottom + tolerance
  );
}
