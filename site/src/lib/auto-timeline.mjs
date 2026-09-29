import { TRACK_UNITS } from "./score-track-layout.mjs";
import { interpolateLongPathNode } from "./note-line-easing.mjs";

const compareTimedItems = (left, right) =>
  left.time - right.time || left.id.localeCompare(right.id);

function lowerBound(items, target) {
  let low = 0;
  let high = items.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (items[middle].time < target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function upperBound(items, target) {
  let low = 0;
  let high = items.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (items[middle].time <= target) low = middle + 1;
    else high = middle;
  }
  return low;
}

function sliceTimedItems(items, start, end) {
  return items.slice(lowerBound(items, start), upperBound(items, end));
}

function requireFinite(value, label) {
  if (!Number.isFinite(value)) {
    throw new TypeError(`${label} must be a finite number`);
  }
  return value;
}

function normalizeSpan(position, size, label, { allowZeroSize = false } = {}) {
  requireFinite(position, `${label}.position`);
  requireFinite(size, `${label}.size`);
  const invalidSize = allowZeroSize ? size < 0 : size <= 0;
  if (invalidSize || position > TRACK_UNITS || position + size < 0) {
    throw new RangeError(`${label} must intersect the 0–${TRACK_UNITS} track`);
  }
  return { position, size };
}

function normalizeNode(node, label, options) {
  const time = requireFinite(node.time, `${label}.time`);
  const hasIncompleteSpan = node.position === null || node.size === null;
  const span = hasIncompleteSpan
    ? { position: node.position ?? null, size: node.size ?? null }
    : normalizeSpan(node.position, node.size, label, options);

  return {
    time,
    ...span,
    easing: node.easing ?? "linear",
    easingRight: node.easingRight ?? node.easing ?? "linear",
    visible: node.visible !== false,
    critical: node.critical === true,
    flick: Boolean(node.flick),
    direction: node.direction
  };
}

function normalizeLongPath(note) {
  const unresolved = (note.nodes ?? []).map((node, index) =>
    normalizeNode(node, `${note.id}.nodes[${index}]`, {
      allowZeroSize: note.type === "guide" || node.visible === false
    })
  );
  if (unresolved.length < 2) {
    throw new RangeError(`${note.id} must contain at least two nodes`);
  }
  unresolved.sort((left, right) => left.time - right.time);
  const nodes = unresolved.map((node, index) => {
    if (node.position !== null && node.size !== null) return node;
    const left = unresolved
      .slice(0, index)
      .reverse()
      .find((candidate) => candidate.position !== null && candidate.size !== null);
    const right = unresolved
      .slice(index + 1)
      .find((candidate) => candidate.position !== null && candidate.size !== null);
    const projected =
      left && right
        ? interpolateLongPathNode([left, right], node.time)
        : left ?? right;
    if (!projected || projected.position === null || projected.size === null) {
      throw new RangeError(`${note.id}.nodes[${index}] cannot resolve its auto span`);
    }
    return {
      ...node,
      position: node.position ?? projected.position,
      size: node.size ?? projected.size
    };
  });
  nodes.forEach((node, index) =>
    normalizeSpan(node.position, node.size, `${note.id}.nodes[${index}]`, {
      allowZeroSize: note.type === "guide" || node.visible === false
    })
  );

  return {
    id: note.id,
    kind: note.type,
    startTime: nodes[0].time,
    endTime: nodes.at(-1).time,
    nodes
  };
}

export function normalizeAutoTimeline(chart) {
  if (!chart || typeof chart !== "object") {
    throw new TypeError("chart must be an object");
  }
  const duration = requireFinite(chart.duration, "chart.duration");
  const markers = [];
  const longPaths = [];
  const cues = [];

  (chart.skillTimings ?? []).forEach((time, index) => {
    cues.push({
      id: `skill:${index}`,
      kind: "skill",
      time: requireFinite(time, `skillTimings[${index}]`)
    });
  });
  const gekisouRanges = chart.gekisouRanges ?? chart.feverRanges ?? [];
  gekisouRanges.forEach((range, index) => {
    const start = requireFinite(range.start, `feverRanges[${index}].start`);
    const end = requireFinite(range.end, `feverRanges[${index}].end`);
    if (end < start) {
      throw new RangeError(`feverRanges[${index}] must end after it starts`);
    }
    cues.push(
      { id: `fever:${index}:start`, kind: "fever-start", time: start },
      { id: `fever:${index}:end`, kind: "fever-end", time: end }
    );
  });
  (chart.callTimings ?? []).forEach((call, index) => {
    cues.push({
      id: `call:${index}`,
      kind: "call",
      time: requireFinite(call.time, `callTimings[${index}].time`),
      pattern: Array.isArray(call.pattern) ? [...call.pattern] : []
    });
  });

  for (const [noteIndex, note] of (chart.notes ?? []).entries()) {
    if (!note?.id || typeof note.id !== "string") {
      throw new TypeError(`chart.notes[${noteIndex}].id must be a string`);
    }
    if (note.type === "long" || note.type === "guide") {
      const path = normalizeLongPath(note);
      longPaths.push(path);
      if (note.type === "guide") continue;

      path.nodes.forEach((node, nodeIndex) => {
        if (!node.visible || node.position === null || node.size === null) return;
        markers.push({
          id: `${note.id}:${nodeIndex}`,
          sourceId: note.id,
          kind: node.flick ? "long-flick" : "long-node",
          time: node.time,
          position: node.position,
          size: node.size,
          direction: node.direction,
          critical: node.critical,
          nodeIndex,
          isEnd: nodeIndex === path.nodes.length - 1
        });
      });
      continue;
    }
    if (note.type !== "tap" && note.type !== "flick" && note.type !== "trace") continue;

    markers.push({
      id: note.id,
      sourceId: note.id,
      kind: note.type,
      time: requireFinite(note.time, `${note.id}.time`),
      ...normalizeSpan(note.position, note.size, note.id),
      direction: note.direction,
      critical: note.critical === true
    });
  }

  markers.sort(compareTimedItems);
  const comboByMarkerId = new Map();
  const comboEvents = (chart.comboEvents ?? []).map((event, index) => {
    const time = requireFinite(event.time, `comboEvents[${index}].time`);
    const combo = requireFinite(event.combo, `comboEvents[${index}].combo`);
    if (!Number.isInteger(combo) || combo <= 0) {
      throw new RangeError(`comboEvents[${index}].combo must be a positive integer`);
    }
    if (event.markerId !== null && event.markerId !== undefined && typeof event.markerId !== "string") {
      throw new TypeError(`comboEvents[${index}].markerId must be a string or null`);
    }
    const normalized = { ...event, time, combo };
    if (typeof event.markerId === "string") {
      comboByMarkerId.set(event.markerId, normalized);
    }
    return normalized;
  });
  comboEvents.sort((left, right) => left.time - right.time || left.combo - right.combo);
  markers.forEach((marker, index) => {
    marker.combo = comboByMarkerId.get(marker.id)?.combo ?? index + 1;
  });
  markers.sort((left, right) => left.time - right.time || left.combo - right.combo);
  longPaths.sort(
    (left, right) =>
      left.startTime - right.startTime || left.id.localeCompare(right.id)
  );
  cues.sort(compareTimedItems);

  return {
    id: chart.id ?? null,
    duration,
    markers,
    longPaths,
    cues,
    gekisouRanges: gekisouRanges.map((range) => ({ start: range.start, end: range.end })),
    comboEvents: comboEvents.length
      ? comboEvents
      : markers.map((marker) => ({
          time: marker.time,
          combo: marker.combo,
          markerId: marker.id,
          noteId: marker.sourceId,
          nodeIndex: marker.id.includes(":") ? Number(marker.id.split(":").at(-1)) : null
        }))
  };
}

export function getCurrentCombo(timeline, time) {
  if (!timeline || typeof timeline !== "object") {
    throw new TypeError("timeline must be an object");
  }
  requireFinite(time, "time");
  const events = timeline.comboEvents ?? [];
  const index = upperBound(events, time) - 1;
  return index >= 0 ? events[index].combo : 0;
}

export function resolveTimelineChartTime(
  playback,
  timelineDuration,
  { positionOffsetMs = 0, tailToleranceSeconds = 0.05 } = {}
) {
  requireFinite(timelineDuration, "timelineDuration");
  requireFinite(positionOffsetMs, "positionOffsetMs");
  requireFinite(tailToleranceSeconds, "tailToleranceSeconds");
  if (timelineDuration < 0 || tailToleranceSeconds < 0) {
    throw new RangeError("timeline duration and tail tolerance cannot be negative");
  }
  const chartTime = requireFinite(playback?.chartTime ?? 0, "playback.chartTime");
  const mediaTime = playback?.mediaTime;
  const mediaDuration = playback?.duration;
  const atMediaTail =
    Number.isFinite(mediaTime) &&
    Number.isFinite(mediaDuration) &&
    mediaTime >= mediaDuration - tailToleranceSeconds;
  const atTimelineTail = chartTime >= timelineDuration - tailToleranceSeconds;
  if (playback?.state === "ended" || atMediaTail || atTimelineTail) {
    return timelineDuration;
  }
  return Math.min(
    timelineDuration,
    Math.max(0, chartTime + positionOffsetMs / 1000)
  );
}

/**
 * @param {{
 *   duration: number,
 *   markers: Array<{ id: string, time: number }>,
 *   cues: Array<{ id: string, time: number }>,
 *   longPaths: Array<{ id: string, startTime: number, endTime: number }>
 * }} timeline
 * @param {{ time: number, pastSeconds?: number, futureSeconds?: number }} options
 */
export function queryAutoTimeline(
  timeline,
  { time, pastSeconds = 0.12, futureSeconds = 3 } = {}
) {
  if (!timeline || typeof timeline !== "object") {
    throw new TypeError("timeline must be an object");
  }
  requireFinite(time, "time");
  requireFinite(pastSeconds, "pastSeconds");
  requireFinite(futureSeconds, "futureSeconds");
  if (pastSeconds < 0 || futureSeconds < 0) {
    throw new RangeError("timeline window distances cannot be negative");
  }

  const clampToDuration = (value) =>
    Math.min(timeline.duration, Math.max(0, value));
  const start = clampToDuration(time - pastSeconds);
  const end = clampToDuration(time + futureSeconds);

  return {
    time,
    start,
    end,
    markers: sliceTimedItems(timeline.markers, start, end),
    cues: sliceTimedItems(timeline.cues, start, end),
    longPaths: timeline.longPaths.filter(
      (path) => path.endTime >= start && path.startTime <= end
    )
  };
}
