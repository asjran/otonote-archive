import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

async function harness(t,createSession){
 const workerUrl=new URL('../src/lib/challenge-optimizer-worker.mjs',import.meta.url);
 let listener,time=0;const messages=[],waits=[];
 const prior={self:globalThis.self,fetch:globalThis.fetch,__createChallengeSession:globalThis.__createChallengeSession};
 globalThis.self={addEventListener:(_,fn)=>{listener=fn;},postMessage:data=>messages.push(data)};
 globalThis.fetch=async()=>({ok:true,json:async()=>({})});
 globalThis.__createChallengeSession=createSession(()=>{time++;});
 t.mock.method(performance,'now',()=>time);
 t.mock.method(globalThis,'setTimeout',(fn,ms)=>{waits.push(ms);queueMicrotask(fn);return waits.length;});
 t.after(()=>{for(const [k,v] of Object.entries(prior)){if(v===undefined)delete globalThis[k];else globalThis[k]=v;}});
 const asModule=source=>'data:text/javascript,'+encodeURIComponent(source).replaceAll("'",'%27');
 const stub=asModule('export const createChallengeSearchSession=globalThis.__createChallengeSession;')+'#'+Math.random();
 let source=await readFile(process.env.CHALLENGE_WORKER_BASELINE??workerUrl,'utf8');
 source=source.replace(/from ['"](\.\/[^'"]+)['"]/g,(_,path)=>`from '${path==='./challenge-optimizer.mjs'?stub:new URL(path,workerUrl).href}'`);
 await import(asModule(source)+'#'+Math.random());
 return {send:data=>listener({data}),messages,waits};
}

test('challenge worker batches fast yield points and reports dynamic search work',async t=>{
 const {send,waits,messages}=await harness(t,advance=>input=>({async run(){
  for(let i=0;i<240;i++){
   advance();input.onProgress({phase:'event-exact',expanded:i,completed:3,frontier:20});await input.yieldControl();
  }
  return {status:'completed',results:[]};
 }}));
 await send({analysisDataUrl:'/chart.json'});
 assert.ok(waits.length>0,'the worker must still service pause messages');
 assert.ok(waits.length<=5,`expected timed slices, received ${waits.length} timer waits`);
 const progress=messages.find(m=>m.type==='progress');
 assert.equal(progress.phase,'event-exact');assert.equal(progress.frontier,20);assert.equal(progress.evaluated,3);
 assert.ok(Number.isFinite(progress.elapsedMs));assert.equal(progress.total,undefined);
 assert.equal(messages.at(-1).type,'result');
});

test('pause and resume retain one worker session across timed slices',async t=>{
 let runs=0,created=0,input;
 const h=await harness(t,advance=>options=>{
  created++;input=options;
  return {async run(){
   runs++;
   if(runs===1)await h.send({type:'pause'});
   for(let i=0;i<50;i++){advance();await options.yieldControl();}
   return {status:options.shouldPause()?'paused':'completed',results:[]};
  }};
 });
 await h.send({analysisDataUrl:'/chart.json'});assert.equal(h.messages.at(-1).result.status,'paused');
 await h.send({type:'resume'});assert.equal(created,1);assert.equal(runs,2);assert.equal(input.shouldPause(),false);
 assert.equal(h.messages.at(-1).result.status,'completed');
});
