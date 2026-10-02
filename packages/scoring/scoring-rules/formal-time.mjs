// Production 1.0.1 (25): SsTickConverter.BuildBpmSegments (0x6a53c44)
// and TickToTimeMs (0x6a50990). Segment anchors round to even; tick-derived event times floor.
// Scoring note times additionally pass through GetTimeMsFromBar (formal-chart).
const f32 = Math.fround;

export function roundToEven(value) {
  const floor = Math.floor(value);
  const fraction = value - floor;
  return fraction === 0.5 ? floor + (floor % 2 === 0 ? 0 : 1) : Math.round(value);
}

export function createFormalTickConverter(bpmEvents) {
  if (!Array.isArray(bpmEvents) || !bpmEvents.length) throw new Error("BPM events are required");
  const sorted = bpmEvents.map((event) => ({ tick: event.tick ?? event.t, bpm: f32(event.bpm) }))
    .sort((a, b) => a.tick - b.tick);
  const segments = [];
  let previousTick = 0;
  let previousBpm = 120;
  let elapsed = 0;
  if (sorted[0].tick > 0) segments.push({ tick: 0, timeMs: 0, bpm: 120 });
  for (const event of sorted) {
    if (!Number.isInteger(event.tick) || event.tick < 0 || !Number.isFinite(event.bpm) || event.bpm <= 0) {
      throw new Error("Invalid BPM event");
    }
    if (segments.length && segments.at(-1).tick >= event.tick) throw new Error("Duplicate BPM tick");
    elapsed += (event.tick - previousTick) * 60000 / f32(previousBpm * 480);
    segments.push({ ...event, timeMs: roundToEven(elapsed) });
    previousTick = event.tick;
    previousBpm = event.bpm;
  }
  function atTick(tick) {
    if (!Number.isInteger(tick) || tick < 0 || tick > 0x7fffffff) throw new Error("Invalid note tick");
    let lo = 0;
    let hi = segments.length;
    while (lo + 1 < hi) {
      const mid = (lo + hi) >>> 1;
      if (segments[mid].tick <= tick) lo = mid;
      else hi = mid;
    }
    const segment = segments[lo];
    return Math.floor(segment.timeMs + (tick - segment.tick) * 60000 / f32(segment.bpm * 480));
  }
  return { segments, atTick };
}
