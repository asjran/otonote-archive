const states = new WeakMap();
const labels = {views:'浏览量',downloads:'下载点击',txMbps:'出站 Mbps',rxMbps:'入站 Mbps',active:'连接数',rps:'请求/秒'};
const fmt = n => new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(n);
const stamp = ts => new Date(ts*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});
const node = (tag,text) => {const e=document.createElement(tag);if(text!=null)e.textContent=text;return e;};
export function chart(container, points, keys, title, gapSeconds=Infinity, exportUrl=null) {
  let state=states.get(container);
  if(!state){state={enabled:new Set(keys),from:0,to:1,focus:0};states.set(container,state);}
  const draw=()=>{
    container.replaceChildren();
    if(!points.some(p=>keys.some(k=>Number.isFinite(p[k])))){container.append(node('p','尚无有效采样；未采集的数据不会画成零。'));return;}
    const first=points[0].ts,last=points.at(-1).ts,span=last-first||1;
    const start=first+state.from*span,end=first+state.to*span;
    const shown=points.filter(p=>p.ts>=start&&p.ts<=end),active=keys.filter(k=>state.enabled.has(k));
    const toolbar=node('div');toolbar.className='chart-tools';
    const button=(text,fn)=>{const b=node('button',text);b.type='button';b.addEventListener('click',fn);toolbar.append(b);return b;};
    for(const key of keys){const b=button(labels[key]||key,()=>{if(state.enabled.has(key)){if(state.enabled.size>1)state.enabled.delete(key);}else state.enabled.add(key);draw();});b.setAttribute('aria-pressed',String(state.enabled.has(key)));}
    const zoom=factor=>{const width=Math.min(1,Math.max(.01,(state.to-state.from)*factor)),middle=(state.to+state.from)/2;state.from=Math.max(0,Math.min(1-width,middle-width/2));state.to=state.from+width;draw();};
    button('放大',()=>zoom(.5));button('缩小',()=>zoom(2));button('复位',()=>{state.from=0;state.to=1;draw();});
    button('导出 CSV',()=>{
      if(exportUrl){const a=node('a');a.href=exportUrl+'&'+new URLSearchParams({fields:active.join(','),start:String(start),end:String(end)});a.download='ournotes.csv';document.body.append(a);a.click();a.remove();return;}
      const content='\uFEFF'+[['时间（北京时间）',...active.map(k=>labels[k]||k)],...shown.map(p=>[stamp(p.ts),...active.map(k=>p[k]??'')])].map(row=>row.map(v=>'"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
      const url=URL.createObjectURL(new Blob([content],{type:'text/csv;charset=utf-8'}));const a=node('a');a.href=url;a.download=title+'.csv';a.hidden=true;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    });
    container.append(toolbar);
    if(state.to-state.from<1){const label=node('label','移动时间窗口');label.className='chart-pan';const input=node('input');input.type='range';input.min='0';input.max=String(1-(state.to-state.from));input.step='.001';input.value=String(state.from);input.setAttribute('aria-label',title+'时间窗口');input.addEventListener('input',()=>{const width=state.to-state.from;state.from=Number(input.value);state.to=state.from+width;draw();});label.append(input);container.append(label);}
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 800 200');svg.setAttribute('role','img');svg.setAttribute('tabindex','0');svg.setAttribute('aria-label',title+'；左右方向键查看读数，拖动选择时间范围');
    const add=(tag,attrs,text)=>{const e=document.createElementNS(ns,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,String(v));if(text!=null)e.textContent=text;svg.append(e);return e;};
    const values=shown.flatMap(p=>active.map(k=>p[k]).filter(Number.isFinite));let maximum=1;for(const v of values)maximum=Math.max(maximum,v);maximum*=1.12;
    const x=t=>48+(t-start)/(end-start||1)*734,y=v=>164-v/maximum*148;
    for(let i=0;i<4;i++){const value=maximum*i/3;add('line',{x1:48,x2:782,y1:y(value),y2:y(value),class:'grid'});add('text',{x:38,y:y(value)+4,'text-anchor':'end'},fmt(value));}
    for(const key of active){let path='',previous=null;for(const p of shown){if(!Number.isFinite(p[key])){previous=null;continue;}path+=`${previous==null||p.ts-previous>gapSeconds||p.gap?'M':'L'}${x(p.ts)},${y(p[key])} `;previous=p.ts;}
      add('path',{d:path,class:keys.indexOf(key)?'line teal':'line'});if(shown.length===1&&Number.isFinite(shown[0][key]))add('circle',{cx:x(shown[0].ts),cy:y(shown[0][key]),r:3,fill:keys.indexOf(key)?'#167d6a':'#287bb8'});
    }
    const short=t=>new Date(t*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
    add('text',{x:48,y:190},short(start));add('text',{x:782,y:190,'text-anchor':'end'},short(end));
    const cross=add('line',{x1:48,x2:48,y1:8,y2:165,class:'crosshair',visibility:'hidden'});
    const readout=node('div','悬停或使用左右方向键查看读数 · 拖动图表可选择范围');readout.className='chart-readout';readout.setAttribute('role','status');
    const show=i=>{if(!shown.length)return;state.focus=Math.max(0,Math.min(shown.length-1,i));const p=shown[state.focus];cross.setAttribute('x1',x(p.ts));cross.setAttribute('x2',x(p.ts));cross.setAttribute('visibility','visible');readout.textContent=stamp(p.ts)+' · '+active.map(k=>(labels[k]||k)+' '+(p[k]==null?'无采样':fmt(p[k]))).join(' · ')+(p.gap?' · 采样不完整':'');};
    const fraction=e=>{const rect=svg.getBoundingClientRect();return Math.max(0,Math.min(1,((e.clientX-rect.left)/rect.width*800-48)/734));};
    svg.addEventListener('pointermove',e=>{const ts=start+fraction(e)*(end-start);let nearest=0;for(let i=1;i<shown.length;i++)if(Math.abs(shown[i].ts-ts)<Math.abs(shown[nearest].ts-ts))nearest=i;show(nearest);});
    let drag=null;svg.addEventListener('pointerdown',e=>{drag=fraction(e);svg.setPointerCapture(e.pointerId);});
    svg.addEventListener('pointerup',e=>{const stop=fraction(e);if(drag!=null&&Math.abs(stop-drag)>.03){const width=state.to-state.from,origin=state.from;state.from=origin+Math.min(drag,stop)*width;state.to=origin+Math.max(drag,stop)*width;draw();}drag=null;});
    svg.addEventListener('pointercancel',()=>{drag=null;});
    svg.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();show(e.key==='Home'?0:e.key==='End'?shown.length-1:state.focus+(e.key==='ArrowRight'?1:-1));}});
    container.append(svg,readout);
  };
  draw();
}
