/**
 * Deterministic D3-style Geometry & Scale Functions for Remotion SVG rendering.
 */

export interface LinearScale {
  (value: number): number;
  domain: [number, number];
  range: [number, number];
  ticks: (count?: number) => number[];
}

export function createLinearScale(
  domain: [number, number],
  range: [number, number]
): LinearScale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 === 0 ? 1 : d1 - d0;

  const scale = (val: number): number => {
    const t = (val - d0) / span;
    return r0 + t * (r1 - r0);
  };

  scale.domain = domain;
  scale.range = range;
  scale.ticks = (count: number = 5): number[] => {
    const step = span / count;
    const ticks: number[] = [];
    for (let i = 0; i <= count; i++) {
      ticks.push(d0 + i * step);
    }
    return ticks;
  };

  return scale;
}

export interface BandScale {
  (key: string): number;
  bandwidth: number;
  step: number;
  domain: string[];
  range: [number, number];
}

export function createBandScale(
  domain: string[],
  range: [number, number],
  padding: number = 0.2
): BandScale {
  const [r0, r1] = range;
  const n = domain.length || 1;
  const totalRange = Math.abs(r1 - r0);
  const step = totalRange / (n - padding + 2 * padding);
  const bandwidth = step * (1 - padding);

  const scale = (key: string): number => {
    const idx = domain.indexOf(key);
    if (idx === -1) return r0;
    return r0 + (idx + padding) * step;
  };

  scale.bandwidth = bandwidth;
  scale.step = step;
  scale.domain = domain;
  scale.range = range;

  return scale;
}

export function polarToCartesian(
  cx: number,
  cy: number,
  r: number,
  angleInDegrees: number
): { x: number; y: number } {
  const radians = ((angleInDegrees - 90) * Math.PI) / 180.0;
  return {
    x: cx + r * Math.cos(radians),
    y: cy + r * Math.sin(radians),
  };
}

export function describeArc(
  cx: number,
  cy: number,
  outerR: number,
  startAngle: number,
  endAngle: number,
  innerR: number = 0
): string {
  // Clamp full circles slightly to avoid SVG arc singularity
  const delta = Math.min(359.999, Math.max(0.001, endAngle - startAngle));
  const effectiveEndAngle = startAngle + delta;

  const startOuter = polarToCartesian(cx, cy, outerR, effectiveEndAngle);
  const endOuter = polarToCartesian(cx, cy, outerR, startAngle);
  const largeArcFlag = delta <= 180 ? '0' : '1';

  if (innerR <= 0) {
    return [
      'M',
      startOuter.x,
      startOuter.y,
      'A',
      outerR,
      outerR,
      0,
      largeArcFlag,
      0,
      endOuter.x,
      endOuter.y,
      'L',
      cx,
      cy,
      'Z',
    ].join(' ');
  }

  const startInner = polarToCartesian(cx, cy, innerR, startAngle);
  const endInner = polarToCartesian(cx, cy, innerR, effectiveEndAngle);

  return [
    'M',
    startOuter.x,
    startOuter.y,
    'A',
    outerR,
    outerR,
    0,
    largeArcFlag,
    0,
    endOuter.x,
    endOuter.y,
    'L',
    startInner.x,
    startInner.y,
    'A',
    innerR,
    innerR,
    0,
    largeArcFlag,
    1,
    endInner.x,
    endInner.y,
    'Z',
  ].join(' ');
}

export function generateSmoothPath(points: Array<{ x: number; y: number }>): string {
  if (!points || points.length === 0) return '';
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;

  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i];
    const p1 = points[i + 1];
    const mx = (p0.x + p1.x) / 2;
    d += ` C ${mx} ${p0.y}, ${mx} ${p1.y}, ${p1.x} ${p1.y}`;
  }
  return d;
}
