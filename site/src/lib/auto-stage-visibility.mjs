// Percentages refer to the visible track, independent of chart time and speed.
export function upperHiddenWindow(frame, height = 0, fade = 10) {
  if (!Number.isFinite(height) || height <= 0) return null;
  const hidden = Math.min(80, height) / 100;
  const transition = Math.min(30, Math.max(0, Number.isFinite(fade) ? fade : 10)) / 100;
  const trackHeight = frame.judgementY - frame.horizonY;
  return {
    start: frame.horizonY + trackHeight * hidden,
    end: frame.horizonY + trackHeight * Math.min(0.95, hidden + transition)
  };
}
