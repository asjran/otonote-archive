import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { createModelZip, exportModel } from '../src/lib/live2d-export.mjs';
import { createResourceCache } from '../src/lib/live2d-resources.mjs';

async function fixture() {
  const settings = { FileReferences: { Moc: 'model.moc3', Textures: ['textures/texture.png'],
    Motions: { main: [{ File: 'motions/idle.motion3.json' }] }, Expressions: [{ Name: 'smile', File: 'expressions/smile.exp3.json' }], Physics: 'model.physics3.json' } };
  const files = new Map(Object.entries({
    'model.model3.json': JSON.stringify(settings), 'model.moc3': 'MOC3-test',
    'textures/texture.png': 'a'.repeat(1024 * 1024 + 3), 'motions/idle.motion3.json': '{}',
    'expressions/smile.exp3.json': '{}', 'model.physics3.json': '{}',
  }).map(([name, value]) => [name, new Blob([value])]));
  const resources = await Promise.all([...files].map(async ([file, blob]) => ({ file, bytes: blob.size,
    sha256: createHash('sha256').update(Buffer.from(await blob.arrayBuffer())).digest('hex') })));
  return { blobs: files, manifest: { model: 'model.model3.json', resources, totalBytes: resources.reduce((n, r) => n + r.bytes, 0) } };
}

test('export is a standard ZIP with valid CRCs, unchanged checksums and complete relative references', async () => {
  const resources = await fixture(), progress = [];
  resources.manifest.jsonBundle = { file: 'json-bundle.json', bytes: 100, sha256: 'a'.repeat(64), files: ['model.model3.json'] };
  const zip = await createModelZip(resources, { onProgress: p => progress.push(p) });
  const result = spawnSync('python3', ['-c', `
import sys,io,zipfile,json,hashlib
z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()))
assert z.testzip() is None
m=json.loads(z.read('manifest.json'))
assert 'jsonBundle' not in m
for r in m['resources']:
    assert hashlib.sha256(z.read(r['file'])).hexdigest()==r['sha256']
s=json.loads(z.read(m['model']))['FileReferences']
refs=[s['Moc'],*s['Textures'],s['Physics'],*[r['File'] for r in s['Expressions']],*[r['File'] for g in s['Motions'].values() for r in g]]
assert all(r in z.namelist() for r in refs)
assert '运行时模型' in z.read('README.txt').decode('utf-8')
print(len(z.namelist()))
`], { input: Buffer.from(await zip.arrayBuffer()), encoding: 'utf8' });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(Number(result.stdout), resources.manifest.resources.length + 2);
  assert.equal(zip.type, 'application/zip');
  assert.ok(progress.some(p => p.loaded > 0 && p.loaded < p.total));
  assert.equal(progress.at(-1).loaded, progress.at(-1).total);
});

test('packing can be cancelled during a large file and never returns a partial archive', async () => {
  const resources = await fixture(), controller = new AbortController();
  await assert.rejects(createModelZip(resources, { signal: controller.signal, onProgress: p => {
    if (p.loaded >= 1024 * 1024) controller.abort(new DOMException('Cancelled', 'AbortError'));
  } }), { name: 'AbortError' });
});

test('missing resources fail instead of exporting an incomplete model', async () => {
  const resources = await fixture(); resources.blobs.delete('model.moc3');
  await assert.rejects(createModelZip(resources), /Missing export resource/);
});

test('export without a player downloads verified resources and reuses cache on retry', async () => {
  const resources = await fixture(), cache = createResourceCache(), requested = [];
  const fetcher = async url => {
    const name = new URL(url).pathname.slice(1); requested.push(name);
    return new Response(name === 'manifest.json' ? JSON.stringify(resources.manifest) : resources.blobs.get(name));
  };
  const options = { fetcher, resourceCache: cache };
  await exportModel('https://local/', options);
  await exportModel('https://local/', options);
  assert.equal(requested.filter(n => n === 'textures/texture.png').length, 1);
});
