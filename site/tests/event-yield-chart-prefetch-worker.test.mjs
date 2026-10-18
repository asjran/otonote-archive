import test from 'node:test';
import assert from 'node:assert/strict';
import {workerHarness,delayedFetch} from './helpers/event-yield-worker-network.mjs';
test('actual Worker overlaps chart I/O with a bounded window and preserves demand result order',async()=>{
 const {stats,fetchImpl}=delayedFetch();const {messages}=await workerHarness({fetchImpl});
 assert.ok(stats.peak>=2,`serial network bottleneck remains: max active ${stats.peak}`);assert.ok(stats.peak<=4);
 assert.deepEqual(messages.at(-1),{type:'result',ids:Array.from({length:12},(_,i)=>'chart-'+i)});assert.equal(new Set(stats.started).size,12);
});
test('actual Worker only looks ahead on demand and cleans up unused requests',async()=>{
 const {stats,fetchImpl}=delayedFetch();const {messages}=await workerHarness({count:100,requestedIds:['chart-0','chart-0'],fetchImpl});
 assert.deepEqual(messages.at(-1),{type:'result',ids:['chart-0','chart-0']});assert.equal(stats.started.filter(x=>x===0).length,1);assert.ok(stats.started.length<=9);assert.equal(stats.active,0);
});
test('actual Worker handles unused failures without a spurious job error',async()=>{
 const {stats,fetchImpl}=delayedFetch({failAt:3});const {messages}=await workerHarness({count:30,requestedIds:['chart-0'],fetchImpl});
 assert.equal(messages.at(-1).type,'result');assert.equal(stats.active,0);
});
test('actual Worker closes its queue before reporting a demanded fetch failure',async()=>{
 const {stats,fetchImpl}=delayedFetch({failAt:0});const {messages}=await workerHarness({count:30,fetchImpl});
 assert.equal(messages.at(-1).type,'error');assert.match(messages.at(-1).message,/synthetic fetch failure/);assert.equal(stats.active,0);
});
test('actual Worker prefetches the challenge stage first without changing stage result order',async()=>{
 const {stats,fetchImpl}=delayedFetch();const challenge={id:'challenge',seconds:1,analysisDataUrl:'https://charts.invalid/100'};
 const {messages}=await workerHarness({count:6,challengeCandidates:[challenge],inputOverrides:{includeChallenge:true},fetchImpl});
 assert.equal(stats.started[0],100);assert.deepEqual(messages.at(-1).ids,['chart-100',...Array.from({length:6},(_,i)=>'chart-'+i)]);assert.ok(stats.peak<=4);
});
test('actual Worker quick metadata never starts an unused full-library download',async()=>{
 const {stats,fetchImpl}=delayedFetch();const {messages}=await workerHarness({count:100,requestedIds:['chart-0','chart-1'],inputOverrides:{searchDepth:'quick'},fetchImpl});
 assert.deepEqual(messages.at(-1).ids,['chart-0','chart-1']);assert.deepEqual(stats.started,[0,1]);
});
