import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {startPageInputs} from '../src/runtime/startup.mjs';
import {artifact} from '../src/runtime/content.mjs';

const hash = value => createHash('sha256').update(value).digest('hex');
for (const locale of ['zh-CN', 'en']) for (const corrupt of [false, true]) {
  test(`early startup shares parallel checked requests: ${locale}, corrupt=${corrupt}`, async () => {
    const originalFetch = globalThis.fetch, originalLocation = globalThis.location, originalBase = globalThis.__OURNOTES_BASE__;
    const keys = ['ournotes.page-startup.v1', 'ournotes.content.snapshot.v1', 'ournotes.content-root.v1', 'ournotes.code-root.v1'].map(Symbol.for);
    const originals = keys.map(key => globalThis[key]);
    keys.forEach(key => delete globalThis[key]);
    const root = '/content/releases/' + 'a'.repeat(24) + '/';
    const names = ['catalog', 'release-index', 'media-index'];
    const data = JSON.stringify({version:'original'});
    const manifest = JSON.stringify({schemaVersion:1, region:'global', root, locales:{[locale]:{files:Object.fromEntries(names.map(name => [
      `projection/${name}.json`, {path:`${locale}/${name}.json`, sha256:hash(data)}
    ]))}}});
    const pointer = JSON.stringify({schemaVersion:1, manifest:root+'manifest.json', sha256:hash(manifest)});
    const counts = new Map(), pending = new Map();
    let releasePointer, imports = 0;
    globalThis.location = new URL(`https://example.test/global/${locale}/cards/members/`);
    globalThis.fetch = async input => {
      const url = String(input);
      counts.set(url, (counts.get(url) ?? 0) + 1);
      if (url === '/content/current.json') return new Promise(resolve => {releasePointer = () => resolve(new Response(pointer));});
      if (url === root+'manifest.json') return new Response(manifest);
      if (names.some(name => url === `${root}${locale}/${name}.json`)) return new Promise(resolve => pending.set(url, resolve));
      throw Error('Unexpected fetch ' + url);
    };
    try {
      const app = {schemaVersion:1, contentSchemaVersion:1, routes:[{pattern:'cards/members/', module:'page.js', css:null}]};
      const options = {importPage:async () => {imports++; return {default:await artifact('projection/catalog.json')};}};
      const task = startPageInputs(app, 'https://example.test/app/releases/test/', options);
      assert.equal(imports, 1, 'page import starts before the pointer resolves');
      assert.equal(startPageInputs(app, 'https://example.test/app/releases/test/', options), task);
      releasePointer();
      for (let i = 0; i < 100 && pending.size < 3; i++) await new Promise(resolve => setTimeout(resolve, 5));
      assert.equal(pending.size, 3, 'all three requests start while none has completed');
      for (const [url, resolve] of pending) resolve(new Response(corrupt && url.endsWith('/catalog.json') ? '{}' : data));
      if (corrupt) {
        await assert.rejects(task, /校验失败/);
        await assert.rejects(startPageInputs(app, 'https://example.test/app/releases/test/', options), /校验失败/);
      } else {
        assert.equal((await task).route.page.default.version, 'original');
        globalThis.fetch = async () => {throw Error('Must keep the original snapshot after an update');};
        const otherModule = await import(`../src/runtime/content.mjs?template-copy=${locale}`);
        assert.deepEqual(await otherModule.artifact('projection/media-index.json'), {version:'original'});
      }
      assert.equal(imports, 1);
      assert.ok([...counts.values()].every(count => count === 1), 'early fetches and template imports never duplicate requests');
    } finally {
      globalThis.fetch = originalFetch; globalThis.location = originalLocation;
      if (originalBase === undefined) delete globalThis.__OURNOTES_BASE__; else globalThis.__OURNOTES_BASE__ = originalBase;
      keys.forEach((key, i) => {if (originals[i] === undefined) delete globalThis[key]; else globalThis[key] = originals[i];});
    }
  });
}


test('compiled page profile starts collection reads before sequential template awaits', async () => {
  const keys = ['ournotes.page-startup.v1', 'ournotes.content.snapshot.v1', 'ournotes.content-root.v1', 'ournotes.code-root.v1'].map(Symbol.for);
  const originals = keys.map(key => globalThis[key]);
  const originalFetch = globalThis.fetch, originalLocation = globalThis.location, originalBase = globalThis.__OURNOTES_BASE__;
  keys.forEach(key => delete globalThis[key]);
  const root = '/content/releases/' + 'b'.repeat(24) + '/';
  const data = JSON.stringify({version:'checked'}), collection = JSON.stringify({'@projection-data/database-shards/skills/a.json':{schemaVersion:1}});
  const manifest = JSON.stringify({schemaVersion:1, region:'global', root, locales:{'zh-CN':{files:{
    'projection/catalog.json':{path:'zh-CN/catalog.json',sha256:hash(data)}
  }, groups:{'@projection-data/database-shards/skills/*.json':{path:'zh-CN/_groups/skills.json',sha256:hash(collection)}}}}});
  const pending = new Map(), counts = new Map();
  globalThis.location = new URL('https://example.test/global/zh-CN/cards/members/');
  globalThis.fetch = async url => {
    counts.set(url,(counts.get(url) ?? 0) + 1);
    if (url === '/content/current.json') return new Response(JSON.stringify({schemaVersion:1,manifest:root+'manifest.json',sha256:hash(manifest)}));
    if (url === root+'manifest.json') return new Response(manifest);
    return new Promise(resolve => pending.set(url,resolve));
  };
  try {
    const app = {schemaVersion:1,contentSchemaVersion:1,routes:[{pattern:'cards/members',module:'page.js',dataProfile:0}],
      dataProfiles:[{files:['projection/catalog.json','supplemental/optional.json'],groups:['@projection-data/database-shards/skills/*.json']}]};
    const task = startPageInputs(app,'https://example.test/app/',{importPage:async()=>({default:await artifact('projection/catalog.json')})});
    for(let i=0;i<100 && pending.size<2;i++) await new Promise(resolve=>setTimeout(resolve,5));
    assert.equal(pending.size,2,'collection starts even while the template is blocked on catalog');
    pending.get(root+'zh-CN/catalog.json')(new Response(data));
    pending.get(root+'zh-CN/_groups/skills.json')(new Response('{}'));
    await assert.rejects(task,/校验失败/,'prefetched corrupt collections fail closed');
    assert.ok([...counts.values()].every(value=>value===1));
  } finally {
    globalThis.fetch=originalFetch;globalThis.location=originalLocation;
    if(originalBase===undefined)delete globalThis.__OURNOTES_BASE__;else globalThis.__OURNOTES_BASE__=originalBase;
    keys.forEach((key,i)=>{if(originals[i]===undefined)delete globalThis[key];else globalThis[key]=originals[i];});
  }
});
