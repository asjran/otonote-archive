import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import test from "node:test";

import {
  getCurrentCombo,
  normalizeAutoTimeline,
  queryAutoTimeline,
  resolveTimelineChartTime
} from "../src/lib/auto-timeline.mjs";

test("normalizes unsorted notes onto one stable absolute timeline", () => {
  const timeline = normalizeAutoTimeline({
    id: "chart-fixture",
    duration: 12,
    skillTimings: [],
    feverRanges: [],
    callTimings: [],
    notes: [
      {
        id: "flick-late",
        type: "flick",
        time: 4,
        position: 18,
        size: 6,
        direction: "right"
      },
      {
        id: "long-first",
        type: "long",
        nodes: [
          { time: 1, position: 2, size: 4, visible: true },
          { time: 3, position: 8, size: 4, visible: true }
        ]
      },
      {
        id: "tap-middle",
        type: "tap",
        time: 2,
        position: 10,
        size: 4
      }
    ]
  });

  assert.equal(timeline.id, "chart-fixture");
  assert.equal(timeline.duration, 12);
  assert.deepEqual(
    timeline.markers.map(({ id, kind, time }) => ({ id, kind, time })),
    [
      { id: "long-first:0", kind: "long-node", time: 1 },
      { id: "tap-middle", kind: "tap", time: 2 },
      { id: "long-first:1", kind: "long-node", time: 3 },
      { id: "flick-late", kind: "flick", time: 4 }
    ]
  );
  assert.deepEqual(
    timeline.longPaths.map(({ id, kind, startTime, endTime }) => ({
      id,
      kind,
      startTime,
      endTime
    })),
    [
      {
        id: "long-first",
        kind: "long",
        startTime: 1,
        endTime: 3
      }
    ]
  );
});

test("keeps invisible long and guide nodes as path controls without creating markers", () => {
  const timeline = normalizeAutoTimeline({
    id: "path-fixture",
    duration: 8,
    skillTimings: [],
    feverRanges: [],
    callTimings: [],
    notes: [
      {
        id: "long-with-control",
        type: "long",
        nodes: [
          { time: 1, position: 2, size: 4, visible: true, easing: "out" },
          { time: 2, position: 8, size: 4, visible: false, easing: "in" },
          {
            time: 3,
            position: 14,
            size: 6,
            visible: true,
            flick: true,
            direction: "left"
          }
        ]
      },
      {
        id: "guide-only",
        type: "guide",
        nodes: [
          { time: 4, position: 0, size: 6, visible: false },
          { time: 5, position: 6, size: 6, visible: false }
        ]
      }
    ]
  });

  assert.deepEqual(
    timeline.markers.map(({ id, kind, direction }) => ({
      id,
      kind,
      direction
    })),
    [
      {
        id: "long-with-control:0",
        kind: "long-node",
        direction: undefined
      },
      {
        id: "long-with-control:2",
        kind: "long-flick",
        direction: "left"
      }
    ]
  );
  assert.equal(timeline.longPaths.length, 2);
  assert.deepEqual(
    timeline.longPaths[0].nodes.map(({ visible, easing }) => ({ visible, easing })),
    [
      { visible: true, easing: "out" },
      { visible: false, easing: "in" },
      { visible: true, easing: "linear" }
    ]
  );
  assert.equal(timeline.longPaths[1].kind, "guide");
});

test("resolves auto guide spans without creating judgement markers", () => {
  const timeline = normalizeAutoTimeline({
    id: "guide-auto-fixture",
    duration: 2,
    skillTimings: [],
    feverRanges: [],
    callTimings: [],
    notes: [
      {
        id: "guide-auto",
        type: "guide",
        nodes: [
          { time: 0, position: 0, size: 4, visible: false },
          { time: 1, position: null, size: null, visible: true },
          { time: 2, position: 12, size: 8, visible: false }
        ]
      }
    ]
  });

  assert.deepEqual(timeline.markers, []);
  assert.deepEqual(
    timeline.longPaths[0].nodes.map(({ position, size }) => ({ position, size })),
    [
      { position: 0, size: 4 },
      { position: 6, size: 6 },
      { position: 12, size: 8 }
    ]
  );
});

test("preserves parser combo ordinals and resolves them deterministically after seeking", () => {
  const timeline = normalizeAutoTimeline({
    id: "combo-fixture",
    duration: 8,
    skillTimings: [],
    feverRanges: [],
    callTimings: [],
    comboEvents: [
      { time: 1, combo: 1, markerId: "trace-first", noteId: "trace-first", nodeIndex: null },
      { time: 2, combo: 2, markerId: "tap-second", noteId: "tap-second", nodeIndex: null },
      { time: 2, combo: 3, markerId: "long-third:0", noteId: "long-third", nodeIndex: 0 }
    ],
    notes: [
      { id: "trace-first", type: "trace", time: 1, position: 0, size: 2 },
      { id: "tap-second", type: "tap", time: 2, position: 2, size: 2 },
      { id: "long-third", type: "long", nodes: [
        { time: 2, position: 4, size: 2, visible: true },
        { time: 3, position: 6, size: 2, visible: false }
      ] }
    ]
  });

  assert.equal(timeline.markers[0].kind, "trace");
  assert.deepEqual(timeline.markers.map(({ id, combo }) => ({ id, combo })), [
    { id: "trace-first", combo: 1 },
    { id: "tap-second", combo: 2 },
    { id: "long-third:0", combo: 3 }
  ]);
  assert.equal(getCurrentCombo(timeline, 1.999), 1);
  assert.equal(getCurrentCombo(timeline, 2), 3);
  assert.equal(getCurrentCombo(timeline, 0), 0);
  assert.equal(getCurrentCombo(timeline, 3), 3);
  assert.equal(getCurrentCombo(timeline, 1.5), 1);
});

test("keeps synthetic slide Combo events off the visible marker layer", () => {
  const timeline = normalizeAutoTimeline({
    id: "synthetic-combo-fixture",
    duration: 3,
    skillTimings: [],
    feverRanges: [],
    callTimings: [],
    comboEvents: [
      { time: 0, combo: 1, markerId: "held:0", noteId: "held", nodeIndex: 0 },
      { time: 0.5, combo: 2, markerId: null, noteId: "held", nodeIndex: null, synthetic: true },
      { time: 1, combo: 3, markerId: "held:1", noteId: "held", nodeIndex: 1 }
    ],
    notes: [{
      id: "held",
      type: "long",
      nodes: [
        { time: 0, position: 2, size: 4, visible: true },
        { time: 1, position: 8, size: 4, visible: true }
      ]
    }]
  });

  assert.equal(timeline.markers.length, 2);
  assert.deepEqual(timeline.markers.map(({ combo }) => combo), [1, 3]);
  assert.equal(getCurrentCombo(timeline, 0.75), 2);
  assert.equal(getCurrentCombo(timeline, 1), 3);
});

test("aligns the media tail to the final chart judgement", () => {
  assert.equal(
    resolveTimelineChartTime(
      {
        state: "paused",
        mediaTime: 98.61,
        chartTime: 98.61,
        duration: 98.61
      },
      98.627264
    ),
    98.627264
  );
  assert.equal(
    resolveTimelineChartTime(
      {
        state: "seeking",
        mediaTime: 98.62,
        chartTime: 98.62,
        duration: null
      },
      98.627264
    ),
    98.627264
  );
  assert.equal(
    resolveTimelineChartTime(
      {
        state: "playing",
        mediaTime: 40,
        chartTime: 40,
        duration: 98.61
      },
      98.627264,
      { positionOffsetMs: 25 }
    ),
    40.025
  );
});

test("normalizes skill, fever and call events as sorted timeline cues", () => {
  const timeline = normalizeAutoTimeline({
    id: "cue-fixture",
    duration: 8,
    skillTimings: [3, 1],
    feverRanges: [{ start: 2, end: 4 }],
    callTimings: [{ time: 0, pattern: [0, 1, 0, 1] }],
    notes: []
  });

  assert.deepEqual(
    timeline.cues.map(({ id, kind, time }) => ({ id, kind, time })),
    [
      { id: "call:0", kind: "call", time: 0 },
      { id: "skill:1", kind: "skill", time: 1 },
      { id: "fever:0:start", kind: "fever-start", time: 2 },
      { id: "skill:0", kind: "skill", time: 3 },
      { id: "fever:0:end", kind: "fever-end", time: 4 }
    ]
  );
  assert.deepEqual(timeline.cues[0].pattern, [0, 1, 0, 1]);
});

test("queries markers and cues by time while retaining paths that intersect the window", () => {
  const timeline = normalizeAutoTimeline({
    id: "window-fixture",
    duration: 10,
    skillTimings: [3.5, 8],
    feverRanges: [],
    callTimings: [],
    notes: [
      { id: "tap-before", type: "tap", time: 1, position: 0, size: 4 },
      { id: "tap-inside", type: "tap", time: 2.5, position: 4, size: 4 },
      { id: "tap-after", type: "tap", time: 5.1, position: 8, size: 4 },
      {
        id: "long-before",
        type: "long",
        nodes: [
          { time: 0, position: 0, size: 4 },
          { time: 2.2, position: 4, size: 4 }
        ]
      },
      {
        id: "long-touching-end",
        type: "long",
        nodes: [
          { time: 4.5, position: 8, size: 4 },
          { time: 6, position: 12, size: 4 }
        ]
      }
    ]
  });

  const window = queryAutoTimeline(timeline, {
    time: 3,
    pastSeconds: 0.5,
    futureSeconds: 1.5
  });

  assert.deepEqual({ start: window.start, end: window.end }, { start: 2.5, end: 4.5 });
  assert.deepEqual(window.markers.map(({ id }) => id), [
    "tap-inside",
    "long-touching-end:0"
  ]);
  assert.deepEqual(window.cues.map(({ id }) => id), ["skill:0"]);
  assert.deepEqual(window.longPaths.map(({ id }) => id), ["long-touching-end"]);
});

test("a hidden long endpoint may collapse to zero width without becoming a judgement marker", () => {
  // Production 10002703 note-562 ends in a hidden, zero-width path control.
  const chart = { id: "collapsed-tail", duration: 2, notes: [{ id: "long", type: "long", nodes: [
    { time: 0, position: 0, size: 24, visible: true },
    { time: 1, position: 0, size: 0, visible: false }
  ] }] };
  const timeline = normalizeAutoTimeline(chart);
  assert.equal(timeline.longPaths[0].nodes[1].size, 0);
  assert.equal(timeline.markers.length, 1);
  chart.notes[0].nodes[1].visible = true;
  assert.throws(() => normalizeAutoTimeline(chart), RangeError);
});

test("normalizes every published chart without losing absolute-time ordering", async () => {
  const chartDirectory = new URL("../public/data/music-charts/", import.meta.url);
  const filenames = (await readdir(chartDirectory))
    .filter((filename) => filename.endsWith(".json"))
    .sort();

  assert.ok(filenames.length > 0);
  for (const filename of filenames) {
    const chart = JSON.parse(await readFile(new URL(filename, chartDirectory), "utf8"));
    let timeline;
    try {
      timeline = normalizeAutoTimeline(chart);
    } catch (error) {
      error.message = `${filename}: ${error.message}`;
      throw error;
    }
    assert.equal(timeline.duration, chart.duration, filename);
    assert.equal(
      timeline.comboEvents.length,
      chart.statistics.judgementCount,
      `${filename} Combo timeline must match Master FC`
    );
    assert.equal(
      timeline.comboEvents.at(-1)?.combo ?? 0,
      chart.statistics.judgementCount,
      `${filename} final Combo must match Master FC`
    );
    assert.ok(
      timeline.markers.every(
        (marker, index) => index === 0 || timeline.markers[index - 1].time <= marker.time
      ),
      `${filename} markers must remain sorted`
    );
    assert.ok(
      timeline.cues.every(
        (cue, index) => index === 0 || timeline.cues[index - 1].time <= cue.time
      ),
      `${filename} cues must remain sorted`
    );
  }
});


test("clamps timeline query windows at the song boundaries", () => {
  const timeline = normalizeAutoTimeline({
    id: "boundary-fixture",
    duration: 10,
    notes: [],
    skillTimings: [],
    feverRanges: [],
    callTimings: []
  });

  assert.deepEqual(
    queryAutoTimeline(timeline, {
      time: -5,
      pastSeconds: 0.5,
      futureSeconds: 1
    }),
    {
      time: -5,
      start: 0,
      end: 0,
      markers: [],
      cues: [],
      longPaths: []
    }
  );
  assert.deepEqual(
    queryAutoTimeline(timeline, {
      time: 20,
      pastSeconds: 0.5,
      futureSeconds: 1
    }),
    {
      time: 20,
      start: 10,
      end: 10,
      markers: [],
      cues: [],
      longPaths: []
    }
  );
});
