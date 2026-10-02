import test from 'node:test';
import assert from 'node:assert/strict';
import {mergeEditionRows, mergeCatalogs, presenceLabel} from '../src/lib/edition-library.mjs';
import {pageEditionHref, rankingServerHref} from '../src/lib/page-edition.mjs';
const options = {region:'global', key:r=>r.proof, path:r=>`/cards/${r.id}/`};
test('same numeric ID never establishes cross-edition identity',()=>{
  const rows=mergeEditionRows([{id:1,proof:'a'}],[{id:1,proof:'b'}],options);
  assert.equal(rows.length,2);assert.equal(rows[1].id,'jp--1');
  assert.equal(rows[1].sourceHref,'/jp/zh-CN/cards/1/');
  assert.equal(presenceLabel(rows[1].editionPresence),'日服独有');
});
test('unique evidence joins content, ambiguous and missing evidence do not',()=>{
  assert.equal(mergeEditionRows([{id:1,proof:'a'}],[{id:2,proof:'a'}],options).length,1);
  assert.equal(mergeEditionRows([{id:1,proof:'a'}],[{id:2,proof:'a'},{id:3,proof:'a'}],options).length,3);
  assert.equal(mergeEditionRows([{id:1}],[{id:1}],options).length,2);
  assert.equal(presenceLabel(mergeEditionRows([{id:1}],null,options)[0].editionPresence),'');
  assert.equal(presenceLabel({status:'known',editions:['global','jp'],different:true}),'');
});
test('page switch keeps filters, resets pagination, never assumes a detail counterpart',()=>{
  const href=pageEditionHref('/global/zh-CN/events/12/','?server=global-en&page=3&q=hello','jp','zh-CN');
  const url=new URL(href,'https://test.invalid');
  assert.equal(url.pathname,'/jp/zh-CN/events/');assert.equal(url.searchParams.get('q'),'hello');
  assert.equal(url.searchParams.get('view'),'page');assert.equal(url.searchParams.get('unavailable'),'/events/12/');
  assert.equal(url.searchParams.has('server'),false);assert.equal(url.searchParams.has('page'),false);
  assert.equal(new URL(pageEditionHref('/global/zh-CN/events/12/','','global','zh-CN'),'https://test.invalid').pathname,'/global/zh-CN/events/12/');
  const rank=new URL(rankingServerHref('/global/en/rankings/','?event=12&board=music&cursor=old','jp'),'https://test.invalid');
  assert.equal(rank.pathname,'/jp/en/rankings/');assert.equal(rank.searchParams.has('event'),false);assert.equal(rank.searchParams.get('board'),'music');
});
test('foreign cards keep distinct media and reference a verified common character',()=>{
  const catalog=region=>({release:{id:region,region},assets:[{id:'a',sha256:'portrait'},{id:'c',sha256:region}],bands:[],characters:[{id:'character-1',profileAssetId:'a',birthday:{month:1,day:1},role:'vocal'}],memberCards:[{id:'member-1',primaryAssetId:'c',characterId:'character-1',rarity:3,attributeCode:1,assetId:1}],supportCards:[],musicTracks:[],musicCharts:[]});
  const a=catalog('global'),b=catalog('jp'),rows=mergeCatalogs(a,b,'en');
  assert.equal(rows.characters.length,1);assert.equal(rows.memberCards.length,2);
  assert.equal(rows.memberCards[1].characterId,'character-1');assert.equal(rows.memberCards[1].primaryAssetId,'jp--c');
  assert.equal(rows.memberCards[1].sourceHref,'/jp/en/cards/members/member-1/');
  assert.equal(b.memberCards[0].primaryAssetId,'c','source snapshot is immutable');
});
