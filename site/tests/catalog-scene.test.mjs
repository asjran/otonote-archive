import assert from 'node:assert/strict';
import test from 'node:test';
import { pickCatalogScene } from '../src/lib/catalog-scene.mjs';
const scenes = [{id:'a'}, {id:'b'}, {id:'c'}];
test('scene selection handles empty and single-image releases', () => {
  assert.equal(pickCatalogScene([], 'a'), undefined);
  assert.equal(pickCatalogScene([scenes[0]], 'a'), scenes[0]);
});
test('every candidate can be chosen on a first visit', () => {
  assert.deepEqual([0, .4, .9].map(value => pickCatalogScene(scenes, null, () => value).id), ['a','b','c']);
});
test('refresh or shuffle excludes the previous scene without mutating candidates', () => {
  assert.equal(pickCatalogScene(scenes, 'b', () => 0).id, 'a');
  assert.equal(pickCatalogScene(scenes, 'b', () => .99).id, 'c');
  assert.deepEqual(scenes.map(scene => scene.id), ['a','b','c']);
});

const { turnCatalogPage } = await import('../src/lib/catalog-scene.mjs');

function paperFixture() {
  const events = [];
  let finish, cancel, markStarted;
  const started = new Promise(resolve => { markStarted = resolve; });
  const finished = new Promise((resolve, reject) => { finish = resolve; cancel = reject; });
  const sheet = {
    removeAttribute() {}, setAttribute() {}, querySelectorAll() { return []; },
    animate() { events.push('animate'); markStarted(); return { finished }; },
    remove() { events.push('remove'); }
  };
  const page = { animate() {}, cloneNode() { return sheet; }, append() { events.push('append'); } };
  return { page, events, finish, cancel, started };
}

test('turning preserves old paper until the reveal completes', async () => {
  const fixture = paperFixture();
  let done = false;
  const turn = turnCatalogPage(fixture.page, () => fixture.events.push('commit'), true).then(() => { done = true; });
  await fixture.started;
  assert.deepEqual(fixture.events, ['append', 'commit', 'animate']);
  await Promise.resolve();
  assert.equal(done, false);
  fixture.finish();
  await turn;
  assert.deepEqual(fixture.events, ['append', 'commit', 'animate', 'remove']);
});

test('cancelled animation removes the old sheet and completes', async () => {
  const fixture = paperFixture();
  const turn = turnCatalogPage(fixture.page, () => {}, true);
  await fixture.started;
  fixture.cancel(new Error('Animation cancelled'));
  await turn;
  assert.equal(fixture.events.at(-1), 'remove');
});

test('reduced-motion and unsupported browsers swap without an overlay', async () => {
  const fixture = paperFixture();
  let commits = 0;
  await turnCatalogPage(fixture.page, () => commits++, false);
  await turnCatalogPage(null, () => commits++, true);
  assert.equal(commits, 2);
  assert.deepEqual(fixture.events, []);
});


test('the old sheet is decoded before changing the visible scene', async () => {
  const fixture = paperFixture();
  let decodeOld;
  const ready = new Promise(resolve => { decodeOld = resolve; });
  const sheet = fixture.page.cloneNode();
  sheet.querySelectorAll = selector => selector === 'img' ? [{ decode: () => ready }] : [];
  const turn = turnCatalogPage(fixture.page, () => fixture.events.push('commit'), true);
  assert.equal(fixture.events.includes('commit'), false, 'new image was exposed before the old overlay decoded');
  decodeOld();
  await fixture.started;
  fixture.finish();
  await turn;
});

test('the prepared overlay gets a paint opportunity before the scene changes', async () => {
  const fixture = paperFixture();
  const frames = [];
  fixture.page.ownerDocument = { defaultView: { requestAnimationFrame(callback) { frames.push(callback); } } };
  const turn = turnCatalogPage(fixture.page, () => fixture.events.push('commit'), true);
  await Promise.resolve();
  assert.deepEqual(fixture.events, ['append']);
  frames.shift()(0);
  assert.equal(fixture.events.includes('commit'), false);
  frames.shift()(16);
  await fixture.started;
  fixture.finish();
  await turn;
});

test('an undecodable old copy falls back without hiding the current page', async () => {
  const fixture = paperFixture();
  fixture.page.cloneNode().querySelectorAll = selector => selector === 'img'
    ? [{ decode: () => Promise.reject(new Error('Decode failed')) }] : [];
  await turnCatalogPage(fixture.page, () => fixture.events.push('commit'), true);
  assert.deepEqual(fixture.events, ['commit']);
});
