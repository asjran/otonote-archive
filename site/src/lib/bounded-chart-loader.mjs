/** Demand-driven chart I/O. Only consumed charts retain the existing per-job
 * cache; unused speculative charts are limited to the current lookahead window.
 * Completion never refills a whole-library queue without another demand. */
export function createBoundedChartLoader({candidates,fetch:fetchChart=globalThis.fetch,
 concurrency=4,lookahead=8,timeoutMs=30000,signal}={}){
 if(!Number.isInteger(concurrency)||concurrency<1||!Number.isInteger(lookahead)||lookahead<0||!Number.isFinite(timeoutMs)||timeoutMs<=0)throw Error('Invalid chart loading limits');
 const metadata=[],positions=new Map(),entries=new Map(),queue=[],active=new Set();
 for(const candidate of candidates??[]){const url=candidate.analysisDataUrl;if(typeof url==='string'&&url&&!positions.has(url)){positions.set(url,metadata.length);metadata.push(candidate);}}
 let closed=false;
 const cancelled=()=>new DOMException('谱面加载已停止','AbortError');
 function settle(entry,outcome){if(entry.state==='settled')return;entry.state='settled';entry.resolve(outcome);}
 function discard(entry){
  for(let i=queue.length-1;i>=0;i--)if(queue[i]===entry)queue.splice(i,1);
  if(entry.state==='queued')settle(entry,{error:cancelled()});
  else if(entry.state==='active')entry.controller.abort(cancelled());
  if(entries.get(entry.url)===entry)entries.delete(entry.url);
 }
 async function execute(entry){
  entry.state='active';active.add(entry);
  const controller=entry.controller=new AbortController();
  let rejectAbort;
  const aborted=new Promise((_,reject)=>{rejectAbort=reject;});
  const onAbort=()=>rejectAbort(controller.signal.reason??cancelled());
  controller.signal.addEventListener('abort',onAbort,{once:true});
  const timer=setTimeout(()=>controller.abort(new DOMException('谱面加载超时','TimeoutError')),timeoutMs);
  try{
   const value=await Promise.race([(async()=>{
    const response=await fetchChart(entry.url,{signal:controller.signal});
    if(!response.ok)throw Error(`谱面加载失败（${response.status}）`);
    return response.json();
   })(),aborted]);
   settle(entry,{value});
  }catch(error){if(!controller.signal.aborted)controller.abort(error);settle(entry,{error});}
  finally{clearTimeout(timer);controller.signal.removeEventListener('abort',onAbort);active.delete(entry);pump();}
 }
 function pump(){
  if(closed)return;
  while(active.size<concurrency&&queue.length){const entry=queue.shift();if(entry.state==='queued')void execute(entry);}
 }
 function ensure(candidate){
  const url=candidate.analysisDataUrl;if(typeof url!=='string'||!url)throw Error('谱面地址缺失');
  if(entries.has(url))return entries.get(url);
  let resolve;
  // Outcome promises never reject before a consumer exists. A failed unused
  // prefetch therefore cannot generate an unhandled rejection or job failure.
  const outcome=new Promise(r=>{resolve=r;});
  const entry={url,state:'queued',demanded:false,outcome,resolve};entries.set(url,entry);return entry;
 }
 async function loadChart(candidate){
  if(closed||signal?.aborted)throw signal?.reason??cancelled();
  const entry=ensure(candidate);
  if(!entry.demanded){
   entry.demanded=true;
   const index=positions.get(entry.url),window=index===undefined?[]:metadata.slice(index+1,index+1+lookahead);
   const wanted=new Set(window.map(c=>c.analysisDataUrl));
   for(const prior of entries.values())if(!prior.demanded&&!wanted.has(prior.url))discard(prior);
   // Demand goes before queued speculative requests. Active consumers are
   // never aborted even when another caller jumps to a distant window.
   if(entry.state==='queued'){const queued=queue.indexOf(entry);if(queued>=0)queue.splice(queued,1);queue.unshift(entry);}
   for(const next of window){const pending=ensure(next);if(pending.state==='queued'&&!queue.includes(pending))queue.push(pending);}
   pump();
  }
  const outcome=await entry.outcome;if(outcome.error)throw outcome.error;return outcome.value;
 }
 async function close(){
  if(!closed){closed=true;for(const entry of entries.values())if(entry.state!=='settled')discard(entry);queue.length=0;signal?.removeEventListener('abort',onExternalAbort);}
  await Promise.all([...active].map(entry=>entry.outcome));entries.clear();
 }
 const onExternalAbort=()=>{void close();};
 signal?.addEventListener('abort',onExternalAbort,{once:true});
 return {loadChart,close};
}
