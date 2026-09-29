import { getScoreSegments } from './score-track-layout.mjs';

export const SHEET_SEGMENT_SECONDS = 4;

export function parseScoreTime(value) {
  const text = String(value).trim();
  if (/^\d+(?:\.\d+)?$/.test(text)) return Number(text);
  const match = /^(\d+):([0-5]\d(?:\.\d+)?)$/.exec(text);
  return match ? Number(match[1]) * 60 + Number(match[2]) : NaN;
}

export function resolveAtlasRange(startText, endText, duration) {
  const start = String(startText).trim() ? parseScoreTime(startText) : 0;
  const end = String(endText).trim() ? parseScoreTime(endText) : duration;
  if (!Number.isFinite(start) || !Number.isFinite(end)) throw new Error('请输入秒数或分:秒，例如 30.5 或 1:02。');
  if (start < 0 || end > duration) throw new Error(`范围需在 0–${duration.toFixed(3)} 秒内。`);
  if (start >= end) throw new Error('结束时间必须晚于开始时间。');
  return { start, end };
}

export function formatScoreTime(time) {
  return String(Number(time.toFixed(3)));
}

export function getAtlasSegments(duration, range) {
  const start = range?.start ?? 0, end = range?.end ?? duration;
  const segments = getScoreSegments(end - start, SHEET_SEGMENT_SECONDS);
  return segments.map((segment, index) => ({
    index,
    start: Math.round((start + segment.start) * 1e9) / 1e9,
    end: Math.min(end, Math.round((start + segment.end) * 1e9) / 1e9),
    includeEnd: index === segments.length - 1,
  }));
}
