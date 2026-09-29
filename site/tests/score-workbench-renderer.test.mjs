import assert from "node:assert/strict";
import test from "node:test";

import {
  inspectScoreTarget,
  renderScoreTrack
} from "../src/lib/score-workbench-renderer.ts";
import { getRuntimeUiLabels } from "../src/lib/runtime-ui-labels.ts";

const chart = {
  id: "chart-expert",
  difficulty: "expert",
  duration: 10,
  bpmEvents: [{ time: 0, bpm: 120 }],
  timeSignatureEvents: [{ time: 0, numerator: 4, denominator: 4 }],
  skillTimings: [3],
  feverRanges: [{ start: 4, end: 6 }],
  comboEvents: [
    {
      time: 2,
      combo: 1,
      markerId: "tap-1",
      noteId: "tap-1",
      nodeIndex: null
    }
  ],
  notes: [
    {
      id: "tap-1",
      type: "tap",
      time: 2,
      position: 4,
      size: 2
    }
  ],
  density: [{ start: 2, end: 3, count: 1 }],
  statistics: {
    noteCounts: { tap: 1, flick: 0, trace: 0, long: 0 },
    averageDensity: 0.1,
    peakDensity: 1,
    bpm: { min: 120, max: 120 }
  }
};

test("renderScoreTrack returns a complete deterministic track plan", () => {
  const rendered = renderScoreTrack({
    chart,
    width: 240,
    pixelsPerSecond: 100,
    enabled: new Set(["tap", "events"])
  });

  assert.equal(rendered.height, 1000);
  assert.deepEqual(rendered.laneBoundaries.slice(0, 3), [0, 20, 40]);
  assert.deepEqual(rendered.secondLines.slice(0, 3), [1000, 900, 800]);
  assert.deepEqual(rendered.feverBands, [{ top: 400, height: 200 }]);
  assert.deepEqual(rendered.skillLines, [700]);
  assert.deepEqual(rendered.hitTargets, [
    {
      key: "tap-1",
      kind: "tap",
      x: 50,
      y: 800,
      width: 17.2,
      detailTime: 2,
      position: 4,
      size: 2,
      direction: undefined
    }
  ]);
});

test("inspectScoreTarget derives the inspector view model from chart time", () => {
  assert.deepEqual(
    inspectScoreTarget(chart, {
      key: "tap-1",
      kind: "tap",
      x: 50,
      y: 200,
      width: 20,
      detailTime: 2,
      position: 4,
      size: 2
    }, getRuntimeUiLabels("zh-CN").scoreWorkbench),
    {
      typeLabel: "TAP",
      time: "2.000 s",
      combo: "1",
      lane: "3 / 12",
      position: "4.0 / 24",
      size: "2.0",
      direction: "无",
      bpm: "120",
      timeSignature: "4/4",
      fever: "区间外"
    }
  );
});

test("future notes appear above earlier notes without reversing flick direction", () => {
  const plan = renderScoreTrack({ chart: { ...chart, notes: [
    { id: 'early', type: 'flick', time: 1, position: 0, size: 2, direction: 'left' },
    { id: 'later', type: 'flick', time: 9, position: 22, size: 2, direction: 'right' }
  ] }, width: 240, pixelsPerSecond: 100, enabled: new Set(['flick']) });
  assert.ok(plan.markers[0].y > plan.markers[1].y);
  assert.equal(plan.markers[0].direction, 'left');
  assert.equal(plan.markers[1].direction, 'right');
});
