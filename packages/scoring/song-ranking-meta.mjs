/** Scoring-event metadata follows the formal reconstruction, including slide
 * ticks. It is intentionally not a difficulty or player-skill prediction. */
export function songRankingMeta(chart, timeline) {
  const counts = new Map(), seconds = chart.duration > 0 ? chart.duration : null;
  const tempos = (chart.bpmEvents ?? []).map(event => event.bpm).filter(value => Number.isFinite(value) && value > 0);
  let simultaneousEvents = 0, maximum = 0, start = 0, generated = 0;
  const bins = new Map();
  for (const event of timeline.events) {
    counts.set(event.timeMs, (counts.get(event.timeMs) ?? 0) + 1);
    const second = Math.floor(event.timeMs / 1000), count = (bins.get(second) ?? 0) + 1;
    bins.set(second, count);
    if (count > maximum) { maximum = count; start = second; }
    if (event.kind === 'slide-combo') generated++;
  }
  for (const count of counts.values()) if (count > 1) simultaneousEvents += count;
  return { version: 1, bpmMin: tempos.length ? Math.min(...tempos) : null, bpmMax: tempos.length ? Math.max(...tempos) : null,
    averageDensity: seconds ? timeline.events.length / seconds : null, peakDensity: maximum, peakStart: start,
    simultaneousEvents, generatedEvents: generated, authoredEvents: timeline.events.length - generated,
    startsSeconds: timeline.skillTimes.map(time => time / 1000) };
}
