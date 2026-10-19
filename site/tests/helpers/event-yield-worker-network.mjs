import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const workerUrl=new URL('../../src/lib/event-yield-worker.mjs',import.meta.url);
const asModule=source=>'data:text/javascript,'+encodeURIComponent(source).replaceAll("'",'%27');
const batchStub=asModule(`export function eventYieldChartPlan(candidates,rules,input){const selected=input.searchDepth==='full'?[...candidates].sort((a,b)=>a.seconds-b.seconds||a.id.localeCompare(b.id)):candidates.slice(0,2);return {plan:{full:candidates,quick:candidates.slice(0,2)},selected};}
export async function runEventYieldBatch({candidates,challengeCandidates,input,loadChart,onMessage}){const rows=[];for(const message of input.progressMessages??[])onMessage(message);if(input.mode==='ordinary'&&input.includeChallenge)for(const c of challengeCandidates)rows.push(await loadChart(c));for(const id of input.requestedIds??candidates.map(c=>c.id)){rows.push(await loadChart(candidates.find(c=>c.id===id)));onMessage({type:'progress',stage:'test',done:rows.length});}return {type:'result',ids:rows.map(x=>x.id)};}`);
const cacheStub=asModule(`export const createEventSearchStore=()=>({get:async()=>null,put:async()=>true});export const eventSearchPartition=async()=> 'partition';export const searchDigest=async v=>JSON.stringify(v);`);
const proofStub=asModule('export const proveEventYieldGroups=async()=>({proven:false});');
export async function workerHarness({count=12,requestedIds,fetchImpl,workerSource,challengeCandidates=[],inputOverrides={}}){
 const candidates=Array.from({length:count},(_,i)=>({id:'chart-'+i,seconds:i,analysisDataUrl:'https://charts.invalid/'+i}));
 let listener;const messages=[],priorSelf=globalThis.self,priorFetch=globalThis.fetch;
 globalThis.self={addEventListener(type,fn){assert.equal(type,'message');listener=fn;},postMessage(data){messages.push(data);}};globalThis.fetch=fetchImpl;
 const stubs={'./event-yield-batch.mjs':batchStub,'./event-search-cache.mjs':cacheStub,'./event-yield-group-proof.mjs':proofStub};
 let source=workerSource??await readFile(workerUrl,'utf8');source=source.replace(/from ['"](\.\/[^'"]+)['"]/g,(_,s)=>`from '${stubs[s]??new URL(s,workerUrl).href}'`);
 try{await import(asModule(source)+'#'+Math.random());await listener({data:{rules:{},eventId:3,candidates,challengeCandidates,input:{searchDepth:'full',mode:'ordinary',includeChallenge:false,requestedIds,...inputOverrides}}});return {messages,candidates};}
 finally{globalThis.self=priorSelf;globalThis.fetch=priorFetch;}
}
export function delayedFetch({delay=12,jsonDelay=3,failAt=-1}={}){
 const stats={active:0,peak:0,started:[],aborted:0};
 const sleep=(ms,signal)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(signal.reason);};const timer=setTimeout(()=>{signal?.removeEventListener('abort',abort);resolve();},ms);if(signal?.aborted)return abort();signal?.addEventListener('abort',abort,{once:true});});
 const fetchImpl=async(url,{signal}={})=>{
  const id=Number(url.split('/').at(-1));stats.started.push(id);stats.peak=Math.max(stats.peak,++stats.active);
  try{await sleep(delay,signal);if(id===failAt)throw Error('synthetic fetch failure');return {ok:true,json:async()=>{try{await sleep(jsonDelay,signal);return {id:'chart-'+id};}finally{stats.active--;}}};}
  catch(error){stats.active--;if(signal?.aborted)stats.aborted++;throw error;}
 };
 return {stats,fetchImpl};
}
