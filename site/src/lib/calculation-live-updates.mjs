/** Publish the first update immediately, then coalesce bursts to their latest
 * value. Ending a job cancels progress; callers choose whether to keep its
 * pending result (pause/error) or discard it (new conditions/destroy). */
export function createCalculationLiveUpdates({onProgress,onResult,hasResults=()=>false,
 now=()=>performance.now(),schedule=setTimeout,cancel=clearTimeout}={}){
 const channel=(publish,interval,immediate=()=>false)=>{
  let timer=null,pending=null,publishedAt=-Infinity;
  function flush(){
   cancel(timer);timer=null;
   if(pending===null)return;
   const value=pending;pending=null;publishedAt=now();publish(value);
  }
  return {
   queue(value){
    pending=value;if(timer!==null)return;
    const delay=interval-(now()-publishedAt);
    if(immediate()||delay<=0)flush();else timer=schedule(flush,delay);
   },
   flush,
   stop(keep=false){cancel(timer);timer=null;if(keep)flush();pending=null;publishedAt=-Infinity;}
  };
 };
 const progress=channel(onProgress,250),result=channel(onResult,750,()=>!hasResults());
 return {progress:progress.queue,result:result.queue,
  stop({flushResult=false}={}){progress.stop();result.stop(flushResult);}};
}

/** Preserve mounted controls and custom playback elements wherever possible. */
export function reconcileCalculationView(container,view){
 const keep=new Set(view);
 for(const node of [...container.children])if(!keep.has(node))container.removeChild(node);
 for(const [index,node] of view.entries())if(container.children[index]!==node){
  const anchor=container.children[index]??null;
  if(node.parentNode===container&&typeof container.moveBefore==='function')container.moveBefore(node,anchor);
  else container.insertBefore(node,anchor);
 }
}
