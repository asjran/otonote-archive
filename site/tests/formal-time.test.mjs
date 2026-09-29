import test from "node:test";
import assert from "node:assert/strict";
import { createFormalTickConverter, roundToEven } from "../src/lib/scoring-rules/formal-time.mjs";

test("BPM anchors use midpoint-to-even while note milliseconds floor", () => {
  const clock = createFormalTickConverter([{ tick: 0, bpm: 200 }, { tick: 4, bpm: 120 }]);
  assert.equal(clock.atTick(3), 1); // 1.875 ms, not rounded to 2.
  assert.equal(clock.segments[1].timeMs, 2); // 2.5 ms -> even anchor 2.
  assert.equal(clock.atTick(484), 502);
  assert.deepEqual([0.5, 1.5, 2.5, 3.5, -0.5, -1.5].map(roundToEven), [0, 2, 2, 4, 0, -2]);
});

test("BPM change anchors retain the unrounded accumulated time", () => {
  const clock = createFormalTickConverter([{ tick: 0, bpm: 200 }, { tick: 4, bpm: 200 }, { tick: 8, bpm: 120 }]);
  assert.deepEqual(clock.segments.map((s) => s.timeMs), [0, 2, 5]);
  assert.equal(clock.atTick(8), 5);
  assert.equal(clock.atTick(488), 505);
});

test("rejects invalid time input and uses the native default BPM before a late first event", () => {
  assert.equal(createFormalTickConverter([{ tick: 480, bpm: 200 }]).atTick(240), 250);
  assert.throws(() => createFormalTickConverter([{ tick: 0, bpm: 0 }]));
  assert.throws(() => createFormalTickConverter([{ tick: 0, bpm: 120 }, { tick: 0, bpm: 130 }]));
  assert.throws(() => createFormalTickConverter([{ tick: 0, bpm: 120 }]).atTick(NaN));
});
