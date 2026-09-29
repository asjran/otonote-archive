import test from "node:test";
import assert from "node:assert/strict";
import { createFormalBarConverter, reconstructFormalChart } from "../src/lib/scoring-rules/formal-chart.mjs";

const node = (tick, extra = {}) => ({ tick, position: 0, size: 6, visible: true, operateType: "normal", ...extra });
const chart = (notes, extra = {}) => ({ notes, bpmEvents: [{ tick: 0, bpm: 125 }],
  timeSignatureEvents: [{ tick: 0, numerator: 4, denominator: 4 }], ...extra });

test("authored notes use native float32 bar time, not direct tick milliseconds", () => {
  const c = createFormalBarConverter(chart([], { bpmEvents: [{ tick: 0, bpm: 137 }] }));
  // Independent Python struct float32 arithmetic: seconds/bar=1.7518248558,
  // delta=64.072998046875, float(delta*1000)=64073.0; direct ticks floor 64072.
  assert.equal(c.clock.atTick(70224), 64072);
  assert.equal(c.atTick(70224).timeMs, 64073);
  assert.equal(reconstructFormalChart(chart([{ id: "a", type: "tap", ...node(70224) }],
    { bpmEvents: [{ tick: 0, bpm: 137 }] }))[0].timeMs, 64073);
});

test("signature boundary uses preceding tempo/bar event and anchors the following interval", () => {
  const c = createFormalBarConverter(chart([], { bpmEvents: [{ tick: 0, bpm: 120 }],
    timeSignatureEvents: [{ tick: 0, numerator: 2, denominator: 4 }, { tick: 960, numerator: 4, denominator: 4 }] }));
  assert.deepEqual(c.atTick(960), { bar: 1, progress: 0, timeMs: 1000 });
  assert.deepEqual(c.atTick(1200), { bar: 1, progress: 0.125, timeMs: 1250 });
});

test("long connections preserve trace weight; middle flicks become connections; hidden nodes do not score", () => {
  const events = reconstructFormalChart(chart([{ id: "long", type: "long", nodes: [node(0),
    node(240, { operateType: "flick" }), node(480, { visible: false }),
    node(720, { operateType: "trace" }), node(960)] }]));
  assert.deepEqual(events.map((e) => [e.timeMs, e.type]), [[0, 20], [240, 21], [480, 120], [719, 63], [960, 22]]);
});

test("guide overlap consumes one single and auto guide controls score without periodic combos", () => {
  const events = reconstructFormalChart(chart([{ id: "single", type: "flick", ...node(0) },
    { id: "guide", type: "guide", nodes: [node(0, { visible: false }),
      node(80, { position: null, size: null, visible: false }), node(960, { operateType: "trace" })] }]));
  assert.deepEqual(events.map((e) => e.type), [102, 63, 105]);
  assert.ok(events.every((e) => e.noteId === "guide"));
});

test("identical endpoints merge, while each incoming long retains its periodic combos", () => {
  const lines = [0, 12].map((position, i) => ({ id: `long-${i}`, type: "long",
    nodes: [node(0, { position }), node(720, { position: 6 })] }));
  const events = reconstructFormalChart(chart(lines));
  assert.equal(events.length, 7);
  assert.equal(events.filter((e) => e.type === 22).length, 1);
  assert.equal(events.filter((e) => e.type === 120).length, 4);
  lines[1].nodes[1].critical = true;
  assert.equal(reconstructFormalChart(chart(lines)).length, 8);
});

test("last combo at exactly 15000/BPM from end is included; just inside is skipped", () => {
  const build = (end) => reconstructFormalChart(chart([{ id: "long", type: "long", nodes: [node(0), node(end)] }], { bpmEvents: [{ tick: 0, bpm: 120 }] }));
  assert.equal(build(360).filter((e) => e.type === 120).length, 1);
  assert.equal(build(359).filter((e) => e.type === 120).length, 0);
});

test("legacy heuristic comboEvents cannot affect reconstructed scoring events", () => {
  const c = chart([{ id: "tap", type: "tap", ...node(480) }]);
  assert.deepEqual(reconstructFormalChart(c), reconstructFormalChart({ ...c, comboEvents: [{ garbage: true }] }));
});
