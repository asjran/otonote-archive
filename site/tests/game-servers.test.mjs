import test from 'node:test';
import assert from 'node:assert/strict';
import {GAME_SERVERS,resolveServer,withServer,scopedStorageKey,assertAccountServer,serverSearchParams} from '../src/lib/game-servers.mjs';

test('four game servers share two editions independently of language',()=>{
  assert.deepEqual(GAME_SERVERS.map(s=>s.region),['jp','global','global','global']);
  assert.equal(resolveServer('jp'),'jp');
  assert.equal(resolveServer('global'),null);
  assert.equal(resolveServer('global','?server=global-kr',{getItem:()=> 'global-hmt'}),'global-kr');
  assert.equal(resolveServer('global','',{getItem:()=> 'jp'}),null);
  assert.throws(()=>resolveServer('jp','?server=global-en'),/不匹配/);
  assert.throws(()=>resolveServer('global','?server=unknown'),/不匹配/);
});
test('links preserve queries and do not carry a server across editions',()=>{
  assert.equal(withServer('/global/zh-CN/cards/?q=test#card','global-kr'),'/global/zh-CN/cards/?q=test&server=global-kr#card');
  assert.equal(withServer('/jp/en/cards/','global-kr'),'/jp/en/cards/');
  assertAccountServer('global-hmt',{region:'global',serverId:'global-hmt'});
  assert.throws(()=>assertAccountServer('global-hmt',{region:'global',serverId:'global-kr'}),/不匹配/);
  assert.throws(()=>assertAccountServer('global-hmt',{region:'global',serverId:null}),/先选择/);
});
test('browser account storage never crosses international servers or old unscoped keys',()=>{
  const previous=globalThis.location;
  try {
    const keys=[];
    for(const id of ['global-hmt','global-kr','global-en']) {
      globalThis.location=new URL('https://example.test/global/en/?server='+id);
      keys.push(scopedStorageKey('inventory','same-release'));
    }
    assert.equal(new Set(keys).size,3);
    assert.ok(keys.every(k=>k!=='ournotes:inventory:same-release'));
  } finally {globalThis.location=previous;}
});

test('clearing filters and changing pages retain the current server in shareable URLs',()=>{
  const previous=globalThis.location;
  try {
    globalThis.location=new URL('https://example.test/global/zh-CN/?server=global-en&q=old');
    assert.equal(serverSearchParams(new URLSearchParams()).toString(),'server=global-en');
    const filters=new URLSearchParams('q=new&page=2');
    assert.equal(serverSearchParams(filters).toString(),'q=new&page=2&server=global-en');
    assert.equal(filters.toString(),'q=new&page=2');
    globalThis.location=new URL('https://example.test/jp/en/');
    assert.equal(serverSearchParams(new URLSearchParams()).toString(),'server=jp');
  } finally {globalThis.location=previous;}
});

test('portable team JSON keeps its server and rejects cross-server imports',async()=>{
  const {createTeamDraft,serializeTeamDraftJson,parseScopedTeamDraftJson}=await import('../src/lib/team-draft.mjs');
  const context={region:'global',serverId:'global-en'},draft=createTeamDraft({});
  const raw=serializeTeamDraftJson(draft,context);
  assert.equal(JSON.parse(raw).serverId,'global-en');
  assert.deepEqual(parseScopedTeamDraftJson(raw,context),draft);
  assert.throws(()=>parseScopedTeamDraftJson(raw,{region:'global',serverId:'global-kr'}),/不匹配/);
  assert.throws(()=>parseScopedTeamDraftJson(JSON.stringify(draft),context),/不匹配/);
});
