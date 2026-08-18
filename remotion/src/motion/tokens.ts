import { SpringConfig } from 'remotion';

export const SPRING_CONFIGS = {
  SNAP: { damping: 20, stiffness: 300 } as SpringConfig,
  FAST: { damping: 14, stiffness: 180, mass: 0.7 } as SpringConfig,
  NORMAL: { damping: 14, stiffness: 90, mass: 0.9 } as SpringConfig,
  SLOW: { damping: 16, stiffness: 50, mass: 1.2 } as SpringConfig,
  BOUNCE: { damping: 8, stiffness: 120, mass: 0.6 } as SpringConfig,
};

export const MOTION_ENERGY = {
  subtle:    { springMult: 0.6, distMult: 0.5, accentInt: 0.6 },
  standard:  { springMult: 1.0, distMult: 1.0, accentInt: 1.0 },
  energetic: { springMult: 1.4, distMult: 1.5, accentInt: 1.3 },
};

export const FINAL_HOLD_RATIO = 0.1; // Reserve 10% of scene duration for hold
