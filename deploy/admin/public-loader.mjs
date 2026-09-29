// Optional edge-installed tracking for published pages; no resource-update access.
import {createTracker} from '/_stats/tracker.mjs';
let storage; try { storage=localStorage; } catch {}
const tracker=createTracker({site:'ournotes',location,navigator,storage,
  uuid:()=>crypto.randomUUID(),referrer:document.referrer});
let viewed=false;
function page(){if(!viewed&&document.visibilityState==='visible'){viewed=true;tracker.send('page_view');}}
page();document.addEventListener('visibilitychange',page);
function notice(){
  if(document.querySelector('[data-edge-analytics]'))return;
  const footer=document.querySelector('.site-footer,footer');
  if(!footer)return;
  const row=document.createElement('div');row.dataset.edgeAnalytics='';
  const en=document.documentElement.lang==='en';
  const label=document.createElement('small');
  label.textContent=en?'Anonymous page views and download clicks. ':'匿名统计页面访问与下载点击。';
  const button=document.createElement('button');button.type='button';
  function render(){button.textContent=tracker.disabled()?(en?'Analytics off · Enable':'统计已关闭 · 开启'):(en?'Disable analytics':'关闭统计');button.setAttribute('aria-pressed',String(tracker.disabled()));}
  button.addEventListener('click',()=>{tracker.setDisabled(!tracker.disabled());render();});render();
  row.append(label,button);footer.append(row);
}
notice();document.addEventListener('astro:page-load',notice);
document.addEventListener('click',event=>{
  if(!event.isTrusted)return;
  const exportButton=event.target.closest?.('[data-scene-export],live2d-workbench [data-export]');
  if(exportButton&&!exportButton.disabled){tracker.send('download_click',{resource:'export-page:'+location.pathname});return;}
  const link=event.target.closest?.('a[download],a[data-analytics-download]');
  if(!link)return;
  try{
    const url=new URL(link.href,location.origin);
    const resource=link.dataset.analyticsResource||(url.origin===location.origin&&url.protocol==='https:'?url.pathname:null);
    // Blob saves have no stable URL: count their registered originating page.
    const key=resource||(url.protocol==='blob:'?'export-page:'+location.pathname:null);
    if(key)tracker.send('download_click',{resource:key});
  }catch{}
},{capture:true});
