import {runEventYieldBatch} from './event-yield-batch.mjs';
import {proveEventYieldGroups} from './event-yield-group-proof.mjs';
import {createEventSearchStore,eventSearchPartition,searchDigest} from './event-search-cache.mjs';
const store=createEventSearchStore();
self.addEventListener('message',async({data})=>{
 try{
   const {rules,eventId,candidates,challengeCandidates,input}=data;
   const partition=await eventSearchPartition(rules,eventId,input),preparedKey=partition+':prepared';
   const candidateCache=new Map(await store.get(preparedKey)??[]),charts=new Map(),storedScores=new Map();
   let storedCandidates=candidateCache.size,reportedAt=0,reportedStage='';
   const loadChart=async c=>{
     if(!charts.has(c.id))charts.set(c.id,(async()=>{
       const response=await fetch(c.analysisDataUrl,{signal:AbortSignal.timeout(30000)});
       if(!response.ok)throw Error(`谱面加载失败（${response.status}）`);return response.json();
     })());
     return charts.get(c.id);
   };
   const scoreKey=async(c,mode,stage,chart)=>await eventSearchPartition(rules,eventId,stage)+':'+mode+':'+await searchDigest({chart});
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
     onMessage:message=>{
       if(message.type==='progress'){
         const stage=message.stage+':'+(message.title??''),now=Date.now();
         if(stage===reportedStage&&now-reportedAt<120)return;
         reportedStage=stage;reportedAt=now;
         const progress=message.detail;
         self.postMessage({...message,title:message.title??'所有候选歌曲',
           detail:typeof progress==='object'?`${message.stage} ${progress.completed??''} / ${progress.total??'…'}`:progress});
       }else self.postMessage(message);
     }});
   self.postMessage(result);
 }catch(error){self.postMessage({type:'error',message:error.message});}
});
