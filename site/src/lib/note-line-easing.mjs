const clampProgress = (value) => Math.min(1, Math.max(0, value));

export function applyNoteLineEasing(easing, progress) {
  const t = clampProgress(progress);
  if (easing === "out") return (2 - t) * t;
  if (easing === "in") return t * t;
  return t;
}

export function interpolateLongPathNode(nodes, time) {
  const exact = nodes.find((node) => node.time === time);
  if (exact) return exact;
  for (let index = 1; index < nodes.length; index += 1) {
    const left = nodes[index - 1];
    const right = nodes[index];
    if (time < left.time || time > right.time) continue;
    if (right.time === left.time) return right;
    const linearProgress = (time - left.time) / (right.time - left.time);
    const leftProgress = applyNoteLineEasing(left.easing, linearProgress);
    const rightProgress = applyNoteLineEasing(
      left.easingRight ?? left.easing,
      linearProgress
    );
    const leftEdge = left.position + (right.position - left.position) * leftProgress;
    const leftRightEdge = left.position + left.size;
    const rightRightEdge = right.position + right.size;
    const rightEdge =
      leftRightEdge + (rightRightEdge - leftRightEdge) * rightProgress;
    return {
      time,
      position: leftEdge,
      size: rightEdge - leftEdge,
      visible: false,
      easing: left.easing ?? "linear",
      easingRight: left.easingRight ?? left.easing ?? "linear"
    };
  }
  return null;
}

export function sampleLongPathNodes(nodes, { samplesPerSegment = 12 } = {}) {
  if (!Number.isInteger(samplesPerSegment) || samplesPerSegment < 1) {
    throw new RangeError("samplesPerSegment must be a positive integer");
  }
  if (!Array.isArray(nodes) || nodes.length < 2) return [...(nodes ?? [])];

  const points = [];
  for (let index = 1; index < nodes.length; index += 1) {
    const left = nodes[index - 1];
    const right = nodes[index];
    if (index === 1) points.push(left);
    for (let sample = 1; sample < samplesPerSegment; sample += 1) {
      const time =
        left.time + (right.time - left.time) * (sample / samplesPerSegment);
      const point = interpolateLongPathNode([left, right], time);
      if (point) points.push(point);
    }
    points.push(right);
  }
  return points;
}
