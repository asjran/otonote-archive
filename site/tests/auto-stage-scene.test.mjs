import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeAutoTimeline } from '../src/lib/auto-timeline.mjs';
import { createAutoStageFrame } from '../src/lib/auto-stage-layout.mjs';
import { createAutoScene, lastComboEvent } from '../src/lib/auto-stage-scene.mjs';

const frame = createAutoStageFrame({ width: 1000, height: 560 });
const timeline = normalizeAutoTimeline({ duration: 12, skillTimings: [1], gekisouRanges: [{ start: 2, end: 5 }], notes: [
  { id: 'tap', type: 'tap', time: 1, position: 1, size: 3 },
  { id: 'trace', type: 'trace', time: 3, position: 4, size: 2 },
  { id: 'hold', type: 'long', nodes: [{ time: 2, position: 5, size: 4 }, { time: 4, position: 8, size: 4 }] }
], comboEvents: [{ time: 1, combo: 1 }, { time: 2, combo: 2 }, { time: 2.5, combo: 3 }, { time: 3, combo: 4 }, { time: 4, combo: 5 }] });
const options = { missions: [{ label: 'LUCK', type: 'luck' }] };

test('seeking into and out of a section derives its type and progress without replaying the start cue', () => {
  const middle = createAutoScene(timeline, frame, 4, options);
  assert.equal(middle.activeGekisou.label, 'LUCK');
  assert.equal(middle.activeGekisou.progress, 2 / 3);
  assert.equal(middle.activeCue, null);
  assert.equal(createAutoScene(timeline, frame, 5, options).activeGekisou, null);
  assert.equal(createAutoScene(timeline, frame, 1.5, options).activeGekisou, null);
});

test('hit effects occur after judgement, fade out, and do not linger after a backwards seek', () => {
  assert.equal(createAutoScene(timeline, frame, 0.99).hitEffects.length, 0);
  assert.deepEqual(createAutoScene(timeline, frame, 1.15).hitEffects.map(x => x.id), ['tap']);
  assert.equal(createAutoScene(timeline, frame, 1.31).hitEffects.length, 0);
  assert.equal(createAutoScene(timeline, frame, 0).judgementProgress, null);
  assert.equal(createAutoScene(timeline, frame, 0).combo, 0);
});

test('holds remain active between visible nodes and implicit combo ticks show judgement feedback', () => {
  const scene = createAutoScene(timeline, frame, 2.55, options);
  assert.equal(scene.heldNotes.length, 1);
  assert.equal(scene.heldNotes[0].y, frame.judgementY);
  assert.equal(scene.combo, 3);
  assert.ok(scene.judgementProgress > 0 && scene.judgementProgress < 0.2);
  assert.equal(createAutoScene(timeline, frame, 4).heldNotes.length, 0);
});

test('distant notes render before close notes, preserving distinct trace and hold endpoints', () => {
  const scene = createAutoScene(timeline, frame, 0.9);
  assert.ok(scene.markers.every((marker, i, markers) => i === 0 || markers[i - 1].depth >= marker.depth));
  assert.equal(scene.markers.find(x => x.id === 'trace').kind, 'trace');
  assert.equal(timeline.markers.find(x => x.id === 'hold:0').isEnd, false);
  assert.equal(timeline.markers.find(x => x.id === 'hold:1').isEnd, true);
  assert.equal(lastComboEvent(timeline, 0), null);
  assert.equal(lastComboEvent(timeline, 12).combo, 5);
});
