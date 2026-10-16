import test from 'node:test';
import assert from 'node:assert/strict';
import {rankingChartSelection} from '../src/lib/song-ranking-chart-dialog.mjs';
import {rankingWebsiteEdition} from '../src/lib/song-ranking-options.mjs';
const chart=(difficulty,url='/bound/chart.json')=>({id:`same-${difficulty}`,trackId:'song',difficulty,level:25,url});
const sources={global:{releaseId:'global-release',charts:[chart('hard'),chart('expert')]},jp:{releaseId:'jp-release',charts:[chart('expert','/jp/chart.json')]}};
const row={title:'Song',trackId:'global--song',sourceEdition:'global',difficulty:'expert',editionChartReferences:{global:{trackId:'song',sourceReleaseId:'global-release'},jp:{trackId:'song',sourceReleaseId:'jp-release'}}};
test('ranking default edition follows the website route or its native projection',()=>{
  assert.equal(rankingWebsiteEdition('/jp/zh-CN/tools/song-ranking/','global'),'jp');
  assert.equal(rankingWebsiteEdition('/global/en/tools/song-ranking/','jp'),'global');
  assert.equal(rankingWebsiteEdition('/tools/song-ranking/','jp'),'jp');
  assert.equal(rankingWebsiteEdition('/tools/song-ranking/','global'),'global');
});
test('in-page chart selection uses the requested edition and exact initial difficulty',()=>{
  assert.deepEqual(rankingChartSelection(row,'global',sources),{releaseId:'global-release',charts:sources.global.charts,difficulty:'expert'});
  assert.equal(rankingChartSelection(row,'jp',sources).charts[0].url,'/jp/chart.json');
  assert.throws(()=>rankingChartSelection({...row,difficulty:'hard'},'jp',sources),/当前版本尚未收录/);
});
test('missing or mismatched chart releases never fall back to the other edition',()=>{
  assert.throws(()=>rankingChartSelection(row,'all',sources),/尚未绑定/);
  assert.throws(()=>rankingChartSelection(row,'jp',{global:sources.global}),/尚未绑定/);
  assert.throws(()=>rankingChartSelection({...row,editionChartReferences:{jp:{trackId:'song',sourceReleaseId:'old'}}},'jp',sources),/尚未绑定/);
  assert.throws(()=>rankingChartSelection({...row,editionChartReferences:{}},'jp',sources),/当前版本尚未收录/);
});

class Field extends EventTarget {
  constructor(){super();this.dataset={};this.children=[];this.hidden=false;this.attrs=new Set();this.value='';this.isConnected=true;}
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=[...children];}
  hasAttribute(name){return this.attrs.has(name);}
  focus(){this.focused=true;}
}
function dialogFixture(t,boundSources=structuredClone(sources)) {
  const saved=new Map(['window','customElements','MutationObserver'].map(name=>[name,Object.getOwnPropertyDescriptor(globalThis,name)]));
  t.after(()=>{for(const [name,value] of saved)if(value)Object.defineProperty(globalThis,name,value);else delete globalThis[name];});
  globalThis.customElements={get:()=>true};globalThis.window=new EventTarget();
  const observed=[];globalThis.MutationObserver=class {constructor(callback){this.callback=callback;observed.push(this);}observe(){}disconnect(){this.stopped=true;}};
  const fields=Object.fromEntries(['mount','difficulty','status','retry','song','close'].map(name=>[name,new Field()]));
  const dialog=new Field();dialog.open=false;dialog.querySelector=selector=>selector==='.song-dialog-body'?new Field():fields[selector.match(/data-ranking-chart-([^\]]+)/)?.[1]];
  dialog.showModal=()=>dialog.open=true;dialog.close=()=>{if(dialog.open){dialog.open=false;dialog.dispatchEvent(new Event('close'));}};
  const origin=new Field(),views=[];
  const makeView=()=>{const view=new Field();view.records=new Field();view.error=new Field();view.error.hidden=true;view.querySelector=selector=>selector==='[data-score-error]'?view.error:view.records;views.push(view);return view;};
  const template={content:{querySelector:()=>({cloneNode:makeView})}};
  const document={activeElement:origin,documentElement:{lang:'zh-CN'},createElement:()=>new Field(),querySelector:selector=>selector==='[data-ranking-chart-dialog]'?dialog:template};
  const ui=setupRankingChartDialog({ownerDocument:document},boundSources);t.after(()=>ui.destroy());
  return {ui,dialog,fields,views,observed,origin};
}
import {setupRankingChartDialog} from '../src/lib/song-ranking-chart-dialog.mjs';
test('chart dialog retries failed loads, isolates cache identity and cleans up on close',t=>{
  const {ui,dialog,fields,views,observed,origin}=dialogFixture(t);
  ui.open(row,'global');assert.equal(dialog.open,true);assert.equal(views[0].dataset.embedded,'true');
  assert.equal(views[0].records.children[0].dataset.chartId,'global:global-release:same-hard');
  views[0].error.hidden=false;observed.at(-1).callback();assert.equal(fields.retry.hidden,false);assert.equal(dialog.dataset.loadState,'error');
  fields.retry.dispatchEvent(new Event('click'));assert.equal(views.length,2);assert.equal(observed[0].stopped,true);
  views[1].attrs.add('data-ready');observed.at(-1).callback();assert.equal(dialog.dataset.loadState,'ready');assert.equal(fields.status.hidden,true);
  fields.close.dispatchEvent(new Event('click'));assert.equal(fields.mount.children.length,0);assert.equal(origin.focused,true);
});
test('chart dialog can recover from an unavailable edition without borrowing its counterpart',t=>{
  const boundSources={global:structuredClone(sources.global)};
  const {ui,dialog,fields,views}=dialogFixture(t,boundSources);
  ui.open(row,'jp');assert.equal(dialog.dataset.loadState,'error');assert.equal(views.length,0);assert.match(fields.status.textContent,/尚未绑定/);
  boundSources.jp=structuredClone(sources.jp);fields.retry.dispatchEvent(new Event('click'));
  assert.equal(views.length,1);assert.equal(views[0].records.children[0].dataset.url,'/jp/chart.json');
});
