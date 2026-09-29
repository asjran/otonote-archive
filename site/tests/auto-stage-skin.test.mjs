import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createGameSkin, gameSkinUrls } from '../src/lib/auto-stage-skin.mjs';
const manifest = JSON.parse(await readFile(new URL('../src/data/auto-stage-skin.json', import.meta.url)));

test('the game skin includes every referenced texture with verified public bytes', async () => {
  const skin = createGameSkin(manifest);
  const urls = gameSkinUrls(skin);
  assert.equal(urls.length, Object.keys(manifest.images).length);
  for (const url of urls) {
    const record = Object.values(manifest.images).find(x => x.url === url);
    const bytes = await readFile(new URL(`../public${url}`, import.meta.url));
    assert.equal(bytes.length, record.bytes);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), record.sha256);
  }
});

test('region builds prefix every game texture and retain separate note families', () => {
  const skin = createGameSkin(manifest, '/global/en/');
  assert.ok(gameSkinUrls(skin).every(url => url.startsWith('/global/en/auto-stage/')));
  assert.notEqual(skin.theme.noteSkin.trace.centerUrl, skin.theme.noteSkin.flick.centerUrl);
  assert.notEqual(skin.theme.noteSkin.slide.centerUrl, skin.theme.noteSkin.slideEnd.centerUrl);
  assert.equal(skin.comboSkin.digitUrls.length, 10);
  assert.throws(() => createGameSkin({ images: {} }), /Missing game skin texture/);
});
