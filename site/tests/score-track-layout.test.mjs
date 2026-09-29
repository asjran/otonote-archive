import assert from "node:assert/strict";
import test from "node:test";

import {
  LOGICAL_LANE_COUNT,
  MOBILE_SCORE_PIXELS_PER_SECOND,
  NOTE_VISUAL_WIDTH_RATIO,
  SCORE_PIXELS_PER_SECOND,
  TRACK_UNITS_PER_LANE,
  TRACK_UNITS,
  describeTrackSpan,
  getLogicalLaneBoundaries,
  flickArrowGeometry,
  getDensityTargetScrollTop,
  getTrackScrollState,
  layoutScoreTrack,
  projectTrackSpan
} from "../src/lib/score-track-layout.mjs";

test("describes the verified 24-unit coordinate space as 12 logical lanes", () => {
  assert.equal(TRACK_UNITS, 24);
  assert.equal(LOGICAL_LANE_COUNT, 12);
  assert.equal(TRACK_UNITS_PER_LANE, 2);
  assert.deepEqual(
    getLogicalLaneBoundaries(),
    [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]
  );
});

test("describes note spans with logical lane numbers without rounding raw coordinates", () => {
  assert.deepEqual(describeTrackSpan(10, 4), {
    laneStart: 6,
    laneEnd: 7,
    laneLabel: "6–7",
    position: 10,
    size: 4
  });
  assert.deepEqual(describeTrackSpan(1, 2), {
    laneStart: 1,
    laneEnd: 2,
    laneLabel: "1–2",
    position: 1,
    size: 2
  });
});

test("uses spacious desktop timing and a restrained mobile timing scale", () => {
  assert.equal(SCORE_PIXELS_PER_SECOND, 240);
  assert.equal(MOBILE_SCORE_PIXELS_PER_SECOND, 200);
  const layout = layoutScoreTrack({
    chart: {
      feverRanges: [],
      skillTimings: [],
      notes: [
        { id: "tap-at-ten", type: "tap", time: 10, position: 6, size: 6 }
      ]
    },
    width: 960,
    enabled: new Set(["tap"]),
    pixelsPerSecond: SCORE_PIXELS_PER_SECOND
  });

  assert.equal(layout.markers[0].y, 2400);
});

test("derives the visible score range from the scroll container", () => {
  assert.deepEqual(
    getTrackScrollState({
      scrollTop: 1680,
      clientHeight: 760,
      duration: 100,
      pixelsPerSecond: 168
    }),
    {
      start: (16040 - 1680) / 168,
      end: 90,
      visibleSeconds: 4.523809523809524,
      maxScrollTop: 16040,
      scrollTop: 1680
    }
  );
});

test("centers density selections and clamps them at the end of the song", () => {
  const input = {
    clientHeight: 760,
    duration: 100,
    pixelsPerSecond: 168
  };

  assert.equal(
    getDensityTargetScrollTop({ ...input, targetTime: 50 }),
    8020
  );
  assert.equal(
    getDensityTargetScrollTop({ ...input, targetTime: 100 }),
    0
  );
});

test("projects score positions against the verified 24-unit track", () => {
  assert.equal(TRACK_UNITS, 24);
  assert.deepEqual(projectTrackSpan(18, 6, 960), {
    x: 720,
    width: 240,
    centerX: 840,
    visibleLeft: 720,
    visibleRight: 960,
    rawX: 720,
    rawWidth: 240
  });
  assert.deepEqual(projectTrackSpan(16, 8, 960), {
    x: 640,
    width: 320,
    centerX: 800,
    visibleLeft: 640,
    visibleRight: 960,
    rawX: 640,
    rawWidth: 320
  });
});

test("keeps playable coordinates stable when the surrounding gutter changes", () => {
  const first = projectTrackSpan(6, 6, { x: 80, width: 960 });
  const second = projectTrackSpan(6, 6, { x: 120, width: 960 });

  assert.deepEqual(first, {
    x: 320,
    width: 240,
    centerX: 440,
    visibleLeft: 320,
    visibleRight: 560,
    rawX: 320,
    rawWidth: 240
  });
  assert.equal(first.x - 80, second.x - 120);
  assert.equal(first.width, second.width);
});

test("visual gutters separate adjacent keys without changing centers or source spans", () => {
  const left = projectTrackSpan(6, 6, 960, NOTE_VISUAL_WIDTH_RATIO);
  const right = projectTrackSpan(12, 6, 960, NOTE_VISUAL_WIDTH_RATIO);
  const raw = projectTrackSpan(6, 6, 960);
  assert.ok(left.width < raw.width);
  assert.ok(right.x - (left.x + left.width) > 0);
  assert.equal(left.centerX, raw.centerX);
  assert.equal(left.rawX, raw.rawX);
  assert.equal(left.rawWidth, raw.rawWidth);
});

test("lays out long ribbons before visible note markers on the 24-unit track", () => {
  const layout = layoutScoreTrack({
    chart: {
      feverRanges: [{ start: 0.5, end: 2.5 }],
      skillTimings: [1.5],
      notes: [
        { id: "tap", type: "tap", time: 1, position: 18, size: 6 },
        {
          id: "flick",
          type: "flick",
          time: 2,
          position: 0,
          size: 6,
          direction: "left"
        },
        {
          id: "long",
          type: "long",
          nodes: [
            { time: 1, position: 6, size: 6, visible: true },
            { time: 2, position: 12, size: 6, visible: false },
            {
              time: 3,
              position: 18,
              size: 6,
              visible: true,
              flick: true,
              direction: "right"
            }
          ]
        }
      ]
    },
    start: 0,
    windowSeconds: 10,
    width: 960,
    height: 720,
    noteWidthRatio: 1,
    enabled: new Set(["tap", "flick", "long", "events"])
  });

  assert.deepEqual(layout.feverBands, [{ top: 36, height: 144 }]);
  assert.deepEqual(layout.skillLines, [108]);
  assert.equal(layout.longRibbons.length, 1);
  assert.equal(layout.longRibbons[0].points.length, 25);
  assert.deepEqual(
    [
      layout.longRibbons[0].points[0],
      layout.longRibbons[0].points[12],
      layout.longRibbons[0].points.at(-1)
    ].map(({ centerX, y, width }) => ({ centerX, y, width })),
    [
      { centerX: 360, y: 72, width: 240 },
      { centerX: 600, y: 144, width: 240 },
      { centerX: 840, y: 216, width: 240 }
    ]
  );
  assert.deepEqual(
    layout.markers.map(({ kind, x, y, width, direction }) => ({
      kind,
      x,
      y,
      width,
      direction
    })),
    [
      {
        kind: "tap",
        x: 720,
        y: 72,
        width: 240,
        direction: undefined
      },
      {
        kind: "flick",
        x: 0,
        y: 144,
        width: 240,
        direction: "left"
      },
      {
        kind: "long-node",
        x: 240,
        y: 72,
        width: 240,
        direction: undefined
      },
      {
        kind: "long-flick",
        x: 720,
        y: 216,
        width: 240,
        direction: "right"
      }
    ]
  );
});

test("gives Flick notes a visible arrow for left, right and neutral directions", () => {
  assert.deepEqual(flickArrowGeometry("left", 100, 50), [
    { x: 91, y: 40 },
    { x: 106, y: 35 },
    { x: 106, y: 45 }
  ]);
  assert.deepEqual(flickArrowGeometry("right", 100, 50), [
    { x: 109, y: 40 },
    { x: 94, y: 35 },
    { x: 94, y: 45 }
  ]);
  assert.deepEqual(flickArrowGeometry(undefined, 100, 50), [
    { x: 100, y: 33 },
    { x: 93, y: 45 },
    { x: 107, y: 45 }
  ]);
});

test("the beginning is at the bottom and scrolling upward advances time", () => {
  const input = { clientHeight: 760, duration: 100, pixelsPerSecond: 168 };
  const beginning = getTrackScrollState({ ...input, scrollTop: 16040 });
  const later = getTrackScrollState({ ...input, scrollTop: 16040 - 1680 });
  assert.equal(beginning.start, 0);
  assert.equal(later.start, 10);
  assert.equal(getDensityTargetScrollTop({ ...input, targetTime: 0 }), beginning.maxScrollTop);
  assert.equal(getTrackScrollState({ ...input, scrollTop: 0 }).end, 100);
});

test("fractional durations and short tracks keep the same rendered scroll origin", () => {
  const input = { clientHeight: 760, duration: 3.1415, pixelsPerSecond: 168 };
  assert.equal(getTrackScrollState({ ...input, scrollTop: 100 }).start, 0);
  assert.equal(getTrackScrollState({ ...input, scrollTop: 100 }).end, 3.1415);
  const long = { ...input, duration: 97.531 };
  const bottom = getDensityTargetScrollTop({ ...long, targetTime: 0 });
  assert.equal(getTrackScrollState({ ...long, scrollTop: bottom }).start, 0);
});
