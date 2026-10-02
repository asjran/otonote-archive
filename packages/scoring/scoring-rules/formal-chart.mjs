import { createFormalTickConverter, roundToEven } from "./formal-time.mjs";

const f32 = Math.fround;
const nonScoring = new Set([0, 80, 82, 100, 103, 121, 122, 123]);
const mergeable = new Set([20, 22, 41, 42, 61, 62, 80, 82, 100, 101, 102, 103, 104, 105]);
const before = (a, b) => a.bar < b.bar || a.bar === b.bar && a.progress < b.progress;
const overlapKey = (n) => [n.tick, roundToEven(f32(n.position)), roundToEven(f32(n.size))].join(":");
const beginTypes = new Set([20, 41, 61, 80, 100, 101, 102, 104]);

// SsMusicScoreConverter.<CreateNoteDictionary>b__23_2 (0x6a50d68).
// This priority orders creation, including nodes that never award score.
export const formalNoteCreationPriority = (type) => beginTypes.has(type) ? 8 : type === 122 ? 9 : 10;
export const FORMAL_CHART_MODEL_VERSION = "formal-chart-v2";

export function formalLineNodeGeometry(line, index) {
  const node = line.nodes[index];
  if (node.position !== null) return node;
  if (index === 0 || index === line.nodes.length - 1) return { ...node,
    position: f32(line.nodes[0].position ?? 0), size: f32(line.nodes[0].size ?? 0) };
  let left = index - 1, right = index + 1;
  while (left > 0 && line.nodes[left].position === null) left--;
  while (right < line.nodes.length - 1 && line.nodes[right].position === null) right++;
  const a = line.nodes[left], b = line.nodes[right];
  const t = b.tick > a.tick ? f32(f32(node.tick - a.tick) / f32(b.tick - a.tick)) : 0;
  // GetNoteLineTypeEasing (0x6a39468), then independent left/right edges.
  const ease = (kind) => kind === "in" ? f32(t * t) : kind === "out" ? f32(f32(2 - t) * t) : t;
  const start = f32(a.position ?? 0), end = f32(b.position ?? 0);
  const leftEdge = f32(start + f32(ease(a.easing) * f32(end - start)));
  const startRight = f32(start + f32(a.size ?? 0)), endRight = f32(end + f32(b.size ?? 0));
  const rightEdge = f32(startRight + f32(ease(a.easingRight) * f32(endRight - startRight)));
  return { ...node, position: leftEdge, size: f32(rightEdge - leftEdge) };
}

// SsTickConverter.BuildSigSegments / TickToBarPosition (1.0.1 build 25).
export function createFormalBarConverter(chart) {
  const clock = createFormalTickConverter(chart.bpmEvents);
  const signatures = [];
  let tick = 0, bar = 0, ticksPerBar = 1920;
  const source = chart.timeSignatureEvents ?? [{ tick: 0, numerator: 4, denominator: 4 }];
  if (!source.length || source[0].tick > 0) signatures.push({ tick, bar, ticksPerBar, beats: 4 });
  for (const sig of [...source].sort((a, b) => a.tick - b.tick)) {
    if (!Number.isInteger(sig.tick) || sig.tick < tick || !(sig.numerator > 0) || !(sig.denominator > 0)) throw new Error("Invalid time signature");
    bar += Math.trunc((sig.tick - tick) / ticksPerBar);
    tick = sig.tick;
    ticksPerBar = Math.trunc(1920 * sig.numerator / sig.denominator);
    if (!ticksPerBar) throw new Error("Invalid time signature length");
    signatures.push({ tick, bar, ticksPerBar, beats: f32(f32(sig.numerator * 4) / sig.denominator) });
  }
  const atTick = (tick) => {
    const sig = signatures.findLast((s) => s.tick <= tick);
    const delta = tick - sig.tick;
    return { bar: sig.bar + Math.trunc(delta / sig.ticksPerBar),
      progress: f32((delta % sig.ticksPerBar) / sig.ticksPerBar), timeMs: clock.atTick(tick) };
  };
  const bpm = [...chart.bpmEvents].sort((a, b) => a.tick - b.tick).map((s) => ({ ...atTick(s.tick), bpm: f32(s.bpm) }));
  const bars = signatures.map((s) => ({ ...atTick(s.tick), beats: s.beats }));
  // GetTimeMsFromBar (0x6a3bd80): events strictly BEFORE the position;
  // latest event time anchors the float32 bar-distance calculation.
  function atPosition(position) {
    let beats = 4, tempo = 160, anchor = { bar: 0, progress: 0, timeMs: 0 };
    for (const event of bars) if (before(event, position)) {
      beats = event.beats;
      if (event.timeMs > anchor.timeMs) anchor = event;
    }
    for (const event of bpm) if (before(event, position)) {
      tempo = event.bpm;
      if (event.timeMs > anchor.timeMs) anchor = event;
    }
    const secondsPerBar = f32(f32(beats * 60) / tempo);
    const seconds = f32(f32(secondsPerBar * f32(position.bar - anchor.bar)) +
      f32(secondsPerBar * f32(position.progress - anchor.progress)));
    return anchor.timeMs + Math.floor(f32(seconds * 1000));
  }
  return { clock, atTick: (tick) => { const p = atTick(tick); return { ...p, timeMs: atPosition(p) }; }, atPosition,
    beatsAtBar: (bar) => bars.findLast((s) => s.bar <= bar)?.beats ?? 4,
    bpmAtTime: (time) => bpm.findLast((s) => s.timeMs <= time)?.bpm ?? 160 };
}

function nodeType(line, node, index, overlap) {
  const last = index === line.nodes.length - 1;
  const op = node.operateType;
  if (line.type === "guide") {
    if (!index) return overlap ? ({ tap: 101, flick: 102, trace: 104 })[overlap.type] : 100;
    if (last) return node.visible !== false && op === "trace" ? 105 : 103;
    return node.position === null || node.visible !== false ? 63 : 122;
  }
  if (!index) return node.visible === false ? 80 : op === "flick" ? 41 : op === "trace" ? 61 : 20;
  if (last) return node.visible === false ? 82 : op === "flick" ? 42 : op === "trace" ? 62 : 22;
  if (node.position === null) return 21;
  return node.visible === false ? 122 : op === "trace" ? 63 : 21;
}

// IsSamePosition uses Mathf.Approximately on the within-bar float, not ms.
function samePosition(a, b) {
  return a.bar === b.bar && Math.abs(f32(a.progress - b.progress)) <
    Math.max(f32(f32(0.000001) * Math.max(Math.abs(a.progress), Math.abs(b.progress))), 8 * 2 ** -149);
}

/** Native conversion reconstruction, independent of legacy comboEvents.
 * Keep verification separate: matching Master FC alone cannot prove timing,
 * merged-line ownership or the order of simultaneous judgements. */
export function reconstructFormalChart(chart, diagnostics = {}) {
  let authored = 0, mergedCount = 0, candidatesCount = 0, skippedCount = 0;
  const clock = createFormalBarConverter(chart);
  const singles = chart.notes.filter((n) => !n.nodes);
  // Native BuildNoteInfoList emits singles, then long lines, then guides;
  // each line group is stable-sorted by its starting tick before conversion.
  const sourceLines = chart.notes.filter((n) => n.nodes);
  for (const line of sourceLines) if (!["long", "guide"].includes(line.type) || line.nodes.length < 2 ||
      line.nodes.some((n, i) => i && n.tick < line.nodes[i - 1].tick)) throw new Error("Invalid slide nodes");
  const lines = ["long", "guide"].flatMap((type) => sourceLines.filter((n) => n.type === type)
    .sort((a, b) => a.nodes[0].tick - b.nodes[0].tick));
  const guideKeys = new Set(lines.filter((n) => n.type === "guide" && n.nodes[0].position !== null).map((n) => overlapKey(n.nodes[0])));
  const overlaps = new Map();
  for (const n of singles) if (guideKeys.has(overlapKey(n)) && !overlaps.has(overlapKey(n))) overlaps.set(overlapKey(n), n);
  const events = [], authoredNodes = [], merged = new Map(), lineIds = new Map();
  function add(event, node, lineIndex) {
    const scoring = !nonScoring.has(event.type);
    if (scoring) authored++;
    const entry = { event: { ...event, critical: !!node.critical }, node,
      lines: lineIndex === undefined ? [] : [lineIndex] };
    if (mergeable.has(event.type) && node.position !== null) {
      const key = [f32(event.bar + event.progress), roundToEven(f32(node.position)), event.type,
        Math.max(1, roundToEven(f32(node.size))), node.direction ?? "none", !!node.critical,
        node.easing ?? "linear", node.easingRight ?? "linear"].join(":");
      if (merged.has(key)) {
        if (scoring) mergedCount++;
        const existing = merged.get(key);
        existing.lines.push(...entry.lines);
        return existing.event;
      }
      merged.set(key, entry);
    }
    authoredNodes.push(entry);
    if (scoring) { entry.event.sourceIndex = events.length; events.push(entry.event); }
    return entry.event;
  }
  for (const n of singles) if (overlaps.get(overlapKey(n)) !== n) {
    const type = { tap: 1, flick: 40, trace: 60 }[n.type];
    if (!type) throw new Error(`Unsupported note type ${n.type}`);
    add({ ...clock.atTick(n.tick), type, noteId: n.id, kind: "authored" }, n);
  }
  const comboGroups = [];
  for (const [lineIndex, line] of lines.entries()) {
    const overlap = line.type === "guide" && line.nodes[0].position !== null ? overlaps.get(overlapKey(line.nodes[0])) : undefined;
    const nodes = line.nodes.map((n, i) => ({ ...clock.atTick(n.tick), type: nodeType(line, n, i, overlap),
      noteId: line.id, nodeIndex: i, kind: "authored" }));
    nodes.forEach((n, i) => add(n, { ...formalLineNodeGeometry(line, i),
      direction: i === 0 && overlap ? overlap.direction : line.nodes[i].direction }, lineIndex));
    // GuideBeginNote.AddCombo is an empty method (0x6a54e48).
    if (line.type === "guide") continue;
    const controls = nodes.slice(1, -1).filter((n) => !nonScoring.has(n.type));
    const boundaries = [nodes[0], ...controls, nodes.at(-1)];
    const candidates = [];
    for (let i = 1; i < boundaries.length; i++) {
      let { bar, progress } = boundaries[i - 1];
      let step = 1 / (2 * clock.beatsAtBar(bar));
      for (let guard = 0; guard < 100000; guard++) {
        progress += step;
        if (progress >= 1) { progress -= 1; bar++; step = 1 / (2 * clock.beatsAtBar(bar)); }
        const p = { bar, progress: f32(progress) };
        const timeMs = clock.atPosition(p);
        if (timeMs >= boundaries[i].timeMs) break;
        candidates.push({ ...p, timeMs });
        if (guard === 99999) throw new Error("Invalid slide duration");
      }
    }
    candidatesCount += candidates.length;
    const combos = [];
    candidates.forEach((p, i) => {
      const skip = () => { skippedCount++; };
      if (nodes.slice(1).some((n) => !nonScoring.has(n.type) && samePosition(p, n))) return skip();
      const halfBeatMs = 15000 / clock.bpmAtTime(p.timeMs);
      if (controls.some((n) => p.timeMs < n.timeMs && n.timeMs - halfBeatMs <= p.timeMs)) return skip();
      if (!i && p.timeMs - nodes[0].timeMs < halfBeatMs) return skip();
      if (i === candidates.length - 1 && nodes.at(-1).timeMs - p.timeMs < halfBeatMs) return skip();
      const event = { ...p, type: 120, noteId: line.id, kind: "slide-combo", sourceIndex: events.length };
      events.push(event);
      combos.push({ event, candidateIndex: i });
    });
    comboGroups.push({ lineIndex, combos });
  }
  // BuildNoteInfoDictionary groups by float32 bar position then rounded lane.
  // Dictionary.Values preserves first insertion order; OrderBy(priority) is
  // stable across the flattened lane groups. Sorting only by time/source order
  // loses this distinction when multiple note types occupy the same lane.
  const positions = new Map();
  for (const entry of authoredNodes) {
    const key = f32(entry.event.bar + entry.event.progress);
    if (!positions.has(key)) positions.set(key, new Map());
    const lanes = positions.get(key), lane = roundToEven(f32(entry.node.position));
    if (!lanes.has(lane)) lanes.set(lane, []);
    lanes.get(lane).push(entry);
  }
  let nativeNoteId = 0, nativeLineId = 0, nativeGuideLineCount = 0;
  for (const [, lanes] of [...positions].sort(([a], [b]) => a - b)) {
    const entries = [...lanes.values()].flat().sort((a, b) =>
      formalNoteCreationPriority(a.event.type) - formalNoteCreationPriority(b.event.type));
    for (const entry of entries) {
      entry.event.nativeNoteId = ++nativeNoteId;
      if (beginTypes.has(entry.event.type)) for (const lineIndex of entry.lines) {
        // Guides have their own counter and 10000 offset (0x6a40cd0).
        lineIds.set(lineIndex, lines[lineIndex].type === "guide" ? 10000 + ++nativeGuideLineCount : ++nativeLineId);
      }
    }
  }
  for (const { event, lines: owners } of authoredNodes) if (owners.length) {
    event.nativeLineIds = owners.map((lineIndex) => lineIds.get(lineIndex));
  }
  // TrySetSlideNoteId 0x6a44fac..0x6a45190: lineId + 10000*(i+1).
  // Candidate index includes skipped nodes; these gaps must not be compacted.
  for (const { lineIndex, combos } of comboGroups) for (const { event, candidateIndex } of combos) {
    event.nativeLineId = lineIds.get(lineIndex);
    event.nativeNoteId = event.nativeLineId + 10000 * (candidateIndex + 1);
  }
  Object.assign(diagnostics, {explicitJudgementCount: authored, mergedEndpointReduction: mergedCount,
    slideComboCandidateCount: candidatesCount, skippedSlideComboCount: skippedCount,
    nativeAuthoredNoteCount: nativeNoteId, nativeLineCount: nativeLineId,
    nativeGuideLineCount, nativeNoteIdModel: FORMAL_CHART_MODEL_VERSION});
  return events.sort((a, b) => a.timeMs - b.timeMs || a.nativeNoteId - b.nativeNoteId || a.sourceIndex - b.sourceIndex);
}
