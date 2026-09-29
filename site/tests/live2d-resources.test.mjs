import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createResourceCache, loadModelResources, readResource, validateManifest } from '../src/lib/live2d-resources.mjs';

const digest = text => createHash('sha256').update(text).digest('hex');
function fixture() {
  const files = { 'model.model3.json': '{}', 'texture.png': 'texture-bytes' };
  const resources = Object.entries(files).map(([file, value]) => ({ file, bytes: value.length, sha256: digest(value) }));
  const manifest = { model: 'model.model3.json', resources, totalBytes: resources.reduce((n, r) => n + r.bytes, 0) };
  return { files, manifest };
}

test('download progress uses streamed bytes, and a completed cache avoids redownloading', async () => {
  const { files, manifest } = fixture();
  const cache = createResourceCache(1024), requests = [], progress = [];
  const fetcher = async url => {
    const name = new URL(url).pathname.split('/').pop(); requests.push(name);
    if (name === 'manifest.json') return new Response(JSON.stringify(manifest));
    const bytes = new TextEncoder().encode(files[name]);
    return new Response(new ReadableStream({ start(c) { c.enqueue(bytes.slice(0, 1)); c.enqueue(bytes.slice(1)); c.close(); } }));
  };
  const first = await loadModelResources('https://local/model/', { fetcher, resourceCache: cache, onProgress: p => progress.push(p) });
  assert.equal(first.blobs.size, 2);
  const values = progress.filter(p => p.phase === 'download').map(p => p.loaded);
  assert.ok(values.some(n => n > 0 && n < manifest.totalBytes));
  assert.deepEqual(values, [...values].sort((a, b) => a - b));
  assert.equal(values.at(-1), manifest.totalBytes);
  await loadModelResources('https://local/model/', { fetcher, resourceCache: cache, onProgress: p => progress.push(p) });
  assert.equal(requests.filter(n => n === 'texture.png').length, 1);
  assert.equal(progress.at(-1).cached, manifest.totalBytes);
});

test('checksum failure is not cached and retry recovers', async () => {
  const { files, manifest } = fixture();
  const cache = createResourceCache(1024);
  let broken = true;
  const fetcher = async url => {
    const name = new URL(url).pathname.split('/').pop();
    if (name === 'manifest.json') return new Response(JSON.stringify(manifest));
    return new Response(broken && name === 'texture.png' ? 'corrupt-bytes' : files[name]);
  };
  await assert.rejects(loadModelResources('https://local/', { fetcher, resourceCache: cache }), /checksum mismatch/);
  broken = false;
  const result = await loadModelResources('https://local/', { fetcher, resourceCache: cache });
  assert.equal(await result.blobs.get('texture.png').text(), 'texture-bytes');
});

test('cancellation aborts downloads without publishing partial files', async () => {
  const { manifest } = fixture();
  const controller = new AbortController(), cache = createResourceCache(1024);
  const fetcher = async (url, { signal }) => {
    if (url.endsWith('manifest.json')) return new Response(JSON.stringify(manifest));
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(signal.reason), { once: true });
      queueMicrotask(() => controller.abort(new DOMException('Cancelled', 'AbortError')));
    });
  };
  await assert.rejects(loadModelResources('https://local/', { signal: controller.signal, fetcher, resourceCache: cache }), { name: 'AbortError' });
  assert.equal(cache.bytes, 0);
});

test('HTTP errors and idle timeouts remain errors', async () => {
  await assert.rejects(readResource('https://local/bad', { fetcher: async () => new Response('', { status: 404 }) }), /HTTP 404/);
  await assert.rejects(readResource('https://local/slow', { timeoutMs: 10,
    fetcher: (_, { signal }) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason))) }), /timed out/);
});

test('cache stays within its byte budget with LRU eviction', () => {
  const cache = createResourceCache(5);
  cache.set('a', new Blob(['aa'])); cache.set('b', new Blob(['bb'])); cache.get('a'); cache.set('c', new Blob(['cc']));
  assert.equal(cache.get('b'), undefined); assert.ok(cache.get('a')); assert.equal(cache.bytes, 4);
  cache.set('large', new Blob(['123456'])); assert.equal(cache.bytes, 4);
});

test('manifest rejects traversal, duplicate files and incorrect totals', () => {
  const { manifest } = fixture();
  assert.throws(() => validateManifest({ ...manifest, totalBytes: 1 }), /totals/);
  assert.throws(() => validateManifest({ ...manifest, resources: [...manifest.resources, manifest.resources[0]] }), /entry/);
  assert.throws(() => validateManifest({ ...manifest, resources: [{ ...manifest.resources[0], file: '../secret' }] }), /entry/);
});

function packedFixture() {
  const files = { 'model.model3.json': '{}\n', 'motion.json': '{"label":"灯"}\n',
    'model.moc3': 'MOC3', 'texture0.png': 'png0', 'texture1.png': 'png1' };
  const resources = Object.entries(files).map(([file, value]) => ({ file,
    bytes: Buffer.byteLength(value), sha256: digest(value) }));
  const names = resources.filter(r => r.file.endsWith('.json')).map(r => r.file);
  const pack = JSON.stringify({ schemaVersion: 1, files: Object.fromEntries(names.map(n => [n, files[n]])) });
  const manifest = { model: 'model.model3.json', resources, totalBytes: resources.reduce((n, r) => n + r.bytes, 0),
    jsonBundle: { file: 'json-bundle.json', bytes: Buffer.byteLength(pack), sha256: digest(pack), files: names } };
  return { files, pack, manifest };
}

test('packed JSON preserves exact bytes, starts textures immediately and keeps four workers', async () => {
  const { files, pack, manifest } = packedFixture(), requests = [], progress = [];
  const cache = createResourceCache();
  let active = 0, peak = 0;
  const fetcher = async url => {
    const name = new URL(url).pathname.slice(1); requests.push(name);
    if (name === 'manifest.json') return new Response(JSON.stringify(manifest));
    active++; peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 10)); active--;
    return new Response(name === manifest.jsonBundle.file ? pack : files[name]);
  };
  const result = await loadModelResources('https://local/', { fetcher, resourceCache: cache, onProgress: p => progress.push(p) });
  assert.equal(requests.length, 5); assert.equal(peak, 4);
  assert.ok(!requests.includes('motion.json'));
  for (const [name, text] of Object.entries(files)) assert.equal(await result.blobs.get(name).text(), text);
  const values = progress.filter(p => p.phase === 'download').map(p => p.loaded);
  assert.deepEqual(values, [...values].sort((a, b) => a - b));
  assert.equal(values.at(-1), manifest.totalBytes);
  await loadModelResources('https://local/', { fetcher, resourceCache: cache });
  assert.equal(requests.length, 6);
  // Partial cache eviction still uses one bundle and returns the full model.
  const partial = createResourceCache();
  partial.set('https://local/model.model3.json#' + manifest.resources[0].sha256, result.blobs.get(manifest.model));
  const again = await loadModelResources('https://local/', { fetcher, resourceCache: partial });
  assert.equal(again.blobs.size, manifest.resources.length);
});

test('corrupt bundle and corrupt packed member are rejected without caching partial JSON', async () => {
  for (const mode of ['bundle', 'member', 'missing']) {
    const { files, pack, manifest } = packedFixture(), cache = createResourceCache();
    const payload = JSON.parse(pack);
    if (mode === 'missing') delete payload.files['motion.json'];
    else payload.files['motion.json'] = '{}';
    const broken = JSON.stringify(payload);
    manifest.jsonBundle.bytes = Buffer.byteLength(broken);
    if (mode !== 'bundle') manifest.jsonBundle.sha256 = digest(broken);
    const fetcher = async url => {
      const name = new URL(url).pathname.slice(1);
      return new Response(name === 'manifest.json' ? JSON.stringify(manifest) : name === manifest.jsonBundle.file ? broken : files[name]);
    };
    await assert.rejects(loadModelResources('https://local/', { fetcher, resourceCache: cache }), /mismatch|contents/);
    assert.equal(cache.get('https://local/model.model3.json#' + manifest.resources[0].sha256), undefined);
  }
});

test('invalid bundle membership and paths fail before any resource download', () => {
  for (const patch of [{ file: '../pack.json' }, { files: ['texture0.png'] },
    { files: ['motion.json', 'motion.json'] }, { files: ['missing.json'] }, { sha256: 'bad' }]) {
    const { manifest } = packedFixture();
    Object.assign(manifest.jsonBundle, patch);
    assert.throws(() => validateManifest(manifest), /bundle/);
  }
});

test('cancelling a bundle aborts its stream and a fresh attempt can recover', async () => {
  const { files, pack, manifest } = packedFixture(), cache = createResourceCache(), controller = new AbortController();
  let cancelBundle = true;
  const fetcher = async (url, { signal }) => {
    const name = new URL(url).pathname.slice(1);
    if (name === 'manifest.json') return new Response(JSON.stringify(manifest));
    if (name === manifest.jsonBundle.file && cancelBundle) {
      return new Response(new ReadableStream({ start(c) {
        c.enqueue(new TextEncoder().encode(pack.slice(0, 10)));
        signal.addEventListener('abort', () => c.error(signal.reason), { once: true });
        queueMicrotask(() => controller.abort(new DOMException('Cancelled', 'AbortError')));
      } }));
    }
    return new Response(name === manifest.jsonBundle.file ? pack : files[name]);
  };
  await assert.rejects(loadModelResources('https://local/', { fetcher, resourceCache: cache, signal: controller.signal }), { name: 'AbortError' });
  assert.equal(cache.get('https://local/model.model3.json#' + manifest.resources[0].sha256), undefined);
  cancelBundle = false;
  assert.equal((await loadModelResources('https://local/', { fetcher, resourceCache: cache })).blobs.size, 5);
});
