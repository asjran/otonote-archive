import {convertGrowthSnapshot, growthModifiersForDraft} from './account-growth-import.mjs';

const messages={credentials_rejected:'官方服务提示账号或密码校验未通过。',account_not_found:'官方服务提示账号不存在。',
  verification_required:'需要额外验证，当前工具已停止。',rate_limited:'请求过于频繁，请稍后再试。'};
export function setupAccountGrowthImport(workbench,{getInventory,replaceInventory}) {
  const root=workbench.querySelector('[data-account-growth]');if(!root)return;
  const q=s=>root.querySelector(s),status=q('[data-growth-status]'),fields=q('[data-growth-login-fields]');
  const rules=workbench.data.formalRules,convert=value=>convertGrowthSnapshot(value,rules,workbench.data.vipRanks);
  const storageKey=`ournotes:account-growth:${rules.sourceReleaseId}`;
  let nonce=null,busy=false,preview=null,undo=null;
  function changed(){if(typeof workbench.commit==='function')workbench.commit();else workbench.refreshInput?.();}
  function save(value){try{if(value===null)localStorage.removeItem(storageKey);else localStorage.setItem(storageKey,JSON.stringify(value));return true;}catch{return false;}}
  try {
    const stored=localStorage.getItem(storageKey);
    if(stored){const saved=convert(JSON.parse(stored));
      const restored=growthModifiersForDraft(saved,workbench.draft);
      workbench.draft.modifiers={...restored,...workbench.draft.modifiers,
        growth:{...restored.growth,...workbench.draft.modifiers?.growth}};}
  }catch{status.textContent='保存的账号养成未载入，请重新导入；原备份仍保留。';}
  function clear(){preview=null;q('[data-growth-preview]').hidden=true;q('[data-growth-apply]').disabled=true;q('[data-growth-download]').disabled=true;}
  function prepare(snapshot){
    clear();const converted=convert(snapshot);preview=converted;
    const s=converted.summary,node=q('[data-growth-preview]');node.replaceChildren();node.hidden=false;
    const summary=document.createElement('p');summary.textContent=`角色卡 ${s.memberCards} 张 · 留影 ${s.supportCards} 张 · 乐器 ${s.bandItems??'未读取'} 件 · 角色评级 ${s.characterRanks??'未读取'} 名 · TGW ${s.tgw===null?'未读取':`${s.tgw} 级`}`;
    const note=document.createElement('p');note.textContent='应用后替换当前卡库，并更新已读取的账号加成。未读取的项目和回忆加成保留原值。请核对是否与游戏一致。';node.append(summary,note);
    q('[data-growth-apply]').disabled=false;q('[data-growth-download]').disabled=false;status.textContent='读取完成，请预览后应用。';
  }
  fetch('/api/growth-export/capabilities/',{cache:'no-store',credentials:'same-origin'})
    .then(async r=>{if(!r.ok)throw Error();const result=await r.json();if(result.enabled!==true||typeof result.nonce!=='string')throw Error();
      nonce=result.nonce;fields.disabled=busy;q('[data-growth-service-status]').textContent='网页登录已就绪，登录请求将经过本站服务端。';})
    .catch(()=>{q('[data-growth-service-status]').textContent='网页登录服务暂未启用，可先导入本地养成 JSON。';});
  q('[data-growth-login]').addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!nonce)return;busy=true;clear();fields.disabled=true;q('[data-growth-file]').disabled=true;
    let body=JSON.stringify({account:q('[data-growth-account]').value,password:q('[data-growth-password]').value});
    q('[data-growth-password]').value='';status.textContent='正在登录并读取养成，请稍候。不会自动重试。';
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),150000);
    try {
      const request=fetch('/api/growth-export/read/',{method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json','X-Growth-Nonce':nonce},body,signal:controller.signal});body='';
      const response=await request;
      if(Number(response.headers.get('content-length'))>2_000_000)throw new Error('返回文件过大，未导入。');
      const text=await response.text();if(text.length>2_000_000)throw new Error('返回文件过大，未导入。');
      let result;try{result=JSON.parse(text);}catch{throw new Error('服务暂不可用，请稍后再试。');}
      if(!response.ok){const code=typeof result.error==='string'&&/^sdk_service_-?\d+$/.test(result.error)?`（${result.error}）`:'';
        throw new Error(messages[result.reason]??(response.status===429?'服务繁忙，请稍后再试。':response.status===403?'页面已过期，请刷新后再试。':`读取未完成，请稍后再试。${code}`));}
      prepare(result.snapshot);
    }catch(error){status.textContent=error.name==='AbortError'?'读取超时，未修改卡库。':error.message;}
    finally{body='';clearTimeout(timer);busy=false;fields.disabled=false;q('[data-growth-file]').disabled=false;}
  });
  q('[data-growth-file]').addEventListener('change',async event=>{
    if(busy)return;clear();busy=true;fields.disabled=true;q('[data-growth-file]').disabled=true;
    try{const file=event.target.files[0];if(!file)return;if(file.size>2_000_000)throw new Error('文件超过 2 MB。');prepare(JSON.parse(await file.text()));}
    catch(error){status.textContent=`未导入：${error.message}`;}
    finally{event.target.value='';busy=false;fields.disabled=!nonce;q('[data-growth-file]').disabled=false;}
  });
  q('[data-growth-apply]').addEventListener('click',()=>{
    if(!preview||busy)return;
    const next=preview,previous={inventory:structuredClone(getInventory()),modifiers:structuredClone(workbench.draft.modifiers),stored:null};
    try{previous.stored=localStorage.getItem(storageKey);}catch{}
    replaceInventory(next.inventory,'已应用游戏养成。');
    workbench.draft.modifiers=growthModifiersForDraft(next,workbench.draft);
    const persisted=save(next.safeSnapshot);undo=previous;changed();q('[data-growth-undo]').disabled=false;
    q('[data-growth-apply]').disabled=true;status.textContent=`已应用卡库及账号加成，可开始配队。${persisted?'':'浏览器保存失败，请下载备份。'}`;
  });
  q('[data-growth-undo]').addEventListener('click',()=>{
    if(!undo||busy)return;const previous=undo;undo=null;
    replaceInventory(previous.inventory,'已撤销账号养成导入。');workbench.draft.modifiers=previous.modifiers;
    let persisted=true;try{if(previous.stored===null)localStorage.removeItem(storageKey);else localStorage.setItem(storageKey,previous.stored);}catch{persisted=false;}
    changed();q('[data-growth-undo]').disabled=true;q('[data-growth-apply]').disabled=!preview;status.textContent='已恢复导入前的卡库及账号加成。'+(persisted?'':'浏览器保存失败，请导出备份。');
  });
  q('[data-growth-download]').addEventListener('click',()=>{
    if(!preview)return;const url=URL.createObjectURL(new Blob([JSON.stringify(preview.safeSnapshot,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='ournotes-growth.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
}
