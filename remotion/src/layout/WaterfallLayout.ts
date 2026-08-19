import { getSafeArea, SafeAreaConfig, clampInsideSafeArea } from './SafeArea';
import { fitText, TextFitResult } from './TextFit';
import { SEMANTIC_COLORS } from './ColorSystem';

export interface WaterfallStepInput {
  label: string;
  delta: number;
  display_value?: string | null;
}

export interface WaterfallColumnBounds {
  x: number;
  y: number;
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface WaterfallColumnResult {
  type: 'start' | 'step' | 'final';
  index: number;
  label: string;
  value: number;
  delta?: number;
  displayValue: string;
  color: string;
  isPositive?: boolean;
  barBounds: WaterfallColumnBounds;
  valueBounds: WaterfallColumnBounds;
  labelBounds: WaterfallColumnBounds;
  globalBounds: WaterfallColumnBounds;
}

export interface WaterfallLayoutResult {
  safeArea: SafeAreaConfig;
  titleBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    bottom: number;
  };
  titleFit: TextFitResult;
  chartContainerBounds: {
    x: number;
    y: number;
    width: number;
    height: number;
    left: number;
    right: number;
    top: number;
    bottom: number;
  };
  columns: WaterfallColumnResult[];
  connectors: Array<{ startX: number; startY: number; endX: number; endY: number }>;
}

export function computeWaterfallLayout(options: {
  width: number;
  height: number;
  headline: string;
  startValue?: number;
  startLabel?: string;
  steps?: WaterfallStepInput[];
  endValue?: number;
  endLabel?: string;
  isPortrait?: boolean;
}): WaterfallLayoutResult {
  const {
    width,
    height,
    headline,
    startValue = 100,
    startLabel = 'Base Quote',
    steps = [
      { label: 'State Filing Fee', delta: 30, display_value: '+$30' },
      { label: 'Safe Driver Discount', delta: -20, display_value: '-$20' },
    ],
    endValue = 110,
    endLabel = 'Final Premium',
    isPortrait = height > width,
  } = options;

  const safeArea = getSafeArea(width, height);

  // 1. Cumulative math
  let currentRunning = startValue;
  const computedSteps = steps.map((stp) => {
    const prev = currentRunning;
    const delta = Number(stp.delta) || 0;
    currentRunning += delta;
    return {
      ...stp,
      prevLevel: prev,
      delta,
      newLevel: currentRunning,
      isPositive: delta >= 0,
    };
  });

  const allLevels = [
    0,
    startValue,
    endValue,
    ...computedSteps.map((s) => s.prevLevel),
    ...computedSteps.map((s) => s.newLevel),
  ];
  const maxLevel = Math.max(...allLevels, 10);
  const minLevel = Math.min(0, ...allLevels);
  const range = maxLevel - minLevel || 1;

  const totalCols = 2 + computedSteps.length;

  // 2. Title Zone
  const titleFit = fitText({
    text: headline,
    maxWidth: safeArea.titleZone.width * 0.9,
    maxHeight: safeArea.titleZone.height - 16,
    preferredFontSize: isPortrait ? 24 : 36,
    minimumFontSize: isPortrait ? 18 : 22,
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

  // 3. Chart Container Bounds
  const chartW = isPortrait
    ? safeArea.chartZone.width * 0.94
    : Math.min(safeArea.chartZone.width * 0.88, 960);
  const chartH = isPortrait
    ? safeArea.chartZone.height * 0.62
    : safeArea.chartZone.height * 0.68;
  const chartLeft = safeArea.chartZone.x + (safeArea.chartZone.width - chartW) / 2;
  const chartTop = safeArea.chartZone.y + Math.round(safeArea.chartZone.height * 0.05);

  const chartContainerBounds = {
    x: chartLeft,
    y: chartTop,
    width: chartW,
    height: chartH,
    left: chartLeft,
    right: chartLeft + chartW,
    top: chartTop,
    bottom: chartTop + chartH,
  };

  const plotPaddingX = isPortrait ? 20 : 36;
  const plotPaddingBottom = isPortrait ? 48 : 58;
  const plotPaddingTop = isPortrait ? 32 : 40;
  const plotW = chartW - plotPaddingX * 2;
  const plotH = chartH - plotPaddingBottom - plotPaddingTop;

  const colWidth = Math.min(plotW / (totalCols * 1.35), isPortrait ? 60 : 100);
  const colGap = (plotW - totalCols * colWidth) / Math.max(1, totalCols - 1);

  const levelToY = (level: number) => ((level - minLevel) / range) * plotH;

  const columns: WaterfallColumnResult[] = [];
  const connectors: Array<{ startX: number; startY: number; endX: number; endY: number }> = [];

  // 4. Start Column (Index 0)
  {
    const colLeft = chartLeft + plotPaddingX;
    const barH = levelToY(startValue);
    const barTop = chartTop + chartH - plotPaddingBottom - barH;
    const barBottom = chartTop + chartH - plotPaddingBottom;

    const valFit = fitText({
      text: `$${startValue.toLocaleString()}`,
      maxWidth: colWidth * 1.5,
      preferredFontSize: isPortrait ? 13 : 15,
      fontWeight: 900,
      role: 'hero_value',
    });

    const lblFit = fitText({
      text: startLabel,
      maxWidth: Math.max(colWidth * 1.2, 100),
      preferredFontSize: isPortrait ? 11 : 13,
      fontWeight: 800,
      role: 'chart_label',
    });

    const valWidth = colWidth * 1.4;
    const valHeight = 20;
    const valX = colLeft + (colWidth - valWidth) / 2;
    const valY = barTop - valHeight - 4;

    const lblWidth = Math.max(colWidth * 1.2, 100);
    const lblHeight = lblFit.height;
    const lblX = colLeft + (colWidth - lblWidth) / 2;
    const lblY = barBottom + 8;

    columns.push({
      type: 'start',
      index: 0,
      label: startLabel,
      value: startValue,
      displayValue: `$${startValue.toLocaleString()}`,
      color: SEMANTIC_COLORS.waterfall.start,
      barBounds: {
        x: colLeft,
        y: barTop,
        width: colWidth,
        height: barH,
        left: colLeft,
        right: colLeft + colWidth,
        top: barTop,
        bottom: barBottom,
      },
      valueBounds: {
        x: valX,
        y: valY,
        width: valWidth,
        height: valHeight,
        left: valX,
        right: valX + valWidth,
        top: valY,
        bottom: valY + valHeight,
      },
      labelBounds: {
        x: lblX,
        y: lblY,
        width: lblWidth,
        height: lblHeight,
        left: lblX,
        right: lblX + lblWidth,
        top: lblY,
        bottom: lblY + lblHeight,
      },
      globalBounds: {
        x: Math.min(colLeft, valX, lblX),
        y: valY,
        width: Math.max(colWidth, valWidth, lblWidth),
        height: (lblY + lblHeight) - valY,
        left: Math.min(colLeft, valX, lblX),
        right: Math.max(colLeft + colWidth, valX + valWidth, lblX + lblWidth),
        top: valY,
        bottom: lblY + lblHeight,
      },
    });

    // Connector to step 1
    connectors.push({
      startX: colLeft + colWidth,
      startY: barTop,
      endX: colLeft + colWidth + colGap,
      endY: barTop,
    });
  }

  // 5. Delta Step Columns
  computedSteps.forEach((step, idx) => {
    const colIndex = idx + 1;
    const colLeft = chartLeft + plotPaddingX + colIndex * (colWidth + colGap);
    const lowerVal = Math.min(step.prevLevel, step.newLevel);
    const higherVal = Math.max(step.prevLevel, step.newLevel);
    const deltaH = (Math.abs(step.delta) / range) * plotH;
    const barTop = chartTop + chartH - plotPaddingBottom - levelToY(higherVal);
    const barBottom = chartTop + chartH - plotPaddingBottom - levelToY(lowerVal);
    const barColor = step.isPositive
      ? SEMANTIC_COLORS.waterfall.positive
      : SEMANTIC_COLORS.waterfall.negative;

    const valFit = fitText({
      text: step.display_value || `${step.isPositive ? '+' : ''}$${Math.abs(step.delta)}`,
      maxWidth: colWidth * 1.4,
      preferredFontSize: isPortrait ? 12 : 14,
      fontWeight: 900,
      role: 'hero_value',
    });

    const lblFit = fitText({
      text: step.label,
      maxWidth: Math.max(colWidth * 1.25, 90),
      preferredFontSize: isPortrait ? 10 : 12,
      fontWeight: 800,
      role: 'chart_label',
    });

    const valWidth = colWidth * 1.4;
    const valHeight = 20;
    const valX = colLeft + (colWidth - valWidth) / 2;
    const valY = barTop - valHeight - 4;

    const lblWidth = Math.max(colWidth * 1.25, 90);
    const lblHeight = lblFit.height;
    const lblX = colLeft + (colWidth - lblWidth) / 2;
    const lblY = chartTop + chartH - plotPaddingBottom + 8;

    columns.push({
      type: 'step',
      index: colIndex,
      label: step.label,
      value: step.newLevel,
      delta: step.delta,
      isPositive: step.isPositive,
      displayValue: step.display_value || `${step.isPositive ? '+' : ''}$${Math.abs(step.delta)}`,
      color: barColor,
      barBounds: {
        x: colLeft,
        y: barTop,
        width: colWidth,
        height: deltaH,
        left: colLeft,
        right: colLeft + colWidth,
        top: barTop,
        bottom: barBottom,
      },
      valueBounds: {
        x: valX,
        y: valY,
        width: valWidth,
        height: valHeight,
        left: valX,
        right: valX + valWidth,
        top: valY,
        bottom: valY + valHeight,
      },
      labelBounds: {
        x: lblX,
        y: lblY,
        width: lblWidth,
        height: lblHeight,
        left: lblX,
        right: lblX + lblWidth,
        top: lblY,
        bottom: lblY + lblHeight,
      },
      globalBounds: {
        x: Math.min(colLeft, valX, lblX),
        y: valY,
        width: Math.max(colWidth, valWidth, lblWidth),
        height: (lblY + lblHeight) - valY,
        left: Math.min(colLeft, valX, lblX),
        right: Math.max(colLeft + colWidth, valX + valWidth, lblX + lblWidth),
        top: valY,
        bottom: lblY + lblHeight,
      },
    });

    // Connector to next column
    const nextY = step.isPositive ? barTop : barBottom;
    connectors.push({
      startX: colLeft + colWidth,
      startY: nextY,
      endX: colLeft + colWidth + colGap,
      endY: nextY,
    });
  });

  // 6. Final Total Column
  {
    const finalIndex = totalCols - 1;
    const colLeft = chartLeft + plotPaddingX + finalIndex * (colWidth + colGap);
    const barH = levelToY(endValue);
    const barTop = chartTop + chartH - plotPaddingBottom - barH;
    const barBottom = chartTop + chartH - plotPaddingBottom;

    const valFit = fitText({
      text: `$${endValue.toLocaleString()}`,
      maxWidth: colWidth * 1.4,
      preferredFontSize: isPortrait ? 13 : 15,
      fontWeight: 900,
      role: 'hero_value',
    });

    const lblFit = fitText({
      text: endLabel,
      maxWidth: Math.max(colWidth * 1.2, 100),
      preferredFontSize: isPortrait ? 11 : 13,
      fontWeight: 800,
      role: 'chart_label',
    });

    const valWidth = colWidth * 1.4;
    const valHeight = 20;
    let valX = colLeft + (colWidth - valWidth) / 2;
    const valY = barTop - valHeight - 4;

    const lblWidth = Math.max(colWidth * 1.2, 100);
    const lblHeight = lblFit.height;
    let lblX = colLeft + (colWidth - lblWidth) / 2;
    const lblY = barBottom + 8;

    // Hard clamp final bounds inside safe area right edge
    if (valX + valWidth > safeArea.right) {
      valX = safeArea.right - valWidth;
    }
    if (lblX + lblWidth > safeArea.right) {
      lblX = safeArea.right - lblWidth;
    }

    columns.push({
      type: 'final',
      index: finalIndex,
      label: endLabel,
      value: endValue,
      displayValue: `$${endValue.toLocaleString()}`,
      color: SEMANTIC_COLORS.waterfall.final,
      barBounds: {
        x: colLeft,
        y: barTop,
        width: colWidth,
        height: barH,
        left: colLeft,
        right: colLeft + colWidth,
        top: barTop,
        bottom: barBottom,
      },
      valueBounds: {
        x: valX,
        y: valY,
        width: valWidth,
        height: valHeight,
        left: valX,
        right: valX + valWidth,
        top: valY,
        bottom: valY + valHeight,
      },
      labelBounds: {
        x: lblX,
        y: lblY,
        width: lblWidth,
        height: lblHeight,
        left: lblX,
        right: lblX + lblWidth,
        top: lblY,
        bottom: lblY + lblHeight,
      },
      globalBounds: {
        x: Math.min(colLeft, valX, lblX),
        y: valY,
        width: Math.max(colWidth, valWidth, lblWidth),
        height: (lblY + lblHeight) - valY,
        left: Math.min(colLeft, valX, lblX),
        right: Math.max(colLeft + colWidth, valX + valWidth, lblX + lblWidth),
        top: valY,
        bottom: lblY + lblHeight,
      },
    });
  }

  return {
    safeArea,
    titleBounds,
    titleFit,
    chartContainerBounds,
    columns,
    connectors,
  };
}
