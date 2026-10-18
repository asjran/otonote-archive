import test from 'node:test';
import assert from 'node:assert/strict';
import {createBoundedChartLoader} from '../src/lib/bounded-chart-loader.mjs';
import {eventYieldChartPlan,runEventYieldBatch} from '../src/lib/event-yield-batch.mjs';
import {planEventSearch} from '../src/lib/event-search-plan.mjs';
import {delayedFetch} from './helpers/event-yield-worker-network.mjs';
const candidates=Array.from({length:60},(_,i)=>({id:'chart-'+i,trackId:'music-'+i,seconds:i,level:20,analysisDataUrl:'https://charts.invalid/'+i}));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
test('cached demands do not refill the queue; later first miss gets its own window',async()=>{
 const {stats,fetchImpl}=delayedFetch({delay:2,jsonDelay:1});const loader=createBoundedChartLoader({candidates,fetch:fetchImpl});
 try{
  await loader.loadChart(candidates[0]);await sleep(12);const before=stats.started.length;
  await loader.loadChart(candidates[0]);assert.equal(stats.started.length,before);assert.ok(before<=9);
  assert.deepEqual(await loader.loadChart(candidates[30]),{id:'chart-30'});assert.ok(stats.started.includes(31));assert.equal(stats.started.filter(i=>i===0).length,1);
 }finally{await loader.close();}assert.equal(stats.active,0);
});
test('a jump aborts speculative I/O without aborting an active consumer',async()=>{
 const {stats,fetchImpl}=delayedFetch({delay:10,jsonDelay:2});const loader=createBoundedChartLoader({candidates,fetch:fetchImpl});
 try{assert.deepEqual(await Promise.all([loader.loadChart(candidates[0]),loader.loadChart(candidates[40])]),[{id:'chart-0'},{id:'chart-40'}]);assert.ok(stats.aborted>0);assert.ok(stats.peak<=4);}
 finally{await loader.close();}assert.equal(stats.active,0);
});
test('URL aliases share the same parsed content and a single HTTP request',async()=>{
 const alias={...candidates[1],analysisDataUrl:candidates[0].analysisDataUrl};let calls=0;
 const loader=createBoundedChartLoader({candidates:[candidates[0],alias],fetch:async()=>{calls++;return {ok:true,json:async()=>({contents:'same immutable chart'})};}});
 try{const values=await Promise.all([loader.loadChart(candidates[0]),loader.loadChart(alias)]);assert.equal(calls,1);assert.strictEqual(values[0],values[1]);}finally{await loader.close();}
});
test('unused prefetch failures are handled; an actual demand surfaces the original failure',async()=>{
 const errors=[];const listener=e=>errors.push(e);process.on('unhandledRejection',listener);
 const {fetchImpl}=delayedFetch({delay:2,jsonDelay:1,failAt:3});const loader=createBoundedChartLoader({candidates,fetch:fetchImpl});
 try{await loader.loadChart(candidates[0]);await sleep(10);assert.deepEqual(errors,[]);await assert.rejects(loader.loadChart(candidates[3]),/synthetic fetch failure/);}
 finally{await loader.close();process.removeListener('unhandledRejection',listener);}
});
test('timeout includes an unresolved JSON body, not just response headers',async()=>{
 let requestSignal;const loader=createBoundedChartLoader({candidates,lookahead:0,timeoutMs:8,fetch:async(_url,{signal})=>{requestSignal=signal;return {ok:true,json:()=>new Promise(()=>{})};}});
 try{await assert.rejects(loader.loadChart(candidates[0]),{name:'TimeoutError'});assert.equal(requestSignal.aborted,true);}finally{await loader.close();}
});
test('HTTP and JSON errors are surfaced only when demanded, with no retry or changed contents',async()=>{
 for(const response of [{ok:false,status:503},{ok:true,json:async()=>{throw new SyntaxError('bad JSON');}}]){
  let requests=0;const loader=createBoundedChartLoader({candidates,lookahead:0,fetch:async()=>{requests++;return response;}});
  try{await assert.rejects(loader.loadChart(candidates[0]));await assert.rejects(loader.loadChart(candidates[0]));assert.equal(requests,1);}finally{await loader.close();}
 }
});
test('explicit abort closes active/queued requests and rejects future demand',async()=>{
 const controller=new AbortController(),{stats,fetchImpl}=delayedFetch({delay:30});const loader=createBoundedChartLoader({candidates,fetch:fetchImpl,signal:controller.signal});
 const pending=loader.loadChart(candidates[0]);controller.abort(new DOMException('test stop','AbortError'));
 await assert.rejects(pending,{name:'AbortError'});await loader.close();const count=stats.started.length;await sleep(5);assert.equal(stats.active,0);assert.equal(stats.started.length,count);await assert.rejects(loader.loadChart(candidates[20]),{name:'AbortError'});
});
test('shared quick/full plans preserve existing selection order and every full candidate',async()=>{
 const input={mode:'ordinary',goal:'badges',searchDepth:'full',draft:{modifiers:{}}},set=[{...candidates[3],seconds:undefined},{...candidates[2],seconds:10},{...candidates[1],seconds:10},...candidates.slice(4,12)];
 const rules={tables:{LiveMusic:set.map((c,i)=>({_id:Number(c.trackId.split('-').at(-1)),_musicType:i%3}))}};
 const original=planEventSearch(set,rules,input.draft);
 for(const depth of ['quick','full']){
  const current={...input,searchDepth:depth};const {selected}=eventYieldChartPlan(set,rules,current);
  const expected=depth==='full'?[...original.full].sort((a,b)=>(a.seconds??Infinity)-(b.seconds??Infinity)||a.id.localeCompare(b.id)):original.quick;
  assert.deepEqual(selected,expected);if(depth==='full')assert.deepEqual(new Set(selected.map(c=>c.id)),new Set(set.map(c=>c.id)));
  const calls=[];await runEventYieldBatch({rules,eventId:3,candidates:set,input:current,globalPruning:false,loadChart:async c=>{calls.push(c.id);return {};},yieldControl:async()=>{},optimizer:async({candidate})=>({results:[],practical:{scoreCacheHits:0,scoreCalculations:0},certifiedSearch:{bestProven:true}})});
  assert.deepEqual(calls,selected.map(c=>c.id));
 }
});
test('invalid future metadata cannot poison or stall a valid demand',async()=>{
 const broken={...candidates[1],analysisDataUrl:123},set=[candidates[0],broken,candidates[2]],{stats,fetchImpl}=delayedFetch({delay:2,jsonDelay:1});
 const loader=createBoundedChartLoader({candidates:set,fetch:fetchImpl,timeoutMs:100});
 try{
  assert.deepEqual(await loader.loadChart(candidates[0]),{id:'chart-0'});assert.deepEqual(await loader.loadChart(candidates[2]),{id:'chart-2'});
  await assert.rejects(loader.loadChart(broken),/谱面地址缺失/);assert.equal(stats.started.includes(1),false);assert.ok(stats.peak<=4);
 }finally{await loader.close();}assert.equal(stats.active,0);
});
