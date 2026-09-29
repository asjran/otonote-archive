const $ = id => document.getElementById(id);
const number = value => value == null ? '—' : new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 1}).format(value);
const bytes = value => value == null ? '—' : value < 1e6 ? `${number(value / 1e3)} KB` : value < 1e9 ? `${number(value / 1e6)} MB` : `${number(value / 1e9)} GB`;
const time = value => value ? new Date(value * 1000).toLocaleTimeString('zh-CN', {hour12:false}) : '尚无数据';
const words = {page:'页面',image:'图片',audio:'音频',video:'视频',live2d:'Live2D',static:'脚本与样式',data:'数据',download:'文件',other:'其他',queued:'等待执行',running:'正在执行',succeeded:'已完成',failed:'失败',interrupted:'已中断',passed:'已完成',not_run:'尚未运行',unknown:'状态未知',unavailable:'不可用',success:'生成成功',cancelled:'已取消'};
let config, currentView = 'overview', generation = 0, loadData = [], inFlight = false;

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function empty(container, title, detail='') {
  const node = el('div', null, 'empty'); node.append(el('span', title));
  if (detail) node.append(el('small', detail)); container.replaceChildren(node);
}
function metrics(container, rows) {
  container.replaceChildren(...rows.map(([label,value,detail]) => {
    const card = el('div', null, 'metric'); card.append(el('span',label,'metric-label'),el('strong',value),el('small',detail)); return card;
  }));
}
function rows(container, items, title='尚无记录', detail='开始采集后会在这里显示。') {
  if (!items.length) return empty(container,title,detail);
  container.replaceChildren(...items.map(([label,value,hint]) => {
    const row = el('div',null,'data-row'), name=el('span',label);
    if(hint) name.append(el('small',hint)); row.append(name,el('strong',value)); return row;
  }));
}
function chart(container, points, keys, label, gapSeconds=Infinity) {
  if (!points.some(p=>keys.some(k=>p[k]!=null))) return empty(container,'尚无有效采样','未接入、断线或第一份基线数据不会被画成零。');
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 800 200'); svg.setAttribute('role','img'); svg.setAttribute('aria-label',label);
  const add=(tag,attrs,text)=>{const n=document.createElementNS(ns,tag); for(const[k,v] of Object.entries(attrs)) n.setAttribute(k,String(v)); if(text!=null)n.textContent=text; svg.append(n);return n;};
  const values=points.flatMap(p=>keys.map(k=>p[k]).filter(v=>v!=null)); const max=Math.max(...values,1)*1.12;
  const start=points[0].ts, end=points.at(-1).ts; const x=t=>48+((t-start)/(end-start||1))*734, y=v=>164-(v/max)*148;
  for(let i=0;i<4;i++){const v=max*i/3;add('line',{x1:48,x2:785,y1:y(v),y2:y(v),class:'grid'});add('text',{x:38,y:y(v)+4,'text-anchor':'end'},number(v));}
  keys.forEach((key,index)=>{
    let path='',previous=null;
    for(const p of points){if(p[key]==null){previous=null;continue;}const move=previous==null||p.ts-previous>gapSeconds||p.gap;path+=`${move?'M':'L'}${x(p.ts).toFixed(2)},${y(p[key]).toFixed(2)} `;previous=p.ts;}
    add('path',{d:path,class:index?'line teal':'line'});
    if(points.length===1 && points[0][key]!=null)add('circle',{cx:x(start),cy:y(points[0][key]),r:3,fill:index?'#167d6a':'#287bb8'});
  });
  add('text',{x:48,y:190},points[0].label||time(start));add('text',{x:785,y:190,'text-anchor':'end'},points.at(-1).label||time(end));
  container.replaceChildren(svg);
}
async function api(path,options={}) {
  const response=await fetch(path,{...options,cache:'no-store',signal:AbortSignal.timeout(12000)});
  if(!response.ok) throw new Error(response.status===401?'认证已失效，请重新登录管理入口。':response.status===403?'当前入口不允许执行此操作。':'请求未完成，请检查节点状态。');
  return response.json();
}
function status(message,error=false){$('health').textContent=message;$('health').parentElement.classList.toggle('error',error);}
function siteId(){return $('site').value;}
function renderSummary(result) {
  const d=result.data, ok=result.status==='ok'&&d, hasEvents=ok&&d.events.lastEvent;
  metrics($('visit-metrics'),[
    ['浏览量',hasEvents?number(d.totals.page_view||0):'—','页面浏览事件'],
    ['日访客累计',hasEvents?number(d.dailyVisitorsSum):'—','每日去重 · 非区间独立人数'],
    ['下载点击',hasEvents?number(d.totals.download_click||0):'—','不代表文件已保存'],
    ['导出成功',hasEvents&&d.exportResultsEnabled!==false?number(d.totals['export_result:success']||0):'—',d?.exportResultsEnabled===false?'当前线上前端尚未接入结果上报':'浏览器文件生成完成']]);
  if(!ok){for(const id of ['pages','downloads','referrers','traffic','visits-chart'])empty($(id),'统计来源暂不可用','检查采集服务或服务器间 SSH 隧道。');status('统计来源离线 · 当前值不可用',true);return;}
  status(d.samplingError?'部分采集失败，请检查采集服务':!hasEvents?'尚未收到网页事件 · 请检查网站采集配置':d.coverage==='partial'?'当前窗口尚未完整覆盖 · 从开始采集后累计':'统计服务已连接 · 网页事件可能受浏览器拦截',Boolean(d.samplingError));
  $('updated').textContent=`查询于 ${time(result.fetchedAt)} · 最近事件 ${time(d.events.lastEvent)}`;
  const points=d.timeline.map(p=>({...p,ts:Date.parse(p.day+'T00:00:00+08:00')/1000,label:p.day.slice(5)}));
  chart($('visits-chart'),points,['views','downloads'],'每日浏览量与下载点击趋势',86400*1.5);
  rows($('pages'),d.pages.map(r=>[r.label,number(r.count)]));
  rows($('downloads'),d.resources.map(r=>[r.label,number(r.count),r.kind==='download_click'?'下载点击':words[r.result]||r.result]));
  rows($('referrers'),d.referrers.map(r=>[r.label==='direct'?'直接或来源未知':r.label==='internal'?'站内跳转':r.label,number(r.count)]));
  rows($('traffic'),d.traffic.map(r=>[words[r.category]||r.category,bytes(r.bytes),`${number(r.requests)} 次请求 · ${number(r.errors)} 次错误`]),d.log.status==='ok'?'窗口内尚无请求':'尚未接入网站日志','请配置站点日志路径；网页事件不会被算成网站传输量。');
}
function renderLoads() {
  const source=loadData.find(s=>s.source===$('load-source').value), latest=source?.latest;
  const fresh=latest && Date.now()/1000-latest.ts<=(source.resolution||5)*3;
  const sample=fresh?latest:null;
  const points=source?.points||[], valid=points.filter(p=>p.txMbps!=null);
  metrics($('load-metrics'),[
    ['当前连接数',number(sample?.active),'共享 Nginx 实例 · 含空闲连接'],
    ['每秒请求数',number(sample?.rps),'采样窗口平均 RPS'],
    ['当前出站带宽',sample?.txMbps!=null?`${number(sample.txMbps)}`:'—','Mbps · 服务器选定网卡'],
    ['当前入站带宽',sample?.rxMbps!=null?`${number(sample.rxMbps)}`:'—','Mbps · 服务器选定网卡']]);
  chart($('bandwidth-chart'),points,['txMbps','rxMbps'],'服务器收发带宽曲线',(source?.resolution||5)*3);
  chart($('connections-chart'),points,['active'],'Nginx 连接数曲线',(source?.resolution||5)*3);
  chart($('requests-chart'),points,['rps'],'Nginx 请求速率曲线',(source?.resolution||5)*3);
  const peak=valid.length?valid.reduce((a,b)=>(a.txPeakMbps??a.txMbps)>(b.txPeakMbps??b.txMbps)?a:b):null;
  const rate=sample?.txMbps!=null&&sample.txLimitMbps?sample.txMbps/sample.txLimitMbps*100:null;
  rows($('bandwidth-detail'),[
    ['采样出站峰值',peak?`${number(peak.txPeakMbps??peak.txMbps)} Mbps · ${time(peak.txPeakAt??peak.ts)}`:'—'],
    ['配置上限占用',rate==null?'未配置上限或暂无有效采样':`${number(rate)}% / ${number(sample.txLimitMbps)} Mbps`],
    ['本窗口已采集出站量',valid.length?bytes(valid.reduce((n,p)=>n+(p.txBytes||0),0)):'—'],
    ['今日 / 本月出站量',source?.totals?`${bytes(source.totals.today.txBytes)} / ${bytes(source.totals.month.txBytes)}`:'未提供','仅采集覆盖范围，整机网卡口径']]);
  rows($('connection-detail'),[['读取 / 写入 / 空闲',sample?`${number(sample.reading)} / ${number(sample.writing)} / ${number(sample.waiting)}`:'—']]);
  if(currentView==='load'){status(!latest?'负载来源尚无采样':!fresh?'采样已延迟 · 保留历史曲线，当前值不可用':'负载每 5 秒刷新 · 连接和网卡指标属于服务器范围',!fresh);$('updated').textContent=`最后采样 ${time(latest?.ts)}`;}
}
async function refreshLoads(gen=generation){
  const result=await api(`/api/loads/${encodeURIComponent(siteId())}?seconds=${$('load-window').value}`);
  if(gen!==generation)return;
  loadData=result.data?.sources||[];const previous=$('load-source').value;
  $('load-source').replaceChildren(...loadData.map(s=>new Option(s.name,s.source)));
  if(loadData.some(s=>s.source===previous))$('load-source').value=previous;
  renderLoads();
}
async function refreshNodes(gen=generation){
  const allowed=config.sites.find(s=>s.id===siteId())?.nodes||[];
  const nodes=config.nodes.filter(n=>allowed.includes(n.id));
  if(!nodes.length)return empty($('nodes'),'还没有绑定资源节点','配置节点后可以查看运行状态、步骤和任务记录。');
  const results=await Promise.all(nodes.map(async n=>({node:n,result:await api(`/api/nodes/${encodeURIComponent(n.id)}`)})));
  if(gen!==generation)return;
  const offline=results.filter(x=>x.result.status!=='ok').length;
  status(offline?`${offline} 个节点暂不可用 · 不据此判断任务结果`:'节点状态已更新 · 仅显示实际开放的操作',Boolean(offline));
  $('updated').textContent=`查询于 ${time(Date.now()/1000)}`;
  $('nodes').replaceChildren(...results.map(({node,result})=>{
    const panel=el('div',null,'panel'),header=el('div',null,'node-header');
    header.append(el('h3',node.name),el('span',result.status==='ok'?'节点已连接':'节点不可用',result.status==='ok'?'badge':'badge warning'));panel.append(header);
    if(!result.data){panel.append(el('p','检查节点服务与 SSH 隧道，未连接不代表任务失败。','caption'));return panel;}
    for(const profile of result.data.profiles){
      const row=el('div',null,'node-profile'),description=el('div');description.append(el('p',profile.name),el('small',`最近运行：${words[profile.status]||profile.status} · 发布权限未开放`));
      const actions=el('div',null,'toolbar'),check=el('button','检查版本');check.disabled=!node.writable;check.title=node.writable?'只检查公开版本，不发布资源':'当前为只读入口';
      check.addEventListener('click',async()=>{
        check.disabled=true; const key=crypto.randomUUID();
        try{await api(`/api/nodes/${node.id}/tasks`,{method:'POST',headers:{'Content-Type':'application/json','X-OurNotes-Request':'1'},body:JSON.stringify({profile:profile.id,action:'check',key})});status('检查任务已提交，关闭页面也会继续执行。');}
        catch(error){status(`${error.message} 提交结果可能未知，请先查看任务列表。`,true);}
        await refreshNodes();
      });
      actions.append(check);for(const title of ['拉取资源','构建候选']){const b=el('button',title);b.disabled=true;b.title='节点尚未提供隔离后的安全执行能力';actions.append(b);}row.append(description,actions);panel.append(row);
      if(profile.steps?.length) rows(panel.appendChild(el('div')),profile.steps.map(s=>[s.name,words[s.status]||s.status]));
    }
    for(const task of result.data.tasks){const row=el('div',null,'task'),name=el('div',task.message);name.append(el('small',`检查版本 · ${task.profile} · ${task.id.slice(0,8)}`));const stamp=el('time',time(task.updated));row.append(el('span',words[task.status]||task.status),name,stamp);panel.append(row);}
    if(!result.data.tasks.length)panel.append(el('p','尚未提交任务。','caption'));return panel;
  }));
}
function settings(){rows($('settings'),[
  ['连接方式',config.connection],['运行模式',config.preview?'本地只读预览':'认证代理保护'],
  ...config.sites.map(s=>[s.name,s.id,`统计时区 ${s.timezone||'Asia/Shanghai'} · ${s.nodes?.length||0} 个资源节点`]),
  ...config.nodes.map(n=>[n.name,n.writable?'可提交检查任务':'只读节点'])]);}
async function refresh(){
  if(!config||!siteId()||inFlight)return;inFlight=true;$('refresh').disabled=true;const gen=generation;
  try{
    if(currentView==='overview'){const result=await api(`/api/summary/${encodeURIComponent(siteId())}?window=${$('window').value}`);if(gen===generation)renderSummary(result);}
    else if(currentView==='load')await refreshLoads(gen);
    else if(currentView==='tasks')await refreshNodes(gen);
    else{settings();status('配置仅在后端维护 · 页面不显示密钥');}
  }catch(error){status(error.message,true);}finally{inFlight=false;$('refresh').disabled=false;if(gen!==generation)queueMicrotask(refresh);}
}
function navigate(){
  const key=location.hash.slice(1);currentView=['overview','load','tasks','settings'].includes(key)?key:'overview';generation++;
  const titles={overview:['访问与下载','了解内容如何被访问，以及资源如何被使用。'],load:['并发与带宽','观察服务器负载，保留来源和采样缺口。'],tasks:['资源任务','查看更新进度，按节点能力执行固定操作。'],settings:['节点与配置','站点、统计和资源节点可以独立部署。']};
  for(const view of document.querySelectorAll('.view'))view.hidden=view.id!==`view-${currentView}`;
  for(const a of document.querySelectorAll('[data-view]')){if(a.dataset.view===currentView)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');}
  status('正在读取对应数据…');$('updated').textContent='等待更新';
  $('title').textContent=titles[currentView][0];$('subtitle').textContent=titles[currentView][1];$('breadcrumb').textContent='网站运行 / '+titles[currentView][0];refresh();
}
$('refresh').addEventListener('click',refresh);for(const id of ['site','window','load-window'])$(id).addEventListener('change',()=>{generation++;refresh();});
$('load-source').addEventListener('change',renderLoads);addEventListener('hashchange',navigate);
try{config=await api('/api/config');$('preview').hidden=!config.preview;$('site').replaceChildren(...config.sites.map(s=>new Option(s.name||s.id,s.id)));navigate();if(!config.sites.length)status('尚未配置站点');}
catch(error){status(error.message,true);}
let tick=0;setInterval(()=>{tick++;if(!document.hidden&&(currentView!=='overview'||tick%12===0))refresh();},5000);
