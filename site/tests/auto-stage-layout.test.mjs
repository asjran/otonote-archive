import assert from "node:assert/strict";
import test from "node:test";

import {
  createAutoStageFrame,
  projectAutoHitEffect,
  projectAutoLongPath,
  projectAutoMarker
} from "../src/lib/auto-stage-layout.mjs";

test('perspective accelerates towards the line and keeps ribbons aligned with note endpoints', () => {
  const frame = createAutoStageFrame({ width: 1000, height: 500 }, { topWidthRatio: 0.12, perspective: true });
  const note = { id: 'perspective', time: 3, position: 4, size: 8 };
  const positions = [0, 0.75, 1.5, 2.25, 3].map(time => projectAutoMarker(note, frame, time));
  const movement = positions.slice(1).map((position, i) => position.y - positions[i].y);
  assert.ok(movement.every((value, i) => i === 0 || value > movement[i - 1]));
  assert.equal(positions[0].y, frame.horizonY);
  assert.equal(positions.at(-1).y, frame.judgementY);
  const path = projectAutoLongPath({ nodes: [{ ...note, time: 1 }, note] }, frame, 1.5);
  const end = path.points.at(-1);
  const marker = projectAutoMarker(note, frame, 1.5);
  assert.equal(end.x, marker.x);
  assert.equal(end.y, marker.y);
  assert.equal(end.width, marker.width);
});

test("creates a perspective frame with 12 logical lanes and 13 boundaries", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });

  assert.equal(frame.laneCount, 12);
  assert.equal(frame.boundaries.length, 13);
  assert.deepEqual(frame.boundaries[0], {
    unit: 0,
    topX: 290,
    bottomX: 40
  });
  assert.deepEqual(frame.boundaries[6], {
    unit: 12,
    topX: 500,
    bottomX: 500
  });
  assert.deepEqual(frame.boundaries[12], {
    unit: 24,
    topX: 710,
    bottomX: 960
  });
  assert.equal(frame.horizonY, 72);
  assert.equal(frame.judgementY, 516);
});

test("projects markers from the horizon to the judgement line on the 24-unit track", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });
  const marker = {
    id: "right-quarter",
    kind: "tap",
    time: 3,
    position: 18,
    size: 6
  };

  assert.deepEqual(projectAutoMarker(marker, frame, 3), {
    ...marker,
    x: 730,
    y: 516,
    width: 230,
    centerX: 845,
    depth: 0
  });
  assert.deepEqual(projectAutoMarker(marker, frame, 1.5), {
    ...marker,
    x: 667.5,
    y: 294,
    width: 167.5,
    centerX: 751.25,
    depth: 0.5
  });
  assert.deepEqual(projectAutoMarker(marker, frame, 0), {
    ...marker,
    x: 605,
    y: 72,
    width: 105,
    centerX: 657.5,
    depth: 1
  });
  assert.equal(projectAutoMarker(marker, frame, -0.01), null);
});

test("removes a marker as soon as it passes the judgement line", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });
  const marker = {
    id: "hit-now",
    kind: "tap",
    time: 1,
    position: 9,
    size: 6
  };

  assert.equal(projectAutoMarker(marker, frame, 1.001), null);
});

test("keeps the short post-hit effect anchored to the judgement line", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });
  const marker = {
    id: "hit-effect",
    kind: "tap",
    time: 1,
    position: 9,
    size: 6
  };

  assert.deepEqual(
    projectAutoHitEffect(marker, frame, 1.06, { postHitSeconds: 0.12 }),
    {
      ...marker,
      x: 385,
      y: 516,
      width: 230,
      centerX: 500,
      depth: -0.02
    }
  );
  assert.equal(projectAutoHitEffect(marker, frame, 1), null);
  assert.equal(projectAutoHitEffect(marker, frame, 1.121), null);
});

test("keeps note ratios stable when the decorative gutter changes", () => {
  const marker = {
    id: "ratio",
    kind: "tap",
    time: 0,
    position: 6,
    size: 6
  };
  const narrowGutter = createAutoStageFrame(
    { width: 1000, height: 600 },
    { gutter: 40 }
  );
  const wideGutter = createAutoStageFrame(
    { width: 1000, height: 600 },
    { gutter: 100 }
  );
  const first = projectAutoMarker(marker, narrowGutter, 0);
  const second = projectAutoMarker(marker, wideGutter, 0);

  assert.equal((first.x - narrowGutter.bottomLeft) / narrowGutter.bottomWidth, 0.25);
  assert.equal(first.width / narrowGutter.bottomWidth, 0.25);
  assert.equal((second.x - wideGutter.bottomLeft) / wideGutter.bottomWidth, 0.25);
  assert.equal(second.width / wideGutter.bottomWidth, 0.25);
});

test("projects visible and invisible long controls as one continuous path", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });
  const path = projectAutoLongPath(
    {
      id: "long-curve",
      kind: "long",
      startTime: 1,
      endTime: 4,
      nodes: [
        { time: 1, position: 0, size: 6, visible: true },
        { time: 2, position: 6, size: 6, visible: false },
        { time: 4, position: 18, size: 6, visible: true }
      ]
    },
    frame,
    1
  );

  assert.equal(path?.points.length, 25);
  assert.deepEqual(
    [path?.points[0], path?.points[12], path?.points.at(-1)].map(
      ({ time, x, y, width, centerX, visible }) => ({
        time,
        x,
        y,
        width,
        centerX,
        visible
      })
    ),
    [
      { time: 1, x: 40, y: 516, width: 230, centerX: 155, visible: true },
      {
        time: 2,
        x: 311.666667,
        y: 368,
        width: 188.333333,
        centerX: 405.833333,
        visible: false
      },
      { time: 4, x: 605, y: 72, width: 105, centerX: 657.5, visible: true }
    ]
  );
});

test("clips a long path at the judgement line", () => {
  const frame = createAutoStageFrame({ width: 1000, height: 600 });
  const path = projectAutoLongPath(
    {
      id: "held-note",
      kind: "long",
      startTime: 1,
      endTime: 2,
      nodes: [
        { time: 1, position: 3, size: 6, visible: true },
        { time: 2, position: 9, size: 6, visible: true }
      ]
    },
    frame,
    1.05
  );

  assert.equal(path?.points[0].time, 1.05);
  assert.equal(path?.points[0].y, 516);
  assert.ok(path?.points.every((point) => point.y <= frame.judgementY));
});
