import test from 'node:test';
import assert from 'node:assert/strict';
import { createMediaClock } from '../src/lib/media-clock.mjs';

function media() {
  return { currentTime: 0, paused: true, ended: false, playbackRate: 1,
    async play() { this.paused = false; }, pause() { this.paused = true; } };
}

test('media clock follows decoded audio time, including buffering and seek', async () => {
  const audio = media(), clock = createMediaClock(audio);
  clock.load(100); await clock.play();
  audio.currentTime = 5.25;
  assert.equal(clock.time(), 5.25);
  assert.equal(clock.time(), 5.25, 'time cannot advance when audio buffers');
  clock.seek(40); assert.equal(audio.currentTime, 40);
  clock.pause(); assert.equal(audio.paused, true); assert.equal(clock.playing, false);
  await clock.play(); assert.equal(clock.time(), 40);
  clock.setRate(1.5); assert.equal(audio.playbackRate, 1.5); assert.equal(clock.time(), 40);
});

test('end, restart and difficulty reload keep media and chart together', async () => {
  const audio = media(), clock = createMediaClock(audio);
  clock.load(100); audio.currentTime = 100; audio.ended = true;
  assert.equal(clock.playing, false);
  await clock.play(); assert.equal(audio.currentTime, 0);
  audio.ended = false; clock.seek(500); assert.equal(audio.currentTime, 100);
  clock.load(90); assert.equal(audio.currentTime, 0); assert.equal(audio.paused, true);
  clock.seek(-1); assert.equal(audio.currentTime, 0);
});

test('a rejected media play request is surfaced instead of silently running a chart', async () => {
  const audio = media(), clock = createMediaClock(audio);
  clock.load(100);
  audio.play = async () => { throw new Error('Media unavailable'); };
  await assert.rejects(clock.play(), /Media unavailable/);
  assert.equal(clock.playing, false); assert.equal(clock.time(), 0);
});
