import test from 'node:test';
import assert from 'node:assert/strict';
import { createMediaClock } from '../src/lib/media-clock.mjs';

function media() {
  return { currentTime: 0, paused: true, ended: false, playbackRate: 1,
    async play() { this.paused = false; }, pause() { this.paused = true; } };
}

function unloadedMedia() {
  const audio = new EventTarget();
  let decodedTime = 0;
  Object.assign(audio, {readyState: 0, paused: true, ended: false, playbackRate: 1,
    pause() { this.paused = true; },
    async play() {
      // A preload=none element can discard a seek made before its metadata.
      decodedTime = 0;
      this.readyState = 1;
      this.dispatchEvent(new Event('loadedmetadata'));
      this.paused = false;
    }
  });
  Object.defineProperty(audio, 'currentTime', {
    get: () => decodedTime,
    set: value => { if (audio.readyState > 0) decodedTime = value; }
  });
  return audio;
}

test('a shared position survives metadata loading on the first play', async () => {
  const audio = unloadedMedia(), clock = createMediaClock(audio);
  clock.load(100);
  clock.seek(10);
  assert.equal(clock.time(), 10, 'the chart keeps the requested position while audio loads');
  await clock.play();
  assert.equal(audio.currentTime, 10, 'the initial media reset cannot discard the shared position');
  assert.equal(clock.time(), 10);
  audio.currentTime = 10.17;
  assert.equal(clock.time(), 10.17, 'after the seek, decoded audio time remains authoritative');
});

test('only the latest unloaded seek is applied and a chart reload clears it', async () => {
  const audio = unloadedMedia(), clock = createMediaClock(audio);
  clock.load(100); clock.seek(10); clock.seek(40);
  await clock.play();
  assert.equal(audio.currentTime, 40);
  audio.readyState = 0;
  clock.seek(70); clock.load(90);
  await clock.play();
  assert.equal(audio.currentTime, 0, 'the previous chart cannot restore a stale seek');
});

test('disposing an unloaded clock removes its pending metadata seek', () => {
  const audio = unloadedMedia(), clock = createMediaClock(audio);
  clock.load(100); clock.seek(10); clock.destroy();
  audio.readyState = 1;
  audio.currentTime = 35;
  audio.dispatchEvent(new Event('loadedmetadata'));
  assert.equal(audio.currentTime, 35);
  assert.equal(audio.paused, true);
});

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
