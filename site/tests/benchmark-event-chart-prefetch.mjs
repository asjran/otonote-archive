/** Timer-only network regression, not a search or production throughput claim. */
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile,writeFile} from 'node:fs/promises';
import {workerHarness,delayedFetch} from './helpers/event-yield-worker-network.mjs';
const baseline=process.argv[2]??'dad2cbaa24e5208037357c6d74e0d6ab76f7e1a1',output=process.argv[3];
const original=execFileSync('git',['show',baseline+':site/src/lib/event-yield-worker.mjs'],{encoding:'utf8'});
const count=24,delay=10,jsonDelay=2,runs=[];
for(const variant of ['baseline','candidate','candidate','baseline']){
 const {stats,fetchImpl}=delayedFetch({delay,jsonDelay}),start=performance.now();
 const {messages}=await workerHarness({count,fetchImpl,workerSource:variant==='baseline'?original:undefined});
 const elapsedMs=performance.now()-start,result=messages.at(-1);
 if(result.type!=='result')throw Error('Benchmark worker failed');
 runs.push({variant,elapsedMs,maxConcurrentFetchAndBody:stats.peak,requests:stats.started.length,resultSha256:createHash('sha256').update(JSON.stringify(result)).digest('hex'),rssBytesAtEnd:process.memoryUsage().rss});
}
const sourceManifest=Object.fromEntries(await Promise.all(['../src/lib/event-yield-worker.mjs','../src/lib/event-yield-batch.mjs','../src/lib/bounded-chart-loader.mjs','./helpers/event-yield-worker-network.mjs'].map(async file=>[file,createHash('sha256').update(await readFile(new URL(file,import.meta.url))).digest('hex')])));
const summary={baselineWorkerSha256:createHash('sha256').update(original).digest('hex'),sourceManifest,kind:'actual_worker_mock_io_abba',baselineCommit:baseline,input:{count,fetchDelayMs:delay,jsonDelayMs:jsonDelay,urlPattern:'https://charts.invalid/N',requestedOrder:'0..23'},runs,
 resultComparable:runs.every(r=>r.resultSha256===runs[0].resultSha256&&r.requests===count),means:Object.fromEntries(['baseline','candidate'].map(v=>[v,runs.filter(r=>r.variant===v).reduce((s,r)=>s+r.elapsedMs,0)/2])),
 limits:'Mock network only; no scoring/search executed. RSS is shared warm Node process instantaneous RSS, not a per-variant isolated peak. Production HTTP/CDN and total search speedup require browser replay.'};
if(output)await writeFile(output,JSON.stringify(summary,null,2)+'\n');console.log(JSON.stringify(summary,null,2));
