import assert from 'node:assert/strict';
import test from 'node:test';
import { upperHiddenWindow } from '../src/lib/auto-stage-visibility.mjs';

const frame = { horizonY: 40, judgementY: 440 };
test('zero height disables the mask regardless of fade range', () => {
  assert.equal(upperHiddenWindow(frame), null);
  assert.equal(upperHiddenWindow(frame, 0, 30), null);
});

test('height and fade use track space and scale together on resize', () => {
  assert.deepEqual(upperHiddenWindow(frame, 40, 15), { start: 200, end: 260 });
  assert.deepEqual(upperHiddenWindow({ horizonY: 20, judgementY: 220 }, 40, 15), { start: 100, end: 130 });
});

test('hard cutoff is supported and maximum hiding leaves the judgement area visible', () => {
  assert.deepEqual(upperHiddenWindow(frame, 50, 0), { start: 240, end: 240 });
  const maximum = upperHiddenWindow(frame, 80, 30);
  assert.ok(maximum.end < frame.judgementY);
  assert.deepEqual(upperHiddenWindow(frame, 500, 100), maximum);
});
