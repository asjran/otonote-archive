import test from 'node:test';
import assert from 'node:assert/strict';
import { createImmersivePlayback, isImmersiveTap } from '../src/lib/immersive-playback.mjs';
import { immersiveClientProfile, verifyImmersiveClientProfile } from '../src/lib/immersive-profile.mjs';
import { createHash } from 'node:crypto';

function fixture() {
  const times = {};
  const layers = ['anon-back', 'anon-front', 'tomori-back', 'tomori-front', 'soyo', 'table']
    .map(id => ({ id, duration: 4, apply(time) { times[id] = time; } }));
  const playback = createImmersivePlayback(layers, [
    { id: 2, nodes: ['anon-back', 'anon-front'] }, { id: 1, nodes: ['tomori-back', 'tomori-front'] }, { id: 4, nodes: ['soyo'] }
  ]);
  playback.seek(0);
  return { playback, times };
}

test('entrance plays once and holds every final frame without wrapping', () => {
  const { playback, times } = fixture();
  playback.advance(3.9); assert.equal(playback.playing, true);
  playback.advance(.2); assert.equal(playback.playing, false);
  playback.advance(20);
  assert.deepEqual(Object.values(times), [4, 4, 4, 4, 4, 4]);
  assert.equal(playback.time, 4);
});

test('character replays keep paired layers together without resetting other people or the table', () => {
  const { playback, times } = fixture();
  playback.seek(4); assert.equal(playback.replay(2), true); playback.advance(.75);
  assert.deepEqual(times, { 'anon-back': .75, 'anon-front': .75, 'tomori-back': 4, 'tomori-front': 4, soyo: 4, table: 4 });
  playback.replay(1); playback.advance(.25);
  assert.equal(times['anon-front'], 1); assert.equal(times['tomori-back'], .25); assert.equal(times['tomori-front'], .25);
  assert.equal(times.soyo, 4); assert.equal(times.table, 4); assert.equal(playback.time, 4);
});

test('export sampling and cancellation can restore each independent character clock', () => {
  const { playback, times } = fixture();
  playback.seek(4); playback.replay(4); playback.advance(1); playback.replay(2); playback.advance(.5);
  const snapshot = playback.snapshot(), before = { ...times };
  for (let time = 0; time <= 4; time += .25) playback.seek(time);
  playback.restore(snapshot); assert.deepEqual(times, before); assert.equal(playback.playing, true);
  playback.advance(.5); assert.equal(times.soyo, 2); assert.equal(times['anon-front'], 1); assert.equal(times['tomori-front'], 4);
});

test('a global seek and replay reset every person coherently; unknown actors cannot affect the scene', () => {
  const { playback, times } = fixture();
  playback.seek(4); playback.replay(2); playback.advance(1); playback.seek(2);
  assert.deepEqual(Object.values(times), [2, 2, 2, 2, 2, 2]);
  assert.equal(playback.replay(999), false); assert.equal(playback.replay('scene'), false);
  playback.seek(0); assert.deepEqual(Object.values(times), [0, 0, 0, 0, 0, 0]);
});

test('an incomplete or overlapping character binding fails instead of splitting her layers', () => {
  const layer = { id: 'body', duration: 4, apply() {} };
  assert.throws(() => createImmersivePlayback([layer], [{ id: 1, nodes: ['body', 'missing'] }]), /layers-unavailable/);
  assert.throws(() => createImmersivePlayback([layer], [{ id: 1, nodes: ['body'] }, { id: 2, nodes: ['body'] }]), /layer-overlap/);
});

test('tap tolerance permits a small finger movement, while dragging does not replay a character', () => {
  assert.equal(isImmersiveTap({ x: 0, y: 0 }, { x: 3, y: 4 }), true);
  assert.equal(isImmersiveTap({ x: 0, y: 0 }, { x: 7, y: 0 }), false);
});

test('only the audited lobby package advertises a native profile', () => {
  assert.ok(immersiveClientProfile({ id: 10007, assetRoot: '/content/v1/public/immersive/mygo-lobby-v1/' }));
  assert.ok(immersiveClientProfile({ id: 10007, assetRoot: '/content/v1/public/immersive/scene-10007-v1/' }));
  assert.equal(immersiveClientProfile({ id: 10008, assetRoot: '/immersive/mygo-lobby-v1/' }), null);
  assert.equal(immersiveClientProfile({ id: 10007, assetRoot: '/immersive/new-package/' }), null);
});

test('native profile checks actual scene and resource bytes, even if their advertised size is unchanged', async () => {
  const hash = text => createHash('sha256').update(text).digest('hex');
  const profile = { id: 10007, packages: [{ 'scene.json': hash('scene'), 'body.json': hash('body') }] };
  const resources = { manifest: { sceneId: 10007 }, sceneBlob: new Blob(['scene']), blobs: new Map([['body.json', new Blob(['body'])]]) };
  assert.equal(await verifyImmersiveClientProfile(resources, profile), profile);
  resources.blobs.set('body.json', new Blob(['evil']));
  await assert.rejects(verifyImmersiveClientProfile(resources, profile), /profile-mismatch/);
  resources.blobs.clear();
  await assert.rejects(verifyImmersiveClientProfile(resources, profile), /profile-mismatch/);
  resources.manifest.sceneId = 10008;
  await assert.rejects(verifyImmersiveClientProfile(resources, profile), /profile-mismatch/);
});
