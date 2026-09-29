import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
const catalog = JSON.parse(await readFile(new URL('../src/data/immersive-scenes.json', import.meta.url), 'utf8'));
const publicFile = path => new URL(`../public${path}`, import.meta.url);

test('all catalogued scenes have complete device or CDN animation packages', async () => {
  assert.equal(catalog.scenes.length, 39);
  assert.equal(new Set(catalog.scenes.map(s => s.id)).size, 39);
  assert.equal(new Set(catalog.scenes.map(s => s.background)).size, 19);
  for (const scene of catalog.scenes) {
    assert.ok(catalog.bands.some(b => b.id === scene.bandId));
    assert.ok((await readFile(publicFile(scene.poster))).length > 0);
    assert.equal(!!scene.assetRoot, scene.missingBundles === 0);
  }
  assert.equal(catalog.scenes.filter(s => s.assetRoot).length, 39);
});

test('playable packages have intact resources and every character animation exists', async () => {
  for (const scene of catalog.scenes.filter(s => s.assetRoot)) {
    const manifest = JSON.parse(await readFile(publicFile(scene.assetRoot + 'manifest.json'), 'utf8'));
    assert.equal(manifest.sceneId, scene.id);
    for (const file of manifest.files) {
      const bytes = await readFile(publicFile(scene.assetRoot + file.path));
      assert.equal(bytes.length, file.bytes, file.path);
      assert.equal(createHash('sha256').update(bytes).digest('hex'), file.sha256, file.path);
    }
    const geometry = JSON.parse(await readFile(publicFile(scene.assetRoot + 'scene.json'), 'utf8'));
    const ids = new Set(geometry.nodes.map(n => n.id));
    for (const node of geometry.nodes) {
      assert.ok(node.parent === '0' || ids.has(node.parent), `${scene.id}: missing parent ${node.parent}`);
      if (!node.spine) continue;
      if (node.spineFormat === 'binary') {
        assert.ok((await readFile(publicFile(scene.assetRoot + node.spine + '.skel'))).length > 0);
      } else {
        const skeleton = JSON.parse(await readFile(publicFile(scene.assetRoot + node.spine + '.json'), 'utf8'));
        if (node.animation) assert.ok(skeleton.animations[node.animation], `${node.spine}: missing animation`);
      }
    }
  }
});
