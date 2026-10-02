// Transport state is expressed in chart seconds, independently of playback rate.
export const MIN_CHART_LOOP_SECONDS = 0.25;

export function chartLoopRange(start, end, duration) {
  if (start == null || end == null || start === '' || end === '') return null;
  const values = [start, end, duration].map(Number);
  if (!values.every(Number.isFinite) || values[2] <= 0) return null;
  const a = Math.max(0, Math.min(values[2], values[0]));
  const b = Math.max(0, Math.min(values[2], values[1]));
  return b - a >= MIN_CHART_LOOP_SECONDS - 1e-9 ? { start: a, end: b } : null;
}

export function chartPlaybackFromSearch(search, duration) {
  const params = new URLSearchParams(search);
  const time = Number(params.get('t'));
  return {
    time: Number.isFinite(time) ? Math.max(0, Math.min(duration, time)) : 0,
    loop: chartLoopRange(params.get('loopStart'), params.get('loopEnd'), duration),
  };
}

export function chartPlaybackUrl(href, { time, difficulty, loop }) {
  const url = new URL(href);
  url.searchParams.set('view', 'playback');
  url.searchParams.set('difficulty', difficulty);
  url.searchParams.set('t', Math.max(0, Number(time) || 0).toFixed(2));
  for (const [key, value] of [['loopStart', loop?.start], ['loopEnd', loop?.end]]) {
    if (value != null) url.searchParams.set(key, value.toFixed(2));
    else url.searchParams.delete(key);
  }
  url.hash = '';
  return url;
}
