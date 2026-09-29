import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { createGameSkin, gameSkinUrls } from '../src/lib/auto-stage-skin.mjs';
import { createAutoStageRenderer } from '../src/lib/auto-stage-renderer.ts';
import { createAutoStageFrame } from '../src/lib/auto-stage-layout.mjs';

const skin = createGameSkin(JSON.parse(readFileSync(new URL('../src/data/auto-stage-skin.json', import.meta.url))));
const marker = { id: 'note', kind: 'tap', x: 200, y: 300, width: 100, centerX: 250, depth: 0.01 };
function render(scene, effects = true) {
  const draws = [];
  const images = new Map(gameSkinUrls(skin).map(url => [url, { url, complete: true, naturalWidth: 100, naturalHeight: 50 }]));
  const context = new Proxy({
    drawImage: (image, ...args) => draws.push({ url: image.url, args }),
    createLinearGradient: () => ({ addColorStop() {} }),
    createRadialGradient: () => ({ addColorStop() {} }),
  }, { get: (target, key) => target[key] ?? (() => {}) });
  createAutoStageRenderer({ images, comboSkin: skin.comboSkin, labels: {}, onSkinStateChange() {} }).render({
    context, frame: createAutoStageFrame({ width: 800, height: 400 }),
    profile: { mode: 'full', effects, laneGuides: true }, stageTheme: skin.theme,
    gameSettings: { backgroundBrightness: 75, laneOpacity: 78, guidelineOpacity: 50 },
    scene: { markers: [], longPaths: [], hitEffects: [], activeCue: null, combo: 0, ...scene },
  });
  return draws;
}

test('trace and long-note ends use their own game textures', () => {
  for (const [kind, isEnd, family] of [['trace', false, 'trace'], ['long-node', false, 'slide'], ['long-node', true, 'slideEnd']]) {
    const draws = render({ markers: [{ ...marker, kind, isEnd }] });
    const urls = draws.map(draw => draw.url);
    for (const url of Object.values(skin.theme.noteSkin[family])) assert.ok(urls.includes(url));
    assert.ok(!urls.includes(skin.theme.noteSkin.flick.centerUrl));
  }
});

test('approaching notes have no hit burst; post-hit particles animate and respect the effects switch', () => {
  const star = skin.theme.effectTextures.particleStarUrl;
  assert.equal(render({ markers: [marker] }).filter(draw => draw.url === star).length, 0);
  const atHit = render({ hitEffects: [{ ...marker, depth: 0 }] }).find(draw => draw.url === star);
  const fading = render({ hitEffects: [{ ...marker, depth: -0.02 }] }).find(draw => draw.url === star);
  assert.ok(fading.args[2] > atHit.args[2]);
  assert.equal(render({ hitEffects: [{ ...marker, depth: 0 }] }, false).filter(draw => draw.url === star).length, 0);
});

test('PERFECT feedback disappears when a seek leaves the judgement window', () => {
  const url = skin.theme.judgementUrl;
  assert.ok(render({ judgementProgress: 0.2 }).some(draw => draw.url === url));
  assert.ok(!render({ judgementProgress: null }).some(draw => draw.url === url));
});

test('note bodies and arrows scale together across viewport sizes and distance', () => {
  const note = { ...marker, kind: 'flick', direction: 'right', size: 6 };
  const bodyUrl = skin.theme.noteSkin.flickRight.centerUrl;
  const arrowUrl = skin.theme.noteSkin.arrows.right[1].url;
  const normal = render({ markers: [note] });
  const scaled = render({ markers: [{ ...note, width: note.width / 2, depth: 0.8 }] });
  for (const url of [bodyUrl, arrowUrl]) {
    const original = normal.find(draw => draw.url === url);
    const smaller = scaled.find(draw => draw.url === url);
    assert.ok(original && smaller);
    assert.equal(smaller.args[3], original.args[3] / 2);
  }
  const star = normal.find(draw => draw.url === skin.theme.noteSkin.overlays.flickRightDecorationUrl);
  assert.ok(star.args[2] < normal.find(draw => draw.url === bodyUrl).args[3]);
});

test('a visible interior hold node uses the connection body and diamond', () => {
  const urls = render({ markers: [{ ...marker, kind: 'long-node', nodeIndex: 1, isEnd: false }] }).map(draw => draw.url);
  assert.ok(urls.includes(skin.theme.noteSkin.slideConnection.centerUrl));
  assert.ok(urls.includes(skin.theme.noteSkin.overlays.slideConnectionUrl));
  assert.ok(!urls.includes(skin.theme.noteSkin.slide.centerUrl));
});

test('upper hidden masks the note layer while preserving the stage and judgement UI', () => {
  const calls = [];
  const makeContext = surface => new Proxy({
    canvas: { width: 1600, height: 800 },
    drawImage: image => calls.push({ surface, image }),
    createLinearGradient: () => ({ addColorStop() {} }),
    createRadialGradient: () => ({ addColorStop() {} }),
  }, { get: (target, key) => target[key] ?? (() => {}) });
  const context = makeContext('stage');
  const noteContext = makeContext('notes');
  const layer = { width: 0, height: 0, getContext: () => noteContext };
  const images = new Map(gameSkinUrls(skin).map(url => [url, { url, complete: true, naturalWidth: 100, naturalHeight: 50 }]));
  const renderer = createAutoStageRenderer({ images, comboSkin: skin.comboSkin, labels: {}, onSkinStateChange() {}, createNoteLayer: () => layer });
  const input = {
    context, frame: createAutoStageFrame({ width: 800, height: 400 }),
    profile: { mode: 'full', effects: true, laneGuides: true }, stageTheme: skin.theme,
    gameSettings: { hiddenHeight: 40, hiddenFade: 10, backgroundBrightness: 75, laneOpacity: 78, guidelineOpacity: 50 },
    scene: { markers: [marker], longPaths: [], hitEffects: [], activeCue: null, combo: 5, judgementProgress: 0.2 }
  };
  renderer.render(input);
  assert.equal(layer.width, 1600);
  assert.equal(layer.height, 800);
  assert.ok(calls.some(call => call.surface === 'notes' && call.image.url === skin.theme.noteSkin.tap.centerUrl));
  for (const url of [skin.theme.backgroundUrl, skin.theme.judgementUrl, skin.comboSkin.digitUrls[5]]) {
    assert.ok(calls.some(call => call.surface === 'stage' && call.image.url === url));
    assert.ok(!calls.some(call => call.surface === 'notes' && call.image.url === url));
  }
  calls.length = 0;
  renderer.render({ ...input, gameSettings: { ...input.gameSettings, hiddenHeight: 0 } });
  assert.ok(calls.some(call => call.surface === 'stage' && call.image.url === skin.theme.noteSkin.tap.centerUrl));
  assert.ok(!calls.some(call => call.image === layer));
});
