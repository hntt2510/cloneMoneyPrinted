/**
 * Deterministic text-fitting and wrapping engine for editorial motion graphics.
 * Calculates optimal font size and line wrapping without DOM thrashing.
 */

export interface TextFitOptions {
  text: string;
  maxWidth: number;
  maxHeight?: number;
  preferredFontSize?: number;
  minimumFontSize?: number;
  maxLines?: number;
  lineHeightRatio?: number;
  fontWeight?: number | string;
  letterSpacing?: number;
  role?:
    | 'headline'
    | 'eyebrow'
    | 'hero_value'
    | 'chart_label'
    | 'milestone_title'
    | 'milestone_time'
    | 'annotation'
    | 'axis_label'
    | 'supporting_text';
}

export interface TextFitResult {
  fontSize: number;
  lineHeight: number;
  lines: string[];
  text: string;
  width: number;
  height: number;
  isTruncated: boolean;
  isCompact: boolean;
}

/**
 * Estimates width of a single character for typical sans-serif fonts
 * based on typographic character width classifications.
 */
function getCharWidthFactor(char: string, fontWeight: number | string = 700): number {
  const isHeavy = Number(fontWeight) >= 700 || fontWeight === 'bold';
  const multiplier = isHeavy ? 1.08 : 1.0;

  if (/[WMwm@#%&]/.test(char)) return 0.78 * multiplier;
  if (/[ABCDEFGHJKLNOPQRSTUVXYZ0-9$]/.test(char)) return 0.58 * multiplier;
  if (/[abcdeghknopquvxyz]/.test(char)) return 0.50 * multiplier;
  if (/[frst]/.test(char)) return 0.35 * multiplier;
  if (/[ijlI.,:;!'| ]/.test(char)) return 0.26 * multiplier;
  return 0.52 * multiplier;
}

/**
 * Measures the approximate pixel width of a string at a given font size.
 */
export function estimateTextWidth(
  text: string,
  fontSize: number,
  fontWeight: number | string = 700,
  letterSpacing: number = -0.02
): number {
  let rawWidth = 0;
  for (let i = 0; i < text.length; i++) {
    rawWidth += getCharWidthFactor(text[i], fontWeight) * fontSize;
  }
  const spacingAdd = text.length * (letterSpacing * fontSize);
  return Math.max(0, Math.round(rawWidth + spacingAdd));
}

/**
 * Wraps text into lines that fit within maxWidth at a given font size.
 */
export function wrapText(
  text: string,
  maxWidth: number,
  fontSize: number,
  fontWeight: number | string = 700
): { lines: string[]; longestLineWidth: number } {
  const words = text.trim().split(/\s+/);
  if (words.length === 0 || text.trim() === '') {
    return { lines: [''], longestLineWidth: 0 };
  }

  const lines: string[] = [];
  let currentLine = words[0];
  let longestLineWidth = estimateTextWidth(currentLine, fontSize, fontWeight);

  for (let i = 1; i < words.length; i++) {
    const word = words[i];
    const testLine = `${currentLine} ${word}`;
    const testWidth = estimateTextWidth(testLine, fontSize, fontWeight);

    if (testWidth <= maxWidth) {
      currentLine = testLine;
      if (testWidth > longestLineWidth) {
        longestLineWidth = testWidth;
      }
    } else {
      lines.push(currentLine);
      currentLine = word;
      const wordWidth = estimateTextWidth(word, fontSize, fontWeight);
      if (wordWidth > longestLineWidth) {
        longestLineWidth = wordWidth;
      }
    }
  }
  lines.push(currentLine);

  return { lines, longestLineWidth };
}

/**
 * Deterministically computes the best font size, line wrapping, and dimensions
 * to fit text comfortably within maxWidth and maxHeight constraints.
 */
export function fitText(options: TextFitOptions): TextFitResult {
  const text = (options.text || '').trim();
  const maxWidth = Math.max(40, options.maxWidth);
  const maxHeight = options.maxHeight ? Math.max(20, options.maxHeight) : 99999;
  const preferredSize = options.preferredFontSize || (options.role === 'headline' ? 36 : 18);
  const minSize = options.minimumFontSize || Math.max(10, Math.round(preferredSize * 0.55));
  const maxLines = options.maxLines || (options.role === 'headline' ? 2 : options.role === 'eyebrow' ? 1 : 3);
  const lineRatio = options.lineHeightRatio || (options.role === 'headline' ? 1.18 : 1.3);
  const fontWeight = options.fontWeight || (options.role === 'headline' ? 800 : 700);

  let currentSize = preferredSize;
  let bestResult: TextFitResult | null = null;

  while (currentSize >= minSize) {
    const { lines, longestLineWidth } = wrapText(text, maxWidth, currentSize, fontWeight);
    const lineHeight = Math.round(currentSize * lineRatio);
    const totalHeight = lines.length * lineHeight;

    const fitsWidth = longestLineWidth <= maxWidth;
    const fitsHeight = totalHeight <= maxHeight;
    const fitsLines = lines.length <= maxLines;

    if (fitsWidth && fitsHeight && fitsLines) {
      bestResult = {
        fontSize: currentSize,
        lineHeight,
        lines,
        text: lines.join('\n'),
        width: longestLineWidth,
        height: totalHeight,
        isTruncated: false,
        isCompact: currentSize < preferredSize,
      };
      break;
    }

    // Step down by 1px
    currentSize -= 1;
  }

  if (!bestResult) {
    // Force fit at minimum font size, truncating or squeezing if necessary
    const { lines, longestLineWidth } = wrapText(text, maxWidth, minSize, fontWeight);
    const cappedLines = lines.slice(0, maxLines);
    if (lines.length > maxLines && cappedLines.length > 0) {
      const last = cappedLines[cappedLines.length - 1];
      cappedLines[cappedLines.length - 1] = last.length > 3 ? `${last.slice(0, -3)}...` : '...';
    }
    const lineHeight = Math.round(minSize * lineRatio);
    bestResult = {
      fontSize: minSize,
      lineHeight,
      lines: cappedLines,
      text: cappedLines.join('\n'),
      width: Math.min(maxWidth, longestLineWidth),
      height: cappedLines.length * lineHeight,
      isTruncated: lines.length > maxLines,
      isCompact: true,
    };
  }

  return bestResult;
}
