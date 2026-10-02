import {createEventEfficiency} from './scoring-rules/event-efficiency.mjs';
import {estimateEventSong} from './event-song-ranking.mjs';

import {createCalculationScheduler} from './calculation-scheduler.mjs';
self.addEventListener('message',async({data})=>{
 try{
  const {rules,eventId,candidates,draft,options}=data;
  const model=createEventEfficiency({tables:rules.tables,sourceReleaseId:rules.sourceReleaseId,eventId});
  const rows=[],failures=[];let next=0,done=0;const yieldControl=createCalculationScheduler();
  await Promise.all(Array.from({length:Math.min(4,candidates.length)},async()=>{
   while(next<candidates.length){
    const candidate=candidates[next++];
    try{
     const response=await fetch(candidate.analysisDataUrl,{signal:AbortSignal.timeout(30000)});
     if(!response.ok)throw Error(`谱面加载失败（${response.status}）`);
     const chart=await response.json();await yieldControl();
     rows.push(estimateEventSong({rules,model,chart,draft,candidate,options}));await yieldControl();
    }catch(error){failures.push({id:candidate.id,title:candidate.title,message:error.message});}
    self.postMessage({type:'progress',done:++done,total:candidates.length});
   }
  }));
  self.postMessage({type:'result',rows,failures});
 }catch(error){self.postMessage({type:'error',message:error.message});}
});
