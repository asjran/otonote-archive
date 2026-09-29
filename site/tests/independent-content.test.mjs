import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {checkedJson,validatePointer,snapshot,artifact,pageContext} from '../src/runtime/content.mjs';

test('content integrity and schema fail closed',async()=>{
  const bytes=JSON.stringify({value:1});const sha=createHash('sha256').update(bytes).digest('hex');
  assert.deepEqual(await checkedJson('/content/example',sha,async()=>new Response(bytes)),{value:1});
  await assert.rejects(checkedJson('/content/example',sha,async()=>new Response('{}')),/校验失败/);
  for(const manifest of ['https://elsewhere.invalid/x','/content/releases/../manifest.json'])
    assert.throws(()=>validatePointer({schemaVersion:1,manifest,sha256:sha}));
  assert.throws(()=>validatePointer({schemaVersion:2,manifest:'/content/releases/'+'a'.repeat(24)+'/manifest.json',sha256:sha}));
  assert.equal(pageContext('/global/en/music/music-1/').locale,'en');
});

test('a document keeps its snapshot after current changes, including lazy data',async()=>{
  const key=Symbol.for('ournotes.content.snapshot.v1');delete globalThis[key];
  const rootKey=Symbol.for('ournotes.content-root.v1');
  const originalFetch=globalThis.fetch,originalLocation=globalThis.location,originalRoot=globalThis[rootKey];
  let currentReads=0;const root='/content/releases/'+'a'.repeat(24)+'/';
  const data=JSON.stringify({version:'old'}),hash=s=>createHash('sha256').update(s).digest('hex');
  const manifest=JSON.stringify({schemaVersion:1,root,locales:{'zh-CN':{files:{
    safe:{path:'zh-CN/data.json',sha256:hash(data)},escape:{path:'../private.json',sha256:hash(data)}
  }}}});
  globalThis.location={pathname:'/global/zh-CN/'};
  globalThis.fetch=async url=>{
    if(url==='/content/current.json') {currentReads++;return new Response(JSON.stringify({schemaVersion:1,manifest:root+'manifest.json',sha256:hash(manifest)}));}
    if(url===root+'manifest.json')return new Response(manifest);
    if(url===root+'zh-CN/data.json')return new Response(data);
    throw Error('Unexpected URL '+url);
  };
  try {
    await snapshot();await snapshot();assert.equal(currentReads,1);
    assert.equal(globalThis[rootKey],root,'media root is ready before templates consume snapshot data');
    assert.deepEqual(await artifact('safe'),{version:'old'});
    assert.equal(await artifact('absent', {optional:true}),null);
    assert.equal(currentReads,1);
    await assert.rejects(artifact('escape'),/清单不完整/);
    await assert.rejects(artifact('escape', {optional:true}),/清单不完整/);
  } finally {globalThis.fetch=originalFetch;globalThis.location=originalLocation;delete globalThis[key];
    if(originalRoot===undefined)delete globalThis[rootKey];else globalThis[rootKey]=originalRoot;
  }
});
