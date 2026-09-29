// GekisouController.GetScoreFrame (0x55d93ec) and
// GetPreviousFrameEndMs (0x55d9314). These are 40 ms SCORE intervals,
// independent of the rendering / skill-update frame rate.
export function gekisouPreviousScoreFrameEnd(timeMs) {
  return (timeMs < 1 ? 0 : Math.ceil(Math.fround(Math.fround(timeMs) / 40))) * 40 - 40;
}

// ScoreCalculationUtility.GetFrame (0x55e15e8). FetchGekisouRangeScore asks
// CalculateLiveScore for both endpoints and subtracts the two whole buckets.
// Ranking-score attribution is therefore distinct from note-ID membership.
export function gekisouScoreFrame(timeMs) {
  return timeMs < 0 ? 0 : Math.ceil(Math.fround(Math.fround(timeMs) / 40));
}
export function gekisouScoreSection(ranges, timeMs) {
  const frame = gekisouScoreFrame(timeMs);
  return ranges.findIndex(r => frame > gekisouScoreFrame(r.startMs) && frame <= gekisouScoreFrame(r.endMs));
}

export function gekisouTimingCombo(history, timeMs) {
  const cutoff = gekisouPreviousScoreFrameEnd(timeMs);
  let lo = 0, hi = history.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (history[mid].timeMs <= cutoff) lo = mid + 1;
    else hi = mid;
  }
  return lo ? history[lo - 1].combo : 0;
}

// Explicit ideal clock used for offline simulation, not a recorded device clock.
// Inputs at the same frame share pre-frame conversion charges / previous LUCK
// results. Score command timestamps remain the authored music positions.
export function gekisouInputFrame(timeMs, offsetMs, frameRate) {
  return Math.max(0, Math.ceil((timeMs + offsetMs) * frameRate / 1000));
}
