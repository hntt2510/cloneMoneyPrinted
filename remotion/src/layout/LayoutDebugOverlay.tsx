import React from 'react';
import { getSafeArea } from './SafeArea';

interface LayoutDebugOverlayProps {
  width: number;
  height: number;
  enabled?: boolean;
}

export const LayoutDebugOverlay: React.FC<LayoutDebugOverlayProps> = ({ width, height, enabled = false }) => {
  if (!enabled) return null;

  const safe = getSafeArea(width, height);

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width,
        height,
        pointerEvents: 'none',
        zIndex: 9999,
        border: '2px solid rgba(239, 68, 68, 0.4)',
      }}
    >
      {/* Safe Area Outer Box */}
      <div
        style={{
          position: 'absolute',
          left: safe.left,
          top: safe.top,
          width: safe.contentWidth,
          height: safe.contentHeight,
          border: '2px dashed rgba(34, 197, 94, 0.7)',
          boxSizing: 'border-box',
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 4,
            left: 6,
            fontSize: 10,
            color: '#22c55e',
            fontWeight: 800,
            letterSpacing: '0.1em',
          }}
        >
          SAFE AREA ({safe.contentWidth}x{safe.contentHeight})
        </span>
      </div>

      {/* Title Zone */}
      <div
        style={{
          position: 'absolute',
          left: safe.titleZone.x,
          top: safe.titleZone.y,
          width: safe.titleZone.width,
          height: safe.titleZone.height,
          border: '1px dotted rgba(59, 130, 246, 0.5)',
          backgroundColor: 'rgba(59, 130, 246, 0.04)',
        }}
      >
        <span style={{ position: 'absolute', bottom: 2, right: 6, fontSize: 9, color: '#3b82f6' }}>
          TITLE ZONE
        </span>
      </div>

      {/* Chart Zone */}
      <div
        style={{
          position: 'absolute',
          left: safe.chartZone.x,
          top: safe.chartZone.y,
          width: safe.chartZone.width,
          height: safe.chartZone.height,
          border: '1px dotted rgba(168, 85, 247, 0.5)',
          backgroundColor: 'rgba(168, 85, 247, 0.04)',
        }}
      >
        <span style={{ position: 'absolute', top: 2, right: 6, fontSize: 9, color: '#a855f7' }}>
          CHART ZONE
        </span>
      </div>
    </div>
  );
};
