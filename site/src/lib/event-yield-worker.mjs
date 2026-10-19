import {createEventYieldParallel} from './event-yield-parallel.mjs';
import {eventYieldWorkerProgress} from './event-yield-progress.mjs';
import {createBoundedChartLoader} from './bounded-chart-loader.mjs';
import {runEventYieldBatch,eventYieldChartPlan} from './event-yield-batch.mjs';
import {proveEventYieldGroups} from './event-yield-group-proof.mjs';
import {createEventSearchStore,eventSearchPartition,searchDigest} from './event-search-cache.mjs';
const store=createEventSearchStore();
self.addEventListener('message',async({data})=>{
 let chartLoader,parallel;
 try{
   const {rules,eventId,candidates,challengeCandidates,input}=data;
   const partition=await eventSearchPartition(rules,eventId,input),preparedKey=partition+':prepared';
   const candidateCache=new Map(await store.get(preparedKey)??[]),storedScores=new Map();
   let storedCandidates=candidateCache.size,reportedAt=-Infinity,reportedStage='';
   const startedAt=Date.now();
   const {selected}=eventYieldChartPlan(candidates,rules,input);
   const cycle=input.mode==='ordinary'&&input.includeChallenge;
   chartLoader=createBoundedChartLoader({candidates:[...(cycle?challengeCandidates:[]),...selected]});
   const {loadChart}=chartLoader;
   const scoreKey=async(c,mode,stage,chart)=>await eventSearchPartition(rules,eventId,stage)+':'+mode+':'+await searchDigest({chart});
   const onMessage=message=>{
       if(message.type==='progress'){
         const stage=(message.detail?.phase??message.stage)+':'+(message.goal??'')+':'+(message.title??''),now=Date.now();
         if(stage===reportedStage&&now-reportedAt<120)return;
         reportedStage=stage;reportedAt=now;
         self.postMessage(eventYieldWorkerProgress(message,now-startedAt));
       }else self.postMessage(message);
     };
   parallel=createEventYieldParallel({rules,eventId,input,onMessage});
   const result=await runEventYieldBatch({rules,eventId,candidates,challengeCandidates,input,candidateCache,loadChart,proveGroup:proveEventYieldGroups,
     getScoreCache:async(c,mode,stage,chart)=>{
       const cache=new Map(await store.get(await scoreKey(c,mode,stage,chart))??[]);
       storedScores.set(mode+':'+c.id,cache.size);return cache;
     },
     afterChart:async({candidate:c,mode,stageInput,chart,scoreCache})=>{
       if(storedScores.get(mode+':'+c.id)!==scoreCache.size){await store.put(await scoreKey(c,mode,stageInput,chart),[...scoreCache]);storedScores.set(mode+':'+c.id,scoreCache.size);}
       const prepared=[...candidateCache].filter(([key])=>!key.startsWith('power:'));
       if(prepared.length!==storedCandidates){await store.put(preparedKey,prepared);storedCandidates=prepared.length;}
     },
     onMessage,...parallel});
   parallel.close();await chartLoader.close();
   self.postMessage(result);
 }catch(error){parallel?.close();await chartLoader?.close();self.postMessage({type:'error',message:error.message});}
});
