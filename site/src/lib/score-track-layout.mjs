import { sampleLongPathNodes } from "./note-line-easing.mjs";

export const TRACK_UNITS = 24;
export const LOGICAL_LANE_COUNT = 12;
export const TRACK_UNITS_PER_LANE = TRACK_UNITS / LOGICAL_LANE_COUNT;
export const SCORE_PIXELS_PER_SECOND = 240;
export const MOBILE_SCORE_PIXELS_PER_SECOND = 200;
export const NOTE_VISUAL_WIDTH_RATIO = 0.86;

export function getLogicalLaneBoundaries() {
  return Array.from(
    { length: LOGICAL_LANE_COUNT + 1 },
    (_, lane) => lane * TRACK_UNITS_PER_LANE
  );
}

export function describeTrackSpan(position, size) {
  if (
    !Number.isFinite(position) ||
    !Number.isFinite(size) ||
    size <= 0 ||
    position < 0 ||
    position + size > TRACK_UNITS
  ) {
    throw new RangeError(
      `track span must stay inside 0–${TRACK_UNITS}: position=${position}, size=${size}`
    );
  }
  const laneStart = Math.floor(position / TRACK_UNITS_PER_LANE) + 1;
  const laneEnd = Math.ceil((position + size) / TRACK_UNITS_PER_LANE);
  return {
    laneStart,
    laneEnd,
    laneLabel: laneStart === laneEnd ? String(laneStart) : `${laneStart}–${laneEnd}`,
    position,
    size
  };
}

export function getTrackScrollState({
  scrollTop,
  clientHeight,
  duration,
  pixelsPerSecond = SCORE_PIXELS_PER_SECOND
}) {
  const safeDuration = Math.max(0, duration);
  const safeHeight = Math.max(0, clientHeight);
  const maxScrollTop = Math.max(
    0,
    Math.ceil(safeDuration * pixelsPerSecond) - safeHeight
  );
  const clampedScrollTop = Math.min(
    Math.max(0, scrollTop),
    maxScrollTop
  );
  const visibleSeconds = Math.min(
    safeDuration,
    safeHeight / pixelsPerSecond
  );
  const start = (maxScrollTop - clampedScrollTop) / pixelsPerSecond;

  return {
    start,
    end: Math.min(safeDuration, start + visibleSeconds),
    visibleSeconds,
    maxScrollTop,
    scrollTop: clampedScrollTop
  };
}

export function getDensityTargetScrollTop({
  targetTime,
  clientHeight,
  duration,
  pixelsPerSecond = SCORE_PIXELS_PER_SECOND
}) {
  const { maxScrollTop } = getTrackScrollState({
    scrollTop: 0,
    clientHeight,
    duration,
    pixelsPerSecond
  });
  const centered =
    Math.ceil(duration * pixelsPerSecond) - targetTime * pixelsPerSecond - clientHeight / 2;

  return Math.min(Math.max(0, centered), maxScrollTop);
}

export function projectTrackSpan(
  position,
  size,
  playableFrame,
  widthRatio = 1
) {
  const frame =
    typeof playableFrame === "number"
      ? { x: 0, width: playableFrame }
      : playableFrame;
  if (
    !frame ||
    !Number.isFinite(frame.x) ||
    !Number.isFinite(frame.width) ||
    frame.width <= 0
  ) {
    throw new RangeError("playable frame must have a finite x and positive width");
  }
  const unit = frame.width / TRACK_UNITS;
  const rawX = frame.x + position * unit;
  const rawWidth = size * unit;
  const roundCoordinate = (value) =>
    Math.round(value * 1_000_000) / 1_000_000;
  const width = roundCoordinate(rawWidth * widthRatio);
  const x = roundCoordinate(rawX + (rawWidth - width) / 2);
  const visibleLeft = Math.max(frame.x, x);
  const visibleRight = roundCoordinate(
    Math.min(frame.x + frame.width, x + width)
  );

  return {
    x,
    width,
    centerX: roundCoordinate((visibleLeft + visibleRight) / 2),
    visibleLeft,
    visibleRight,
    rawX,
    rawWidth
  };
}

export function flickArrowGeometry(direction, centerX, noteY) {
  if (direction === "left") {
    return [
      { x: centerX - 9, y: noteY - 10 },
      { x: centerX + 6, y: noteY - 15 },
      { x: centerX + 6, y: noteY - 5 }
    ];
  }
  if (direction === "right") {
    return [
      { x: centerX + 9, y: noteY - 10 },
      { x: centerX - 6, y: noteY - 15 },
      { x: centerX - 6, y: noteY - 5 }
    ];
  }
  return [
    { x: centerX, y: noteY - 17 },
    { x: centerX - 7, y: noteY - 5 },
    { x: centerX + 7, y: noteY - 5 }
  ];
}

export function layoutScoreTrack({
  chart,
  start = 0,
  windowSeconds,
  width,
  height,
  enabled,
  pixelsPerSecond,
  noteWidthRatio = 1,
  timeDirection = "down"
}) {
  const scaleY =
    pixelsPerSecond ?? height / windowSeconds;
  const visibleHeight = height ?? Number.POSITIVE_INFINITY;
  const end =
    windowSeconds === undefined
      ? Number.POSITIVE_INFINITY
      : start + windowSeconds;
  const toY = (time) => timeDirection === "up"
    ? visibleHeight - (time - start) * scaleY
    : (time - start) * scaleY;
  const feverBands = enabled.has("events")
    ? chart.feverRanges
        .map((range) => {
          if (range.end <= start || range.start >= end) return { top: 0, height: 0 };
          const top = toY(Math.max(range.start, start));
          const bottom = toY(Math.min(range.end, end));
          return { top: Math.min(top, bottom), height: Math.abs(bottom - top) };
        })
        .filter((band) => band.height > 0 && band.top <= visibleHeight)
    : [];
  const skillLines = enabled.has("events")
    ? chart.skillTimings
        .map(toY)
        .filter((y) => y >= 0 && y <= visibleHeight)
    : [];
  const longRibbons = [];
  const markers = [];

  for (const note of chart.notes) {
    if (note.type === "guide" || !enabled.has(note.type)) continue;

    if (note.type === "long" && note.nodes) {
      const concreteNodes = note.nodes
        .map((node, nodeIndex) => ({ node, nodeIndex }))
        .filter(({ node }) => node.position !== null && node.size !== null);
      if (
        concreteNodes.length < 2 ||
        concreteNodes.at(-1).node.time < start ||
        concreteNodes[0].node.time > end
      ) {
        continue;
      }
      const sampledNodes = sampleLongPathNodes(
        concreteNodes.map(({ node }) => node)
      );
      const points = sampledNodes.map((node) => {
        const span = projectTrackSpan(
          node.position,
          node.size,
          width,
          noteWidthRatio
        );
        return {
          ...span,
          y: toY(node.time),
          time: node.time,
          visible: node.visible,
          flick: Boolean(node.flick),
          direction: node.direction
        };
      });
      longRibbons.push({ note, points });

      for (const { node, nodeIndex } of concreteNodes) {
        if (!node.visible) continue;
        const y = toY(node.time);
        if (y < -18 || y > visibleHeight + 18) continue;
        const span = projectTrackSpan(
          node.position,
          node.size,
          width,
          noteWidthRatio
        );
        markers.push({
          kind: node.flick ? "long-flick" : "long-node",
          key: `${note.id}:${nodeIndex}`,
          note,
          ...span,
          y,
          detailTime: node.time,
          position: node.position,
          size: node.size,
          direction: node.direction
        });
      }
      continue;
    }

    if (
      note.time === undefined ||
      note.position === undefined ||
      note.size === undefined
    ) {
      continue;
    }
    const y = toY(note.time);
    if (y < -18 || y > visibleHeight + 18) continue;
    const span = projectTrackSpan(
      note.position,
      note.size,
      width,
      noteWidthRatio
    );
    markers.push({
      kind: note.type,
      key: note.id,
      note,
      ...span,
      y,
      detailTime: note.time,
      position: note.position,
      size: note.size,
      direction: note.direction
    });
  }

  return {
    feverBands,
    skillLines,
    longRibbons,
    markers
  };
}

// Consecutive windows share a boundary; each note belongs to only one segment.
export function getScoreSegments(duration, segmentSeconds = 8) {
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(segmentSeconds) || segmentSeconds <= 0) return [];
  return Array.from({ length: Math.ceil(duration / segmentSeconds) }, (_, index) => ({
    index, start: index * segmentSeconds, end: Math.min(duration, (index + 1) * segmentSeconds)
  }));
}
