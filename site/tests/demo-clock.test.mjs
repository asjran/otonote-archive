import test from 'node:test';
import assert from 'node:assert/strict';
import { createDemoClock } from '../src/lib/demo-clock.mjs';

test('silent demo pauses, resumes, seeks and changes speed without time jumps', () => {
  let now = 0;
  const clock = createDemoClock(() => now);
  clock.load(120);
  clock.play(); now = 5000; assert.equal(clock.time(), 5);
  clock.pause(); now = 10000; assert.equal(clock.time(), 5);
  clock.play(); now = 12000; assert.equal(clock.time(), 7);
  clock.setRate(0.5); now = 14000; assert.equal(clock.time(), 8);
  clock.seek(30); now = 16000; assert.equal(clock.time(), 31);
  clock.seek(119); now = 20000; assert.equal(clock.time(), 120);
  assert.equal(clock.playing, false);
  clock.play(); assert.equal(clock.time(), 0);
  clock.load(60); assert.equal(clock.playing, false); assert.equal(clock.time(), 0);
});
