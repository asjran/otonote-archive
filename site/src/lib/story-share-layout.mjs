export const MAX_SHARE_LINES = 80;
// At 2x this stays within a 1080 x 16000 canvas, including mobile browsers.
export const MAX_SHARE_HEIGHT = 8000;

export function selectedRange(anchor, end = anchor) {
  if (!Number.isInteger(anchor) || !Number.isInteger(end) || anchor < 0 || end < 0) return null;
  return { start: Math.min(anchor, end), end: Math.max(anchor, end), count: Math.abs(end - anchor) + 1 };
}

/** Wrap without losing whitespace, explicit line breaks, or joined emoji. */
export function wrapStoryText(text, maxWidth, measure) {
  const graphemes = new Intl.Segmenter(undefined, { granularity: "grapheme" });
  const output = [];
  for (const paragraph of String(text).split(/\r\n|\r|\n/)) {
    let line = "";
    for (const { segment } of graphemes.segment(paragraph)) {
      if (line && measure(line + segment) > maxWidth) {
        output.push(line);
        line = "";
      }
      line += segment;
    }
    output.push(line);
  }
  return output;
}

/** Measure before allocating the final canvas; never crop an oversized excerpt. */
export function shareImageHeight(headerHeight, rowHeights, footerHeight) {
  const height = Math.ceil(headerHeight + rowHeights.reduce((sum, value) => sum + value, 0) + footerHeight);
  if (!rowHeights.length || rowHeights.length > MAX_SHARE_LINES || height > MAX_SHARE_HEIGHT) {
    throw new RangeError("Story excerpt exceeds image limits");
  }
  return height;
}
