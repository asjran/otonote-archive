import test from 'node:test';
import assert from 'node:assert/strict';
import {maintenanceNotice,installGameServiceNotice} from '../src/lib/game-service-status.mjs';
import {setupAccountGrowthImport} from '../src/lib/account-growth-ui.mjs';
import {GachaHistoryTool} from '../src/lib/gacha-history-ui.mjs';

const observation={status:'maintenance',maintenance:{expectedEndAt:'2026-10-18T06:00:00Z'}};
const node=()=>({hidden:false,disabled:false,value:'',textContent:'',listeners:{},addEventListener(type,fn){this.listeners[type]=fn;}});

test('expected maintenance end is UTC+8 and never an automatic recovery claim',()=>{
  assert.match(maintenanceNotice(observation,'zh',Date.parse('2026-10-18T05:00:00Z')),/14:00/);
  assert.match(maintenanceNotice(observation,'en',Date.parse('2026-10-18T07:00:00Z')),/not confirmed/);
  assert.match(maintenanceNotice(observation,'zh',Date.parse('2026-10-18T07:00:00Z')),/等待官方恢复确认/);
  assert.equal(maintenanceNotice({status:'unknown'}),'');
});

test('growth blocks credentials during maintenance, keeps file import usable, and never retries login on recovery',async()=>{
  const previous={location:globalThis.location,fetch:globalThis.fetch,window:globalThis.window};
  const elements=new Map(),q=key=>{if(!elements.has(key))elements.set(key,node());return elements.get(key);};
  globalThis.location={pathname:'/global/tools/song-calculator/',search:'?server=global-hmt'};
  globalThis.window=new EventTarget();
  const sent=[];
  globalThis.fetch=async url=>{sent.push(url);return {ok:true,json:async()=>({enabled:true,nonce:'fixture',gameStatus:observation})};};
  try {
    setupAccountGrowthImport({querySelector:()=>({querySelector:q}),addEventListener(){},personalGrowthStore:{}},{getInventory(){},replaceInventory(){}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.equal(q('[data-growth-login-fields]').disabled,true);
    assert.equal(q('[data-growth-file]').disabled,false);
    await q('[data-growth-login]').listeners.submit({preventDefault(){}});
    assert.deepEqual(sent,['/api/growth-export/capabilities/']);
    const event=new Event('game-service-status-change');
    event.detail={servers:{'global-hmt':{status:'no_maintenance_signal'}}};
    window.dispatchEvent(event);
    assert.equal(q('[data-growth-login-fields]').disabled,false);
    assert.equal(sent.length,1);
  } finally {
    globalThis.window.dispatchEvent(new Event('pagehide'));
    Object.assign(globalThis,previous);
  }
});

test('gacha stops before reading inputs or issuing a request when maintenance is known',async()=>{
  const tool=new GachaHistoryTool(),elements=new Map();
  tool.q=key=>{if(!elements.has(key))elements.set(key,node());return elements.get(key);};
  tool.nonce='fixture';tool.applyGameStatus(observation);
  assert.equal(tool.q('fields').disabled,true);
  assert.match(tool.q('service').textContent,/维护/);
  await tool.queryHistory();
  assert.equal(elements.has('account'),false);
});


test('public banner rejects stale status and keeps recovery unconfirmed after probe failure',async()=>{
  const names=['window','document','location','fetch','setTimeout','clearTimeout'];
  const previous=Object.fromEntries(names.map(key=>[key,globalThis[key]]));
  const timers=[],requests=[],updates=[],message=node(),detail=node();
  const root={hidden:true,dataset:{locale:'zh-CN'},querySelector:key=>key.includes('message')?message:detail};
  globalThis.window=new EventTarget();globalThis.document=new EventTarget();
  globalThis.location={pathname:'/global/zh-CN/tools/gacha-history/',search:'?server=global-en'};
  globalThis.setTimeout=(callback,delay)=>{const timer={callback,delay};timers.push(timer);return timer;};
  globalThis.clearTimeout=timer=>{if(timer)timer.cleared=true;};
  let response={schemaVersion:1,validUntil:new Date(Date.now()+60000).toISOString(),servers:{'global-en':observation}};
  globalThis.fetch=async(url,options)=>{requests.push({url,options});return {ok:true,json:async()=>response};};
  window.addEventListener('game-service-status-change',event=>updates.push(event.detail));
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  let stop;
  try {
    stop=installGameServiceNotice(root);await flush();
    assert.equal(root.hidden,false);assert.match(message.textContent,/EN.*维护/);
    assert.match(detail.textContent,/本地文件导入/);
    assert.equal(requests[0].options.credentials,'omit');
    assert.equal(requests[0].options.cache,'no-store');
    response={...response,validUntil:'2026-01-01T00:00:00Z',servers:{'global-en':{status:'no_maintenance_signal'}}};
    await timers.findLast(timer=>timer.delay===60000).callback();await flush();
    assert.equal(root.hidden,false);assert.match(message.textContent,/尚不能确认维护已经结束/);
    assert.deepEqual(updates.at(-1).servers,{});
    response={...response,validUntil:new Date(Date.now()+60000).toISOString()};
    const restored=new Event('pageshow');restored.persisted=true;window.dispatchEvent(restored);await flush();
    assert.equal(root.hidden,true);
    assert.equal(requests.length,3);
    document.dispatchEvent(new Event('ournotes:shell-dispose'));
    assert.equal(requests.at(-1).options.signal.aborted,true);
    assert.equal(timers.findLast(timer=>timer.delay===60000).cleared,true);
    window.dispatchEvent(restored);await flush();assert.equal(requests.length,3);
  } finally {stop?.();Object.assign(globalThis,previous);}
});
