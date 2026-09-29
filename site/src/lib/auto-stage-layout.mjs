import {
  LOGICAL_LANE_COUNT,
  TRACK_UNITS,
  TRACK_UNITS_PER_LANE
} from "./score-track-layout.mjs";
import {
  interpolateLongPathNode,
  sampleLongPathNodes
} from "./note-line-easing.mjs";

function requirePositive(value, label) {
  if (!Number.isFinite(value) || value <= 0) {
    throw new RangeError(`${label} must be a positive finite number`);
  }
  return value;
}

function round(value) {
  return Math.round(value * 1_000_000) / 1_000_000;
}

export function createAutoStageFrame(
  { width, height },
  {
    gutter = Math.max(16, width * 0.04),
    horizonRatio = 0.12,
    judgementRatio = 0.86,
    topWidthRatio = 0.42,
    perspective = false
  } = {}
) {
  requirePositive(width, "width");
  requirePositive(height, "height");
  if (!Number.isFinite(gutter) || gutter < 0 || gutter * 2 >= width) {
    throw new RangeError("gutter must leave a positive playable width");
  }
  const bottomLeft = gutter;
  const bottomWidth = width - gutter * 2;
  const topWidth = width * topWidthRatio;
  const topLeft = (width - topWidth) / 2;
  const horizonY = height * horizonRatio;
  const judgementY = height * judgementRatio;
  const boundaries = Array.from(
    { length: LOGICAL_LANE_COUNT + 1 },
    (_, laneIndex) => {
      const unit = laneIndex * TRACK_UNITS_PER_LANE;
      const progress = unit / TRACK_UNITS;
      return {
        unit,
        topX: round(topLeft + topWidth * progress),
        bottomX: round(bottomLeft + bottomWidth * progress)
      };
    }
  );

  return {
    width,
    height,
    laneCount: LOGICAL_LANE_COUNT,
    trackUnits: TRACK_UNITS,
    gutter,
    perspective,
    topLeft: round(topLeft),
    topWidth: round(topWidth),
    bottomLeft: round(bottomLeft),
    bottomWidth: round(bottomWidth),
    horizonY: round(horizonY),
    judgementY: round(judgementY),
    boundaries
  };
}

// A ground-plane projection: distant notes move slowly near the horizon and
// accelerate towards the judgement line. Markers and ribbons share this map.
function projectDepth(frame, depth) {
  if (!frame.perspective) return depth;
  const ratio = frame.topWidth / frame.bottomWidth;
  return depth / (ratio + (1 - ratio) * depth);
}

export function projectAutoMarker(
  marker,
  frame,
  chartTime,
  { lookAheadSeconds = 3 } = {}
) {
  requirePositive(lookAheadSeconds, "lookAheadSeconds");
  if (
    !Number.isFinite(chartTime) ||
    !Number.isFinite(marker?.time) ||
    !Number.isFinite(marker?.position) ||
    !Number.isFinite(marker?.size) ||
    marker.size <= 0
  ) {
    throw new TypeError("marker must provide finite time, position and positive size");
  }
  const timeUntilHit = marker.time - chartTime;
  if (timeUntilHit < 0 || timeUntilHit > lookAheadSeconds) {
    return null;
  }

  const depth = projectDepth(frame, timeUntilHit / lookAheadSeconds);
  const stageLeft = frame.bottomLeft + (frame.topLeft - frame.bottomLeft) * depth;
  const stageWidth = frame.bottomWidth + (frame.topWidth - frame.bottomWidth) * depth;
  const y = frame.judgementY + (frame.horizonY - frame.judgementY) * depth;
  const rawX = stageLeft + (marker.position / TRACK_UNITS) * stageWidth;
  const rawRight = rawX + (marker.size / TRACK_UNITS) * stageWidth;
  const x = Math.max(stageLeft, rawX);
  const right = Math.min(stageLeft + stageWidth, rawRight);
  if (right <= x) return null;
  const width = right - x;
  const vanishY = (frame.horizonY * frame.bottomWidth - frame.judgementY * frame.topWidth) / (frame.bottomWidth - frame.topWidth);

  return {
    ...marker,
    x: round(x),
    y: round(y),
    width: round(width),
    centerX: round(x + width / 2),
    depth: round(depth),
    ...(frame.perspective ? {
      slopeLeft: (x - frame.width / 2) / (y - vanishY),
      slopeRight: (right - frame.width / 2) / (y - vanishY)
    } : {})
  };
}

export function projectAutoHitEffect(
  marker,
  frame,
  chartTime,
  { postHitSeconds = 0.12 } = {}
) {
  requirePositive(postHitSeconds, "postHitSeconds");
  if (!Number.isFinite(chartTime) || !Number.isFinite(marker?.time)) {
    throw new TypeError("marker time and chartTime must be finite numbers");
  }
  const elapsed = chartTime - marker.time;
  if (elapsed <= 0 || elapsed > postHitSeconds) return null;

  const hitPosition = projectAutoMarker(marker, frame, marker.time);
  if (!hitPosition) return null;
  return {
    ...hitPosition,
    y: frame.judgementY,
    depth: round(-(elapsed / postHitSeconds) * 0.04)
  };
}

export function projectAutoLongPath(
  path,
  frame,
  chartTime,
  { lookAheadSeconds = 3 } = {}
) {
  requirePositive(lookAheadSeconds, "lookAheadSeconds");
  if (!Number.isFinite(chartTime)) {
    throw new TypeError("chartTime must be a finite number");
  }
  const concreteNodes = (path?.nodes ?? [])
    .filter(
      (node) =>
        Number.isFinite(node.time) &&
        Number.isFinite(node.position) &&
        Number.isFinite(node.size) &&
        node.size >= 0
    )
    .sort((left, right) => left.time - right.time);
  if (concreteNodes.length < 2) return null;

  const startTime = Math.max(concreteNodes[0].time, chartTime);
  const endTime = Math.min(
    concreteNodes.at(-1).time,
    chartTime + lookAheadSeconds
  );
  if (endTime < startTime) return null;
  const sampledNodes = sampleLongPathNodes(concreteNodes);
  const sampleTimes = [
    startTime,
    ...sampledNodes
      .map((node) => node.time)
      .filter((time) => time > startTime && time < endTime),
    endTime
  ].filter((time, index, times) => index === 0 || time !== times[index - 1]);
  const points = sampleTimes
    .map((time) => interpolateLongPathNode(concreteNodes, time))
    .filter((node) => node !== null)
    .map((node) => {
      const depth = projectDepth(frame, (node.time - chartTime) / lookAheadSeconds);
      const stageLeft =
        frame.bottomLeft + (frame.topLeft - frame.bottomLeft) * depth;
      const stageWidth =
        frame.bottomWidth + (frame.topWidth - frame.bottomWidth) * depth;
      const y =
        frame.judgementY + (frame.horizonY - frame.judgementY) * depth;
      const rawX = stageLeft + (node.position / TRACK_UNITS) * stageWidth;
      const rawRight = rawX + (node.size / TRACK_UNITS) * stageWidth;
      const x = Math.max(stageLeft, Math.min(stageLeft + stageWidth, rawX));
      const right = Math.max(
        stageLeft,
        Math.min(stageLeft + stageWidth, rawRight)
      );
      const width = Math.max(0, right - x);
      return {
        ...node,
        x: round(x),
        y: round(y),
        width: round(width),
        centerX: round(x + width / 2),
        depth: round(depth)
      };
    });

  return points.length < 2 ? null : { ...path, points };
}
