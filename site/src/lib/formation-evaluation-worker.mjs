import {createCandidateEvaluator} from './formation-candidate-evaluator.mjs';
let evaluator, controller;
self.addEventListener('message',async ({data})=>{
  if(data.type==='cancel'){controller?.abort();return;}
  if(data.type==='init'){
    try {evaluator=createCandidateEvaluator(data.context);self.postMessage({type:'ready'});}
    catch(error){self.postMessage({type:'error',error:String(error.message??error)});}
    return;
  }
  if(data.type!=='evaluate')return;
  controller=new AbortController();
  try {
    const result=await evaluator.evaluate(data.draft,{signal:controller.signal,yieldControl:()=>new Promise(r=>setTimeout(r,0))});
    self.postMessage({type:'evaluated',taskId:data.taskId,result});
  }catch(error){self.postMessage({type:'error',taskId:data.taskId,error:String(error.message??error)});}
});
