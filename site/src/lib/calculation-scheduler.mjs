/** Cooperative worker scheduling. Short bursts followed by proportional rest
 * reduce sustained CPU load without reducing the candidate set or precision. */
export function createCalculationScheduler({eco=true,now=()=>performance.now(),sleep=ms=>new Promise(r=>setTimeout(r,ms))}={}){
 let started=now(),pending=null;
 return async()=>{
   if(pending)return pending;
   const elapsed=now()-started;
   if(elapsed<12)return;
   pending=sleep(eco?Math.min(100,Math.max(16,elapsed*2)):0).then(()=>{started=now();pending=null;});
   return pending;
 };
}
