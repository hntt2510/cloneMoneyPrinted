import { BoundingBox } from './SafeArea';

export interface CollisionItem extends BoundingBox {
  id?: string;
  right?: number;
  bottom?: number;
  priority?: number; // Higher number = higher priority
}

/**
 * Checks whether two bounding boxes intersect, considering an optional safety margin padding.
 */
export function detectCollision(
  boxA: BoundingBox,
  boxB: BoundingBox,
  padding: number = 4
): boolean {
  const aRight = boxA.x + boxA.width + padding;
  const aBottom = boxA.y + boxA.height + padding;
  const aLeft = boxA.x - padding;
  const aTop = boxA.y - padding;

  const bRight = boxB.x + boxB.width + padding;
  const bBottom = boxB.y + boxB.height + padding;
  const bLeft = boxB.x - padding;
  const bTop = boxB.y - padding;

  return !(
    aRight < bLeft ||
    aLeft > bRight ||
    aBottom < bTop ||
    aTop > bBottom
  );
}

/**
 * Clamps a box to remain strictly inside its allocated slot boundaries.
 */
export function clampToSlot(
  box: BoundingBox,
  slotLeft: number,
  slotRight: number,
  padding: number = 4
): BoundingBox {
  const minX = slotLeft + padding;
  const maxX = slotRight - padding - box.width;

  let x = box.x;
  if (maxX >= minX) {
    x = Math.max(minX, Math.min(box.x, maxX));
  } else {
    // Box is wider than slot: center on slot
    x = slotLeft + (slotRight - slotLeft - box.width) / 2;
  }

  return {
    ...box,
    x,
    right: x + box.width,
    bottom: box.y + box.height,
  };
}

/**
 * Shifts a box inward from canvas left and right boundaries if it would overflow.
 */
export function shiftInward(
  box: BoundingBox,
  minLeft: number,
  maxRight: number,
  padding: number = 8
): BoundingBox {
  let x = box.x;
  if (x < minLeft + padding) {
    x = minLeft + padding;
  } else if (x + box.width > maxRight - padding) {
    x = maxRight - padding - box.width;
  }

  return {
    ...box,
    x,
    right: x + box.width,
    bottom: box.y + box.height,
  };
}

/**
 * Resolves vertical positions for a series of horizontal milestones by alternating above and below a central axis.
 */
export function alternateAboveBelow(
  items: Array<{ id: string; x: number; width: number; height: number }>,
  axisY: number,
  aboveOffset: number = 40,
  belowOffset: number = 40
): Array<BoundingBox & { placement: 'above' | 'below' }> {
  return items.map((item, idx) => {
    const isAbove = idx % 2 === 1; // Center item (index 1 in 3 items) or alternate
    const placement: 'above' | 'below' = isAbove ? 'above' : 'below';
    const y = isAbove
      ? axisY - aboveOffset - item.height
      : axisY + belowOffset;

    return {
      id: item.id,
      x: item.x,
      y,
      width: item.width,
      height: item.height,
      right: item.x + item.width,
      bottom: y + item.height,
      placement,
    };
  });
}
