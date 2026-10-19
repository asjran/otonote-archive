/** A percentage describes the reported stage, never an estimated time remaining. */
export function progressSnapshot({label='正在计算',completed,total,detail='',state='running'}={}) {
 const known=Number.isFinite(completed)&&Number.isFinite(total)&&total>0;
 const done=known?Math.max(0,Math.min(total,completed)):null;
 return {label,detail,state,completed:done,total:known?total:null,
  fraction:known?done/total:null,counter:known?`${done.toLocaleString()} / ${total.toLocaleString()}`:''};
}

export function createCalculationProgress(anchor,kind) {
 const root=document.createElement('section');root.className='calculation-progress';root.dataset.calculationProgress=kind;root.hidden=true;
 const heading=document.createElement('div'),label=document.createElement('strong'),counter=document.createElement('span'),bar=document.createElement('progress'),detail=document.createElement('small');
 heading.append(label,counter);bar.max=1;root.append(heading,bar,detail);anchor.before(root);
 let previous;
 function update(input){
  const p=progressSnapshot(input);root.hidden=false;root.dataset.state=p.state;
  if(p.label!==previous?.label)label.textContent=p.label;
  if(p.counter!==previous?.counter||p.state!==previous?.state)counter.textContent=p.state==='complete'?'已完成':p.counter;
  if(p.detail!==previous?.detail)detail.textContent=p.detail;detail.hidden=!p.detail;
  if(p.label!==previous?.label||p.counter!==previous?.counter)bar.setAttribute('aria-label',`${p.label}${p.counter?' · 当前阶段 '+p.counter:''}`);
  if(!previous||p.fraction!==previous.fraction){if(p.fraction===null)bar.removeAttribute('value');else bar.value=p.fraction;}
  bar.hidden=p.state==='error'||p.state==='stopped';previous=p;
 }
 return {update,reset:()=>{root.hidden=true;},finish:(label,detail='',state='complete')=>update({label,detail,state,completed:state==='complete'?1:undefined,total:state==='complete'?1:undefined})};
}
