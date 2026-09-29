/** Optional first-party analytics. No request may delay a page or an export. */
let tracker = null;
export const OPT_OUT_KEY = 'ournotes.analytics.disabled';

export function createTracker({site, timezone='Asia/Shanghai', endpoint='/_stats/events', location, navigator, storage, uuid, now=()=>new Date(), referrer=''}) {
  let sessionDisabled = null;
  const day = () => new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).format(now());
  const disabled = () => {
    if(navigator.doNotTrack==='1'||navigator.globalPrivacyControl===true)return true;
    if(sessionDisabled !== null)return sessionDisabled;
    try{return storage?.getItem(OPT_OUT_KEY)==='1';}catch{return false;}
  };
  const visitor = () => {
    if(!storage)return null;
    try{const key='ournotes.analytics.visitor.'+site;let saved=JSON.parse(storage.getItem(key)||'null');
      if(saved?.day!==day()){saved={day:day(),id:uuid()};storage.setItem(key,JSON.stringify(saved));}return saved.id;
    }catch{return null;}
  };
  function send(type,fields={}) {
    try{
      if(disabled())return false;
      const url=new URL(endpoint,location.origin);
      if(url.origin!==location.origin||!url.pathname.startsWith('/')||url.search||url.hash)return false;
      const payload={v:1,site,id:uuid(),type,path:location.pathname,...fields};
      const id=visitor();if(id)payload.visitor=id;
      if(type==='page_view'){
        const host=referrer?new URL(referrer).hostname:'';
        payload.referrer=host?(host===location.hostname?'internal':host):'direct';
      }
      const body=JSON.stringify(payload);
      return navigator.sendBeacon(url.pathname,new Blob([body],{type:'application/json'}));
    }catch{return false;}
  }
  return {send,disabled,setDisabled(value){sessionDisabled=Boolean(value);try{storage?.setItem(OPT_OUT_KEY,value?'1':'0');if(value)storage?.removeItem('ournotes.analytics.visitor.'+site);}catch{}}};
}

export function recordDownload(resource){tracker?.send('download_click',{resource});}
export function beginExport(resource){
  if(!tracker)return {finish(){}};
  let operation;
  try{operation=globalThis.crypto?.randomUUID?.();}catch{return {finish(){}};}
  if(!operation)return {finish(){}};
  tracker?.send('export_start',{resource,operation});
  let finished=false;
  return {finish(result){if(finished)return;finished=true;tracker?.send('export_result',{resource,operation,result});}};
}

export function installAnalytics(doc=globalThis.document,win=globalThis.window){
  const config=doc?.querySelector('[data-site-analytics]');
  if(!config||tracker)return;
  let storage=null;try{storage=win.localStorage;}catch{}
  tracker=createTracker({site:config.dataset.site,timezone:config.dataset.timezone,endpoint:config.dataset.endpoint,
    location:win.location,navigator:win.navigator,storage,uuid:()=>win.crypto.randomUUID(),referrer:doc.referrer});
  let pageSent=false;
  const page=()=>{if(!pageSent&&doc.visibilityState==='visible'){pageSent=true;tracker.send('page_view');}};
  page();doc.addEventListener('visibilitychange',page);
  doc.addEventListener('click',event=>{
    if(!event.isTrusted)return;
    const link=event.target.closest?.('a[download],a[data-analytics-download]');
    if(!link)return;
    try{const resource=link.dataset.analyticsResource;const url=new URL(link.href,win.location.origin);
      if(resource)recordDownload(resource);else if(url.origin===win.location.origin&&['http:','https:'].includes(url.protocol))recordDownload(url.pathname);
    }catch{}
  },{capture:true});
  const button=doc.querySelector('[data-analytics-toggle]');
  const en=doc.documentElement.lang==='en';
  const render=()=>{if(button){button.textContent=tracker.disabled()?(en?'Analytics off · Turn on':'访问统计已关闭 · 点击开启'):(en?'Turn off anonymous analytics':'关闭匿名访问统计');button.setAttribute('aria-pressed',String(tracker.disabled()));}};
  button?.addEventListener('click',()=>{tracker.setDisabled(!tracker.disabled());render();});render();
}
