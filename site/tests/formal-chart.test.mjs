import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createFormalBarConverter, reconstructFormalChart, formalNoteCreationPriority, formalLineNodeGeometry } from "../src/lib/scoring-rules/formal-chart.mjs";

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

test("creation priority and automatic-node easing match unchanged native ARM64 functions", () => {
  const data = JSON.parse(readFileSync(new URL("./fixtures/formal-chart-native-kernels.json", import.meta.url)));
  for (const row of data.priorities) assert.equal(formalNoteCreationPriority(row.type), row.priority);
  for (const row of data.easing) {
    const kind = ["linear", "out", "in"][row.type];
    const line = { nodes: [node(0, { position: 0, size: 1, easing: kind, easingRight: kind }),
      node(row.progress * 128, { position: null }), node(128, { position: 1, size: 1 })] };
    assert.equal(formalLineNodeGeometry(line, 1).position, row.value);
  }
});

test("periodic combos match native MoveNext across fractional starts and time signatures", () => {
  const data = JSON.parse(readFileSync(new URL("./fixtures/formal-chart-native-kernels.json", import.meta.url)));
  for (const row of data.intervals) {
    const events = reconstructFormalChart(chart([{ id: "line", type: "long", nodes: [node(row.startTick), node(row.endTick)] }],
      { bpmEvents: [{ tick: 0, bpm: 120 }], timeSignatureEvents: [{ tick: 0, numerator: row.beats, denominator: 4 }] }));
    assert.deepEqual(events.filter((e) => e.type === 120).map(({ bar, progress, timeMs }) => ({ bar, progress, timeMs })), row.points);
  }
});

test("same-position creation prioritizes long starts before singles", () => {
  const events = reconstructFormalChart(chart([{ id: "tap", type: "tap", ...node(0) },
    { id: "long", type: "long", nodes: [node(0, { position: 6 }), node(480)] }]));
  assert.deepEqual(events.slice(0, 2).map((e) => [e.noteId, e.nativeNoteId]), [["long", 1], ["tap", 2]]);
  assert.equal(events.find((e) => e.type === 120).nativeNoteId, 10001);
});

test("same-position lane groups preserve insertion order before stable type ordering", () => {
  const events = reconstructFormalChart(chart([
    { id: "a", type: "tap", ...node(0) }, { id: "b", type: "tap", ...node(0, { position: 12 }) },
    { id: "c", type: "trace", ...node(0) },
  ]));
  assert.deepEqual(events.map((e) => [e.noteId, e.nativeNoteId, e.sourceIndex]), [["a", 1, 0], ["c", 2, 2], ["b", 3, 1]]);
});

test("hidden authored nodes reserve IDs and are created before scoring connections", () => {
  const diagnostics = {};
  const events = reconstructFormalChart(chart([{ id: "tap", type: "tap", ...node(240) },
    { id: "line", type: "long", nodes: [node(0), node(240, { visible: false }), node(480)] }]), diagnostics);
  assert.equal(events.find((e) => e.noteId === "tap").nativeNoteId, 3);
  assert.equal(events.find((e) => e.type === 22).nativeNoteId, 4);
  assert.equal(diagnostics.nativeAuthoredNoteCount, 4);
});

test("merged starts retain distinct line ownership and periodic combo IDs", () => {
  const diagnostics = {};
  const events = reconstructFormalChart(chart([0, 12].map((position, i) => ({ id: `line-${i}`, type: "long",
    nodes: [node(0), node(480, { position })] }))), diagnostics);
  assert.equal(events.filter((e) => e.type === 20).length, 1);
  assert.deepEqual(events.find((e) => e.type === 20).nativeLineIds, [1, 2]);
  assert.deepEqual(events.filter((e) => e.type === 120).map((e) => e.nativeNoteId), [10001, 10002]);
  assert.equal(diagnostics.nativeLineCount, 2);
});

test("skipped periodic candidates leave native ID gaps", () => {
  const events = reconstructFormalChart(chart([{ id: "line", type: "long", nodes: [node(0), node(300), node(1200)] }]));
  assert.deepEqual(events.filter((e) => e.type === 120).map((e) => e.nativeNoteId), [20001, 30001, 40001]);
});

test("guide starts reserve note IDs but use an independent line-ID counter", () => {
  const events = reconstructFormalChart(chart([
    { id: "long", type: "long", nodes: [node(240), node(720)] },
    { id: "guide", type: "guide", nodes: [node(0), node(960, { operateType: "trace" })] },
  ]));
  assert.equal(events.find((e) => e.type === 120).nativeNoteId, 10001);
  assert.equal(events.find((e) => e.type === 20).nativeNoteId, 2);
  assert.deepEqual(events.find((e) => e.type === 105).nativeLineIds, [10001]);
});

test("merged endpoint ownership follows native start-time order rather than source line order", () => {
  const events = reconstructFormalChart(chart([
    { id: "late", type: "long", nodes: [node(240), node(960)] },
    { id: "early", type: "long", nodes: [node(0), node(960)] },
  ]));
  const end = events.find((e) => e.type === 22);
  assert.equal(end.noteId, "early");
  assert.deepEqual(end.nativeLineIds, [1, 2]);
  assert.equal(new Set(events.map((e) => e.nativeNoteId)).size, events.length);
});
