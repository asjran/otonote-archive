import {filterCalculatorCards} from './calculator-card-model.mjs';
import {skillPeek,cardIdentity,setupAttributeFilter} from './calculator-card-ui.mjs';
import {createInventoryManager,growthFields,growthLabels} from './inventory-manager.mjs';
import {setupAccountGrowthImport} from './account-growth-ui.mjs';

const el=(tag,text='',cls='')=>{const n=document.createElement(tag);n.textContent=text;n.className=cls;return n;};
function download(name,text,type) {
  const url=URL.createObjectURL(new Blob([text],{type})),a=el('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const describeGrowth=g=>`Lv.${g.level} · 突破 ${g.rank}${g.awake?` · 觉醒 ${g.awake} · 技能 ${g.skillLevel}/${g.gekisouSkillLevel}`:''}`;

export function setupInventoryEditor(workbench,{onChange,onUse}) {
  const q=s=>workbench.querySelector(s),cards=[...workbench.data.memberCards,...workbench.data.supportCards];
  const manager=createInventoryManager(workbench.data.formalRules,cards),key=`ournotes:inventory:${workbench.data.formalRules.sourceReleaseId}`;
  let inventory=manager.empty(),undo=null,page=0,preview=null,fileRequest=0;
  const selected=new Set(),pageSize=12,status=q('[data-inventory-status]');
  try{const saved=localStorage.getItem(key);if(saved)inventory=manager.validate(JSON.parse(saved));}
  catch(error){status.textContent=`卡库未载入：${error.message}。原备份仍保留在浏览器中。`;}
  const kind=()=>q('[data-inventory-kind]').value;
  function clearPreview(){preview=null;q('[data-inventory-apply]').disabled=true;q('[data-inventory-preview-results]').replaceChildren();}
  const attributes=setupAttributeFilter(q('[data-inventory-attributes]'),()=>{page=0;render();});
  const filterKeys=['query','rarity','owned','band','character','mission','effect','normal','sort'];
  for(const option of workbench.data.skillFilterFacets?.find(f=>f.name==='gekisou-effect')?.options??[]){const o=el('option',option.label);o.value=option.value;q('[data-inventory-effect]').append(o);}
  function filtered() { return filterCalculatorCards(cards,{kind:kind(),attributes:attributes.values,...Object.fromEntries(filterKeys.map(k=>[k,q(`[data-inventory-${k}]`).value]))},inventory); }
  function selectionStatus() {
    q('[data-inventory-selection-count]').textContent=`已选 ${selected.size} 张${kind()==='member'?'成员':'留影'}`;
    for(const selector of ['[data-inventory-add]','[data-inventory-remove]','[data-inventory-clear-selection]','[data-inventory-batch]'])for(const n of workbench.querySelectorAll(selector))n.disabled=!selected.size;
  }
  function selectionChanged() {
    const single=selected.size===1?inventory.growth[[...selected][0]]:null;
    for(const field of growthFields)q(`[data-inventory-growth="${field}"]`).value=single?.[field]??'';
    selectionStatus();
  }
  function render() {
    workbench.cardInventory=inventory;
    q('[data-inventory-count]').textContent=`${inventory.memberCardIds.length} 张成员 · ${inventory.supportCardIds.length} 张留影`;
    const list=filtered(),pages=Math.max(1,Math.ceil(list.length/pageSize));page=Math.min(page,pages-1);
    const root=q('[data-inventory-cards]');root.replaceChildren();
    for(const card of list.slice(page*pageSize,(page+1)*pageSize)) {
      const owned=inventory[`${card.kind}CardIds`].includes(card.id),tile=el('article','','inventory-card');tile.dataset.owned=String(owned);tile.dataset.selected=String(selected.has(card.id));
      const label=el('label','','inventory-card-select'),check=el('input');check.type='checkbox';check.checked=selected.has(card.id);check.setAttribute('aria-label',`选择 ${card.shortLabel} ${card.relationLabel??''}`);
      check.addEventListener('change',()=>{if(check.checked)selected.add(card.id);else selected.delete(card.id);tile.dataset.selected=String(check.checked);selectionChanged();});
      label.append(check,cardIdentity(workbench,card));tile.append(label,el('span',owned?'已拥有':'未录入','card-selection-state'),el('span',owned?describeGrowth(inventory.growth[card.id]):'未录入 · 以下为满级技能预览','inventory-card-growth'));
      tile.append(skillPeek(workbench,card,{growth:inventory.growth[card.id],maximum:!owned},tile));root.append(tile);
    }
    if(!list.length)root.append(el('p','没有符合筛选的卡片，试试缩短关键词或选择“全部卡片”。'));
    q('[data-inventory-filter-count]').textContent=`${list.length} 张${kind()==='member'?'成员卡':'留影'}`;
    q('[data-inventory-page]').textContent=`${list.length} 张卡 · 第 ${page+1} / ${pages} 页`;
    q('[data-inventory-prev]').disabled=page===0;q('[data-inventory-next]').disabled=page>=pages-1;
    q('[data-inventory-undo]').disabled=!undo;
    for(const f of growthFields.slice(2))q(`[data-inventory-growth-label="${f}"]`).hidden=kind()!=='member';
    selectionStatus();
  }
  function commit(next,message) {
    next=manager.validate(next);undo=structuredClone(inventory);inventory=next;clearPreview();
    persist(message);workbench.cardInventory=inventory;onChange(inventory);render();selectionChanged();
  }
  function persist(message) {
    try{localStorage.setItem(key,JSON.stringify(inventory));status.textContent=message;}
    catch{status.textContent=`${message} 浏览器保存失败，请导出备份以免丢失。`;}
  }
  function action(fn){try{fn();}catch(error){status.textContent=`未修改卡库：${error.message}`;}}
  function preparePreview() {
    clearPreview();
    try {
      const rows=manager.preview(q('[data-inventory-paste]').value,{kind:q('[data-inventory-import-kind]').value});
      const errors=rows.filter(r=>r.error),root=q('[data-inventory-preview-results]');
      if(errors.length){for(const r of errors)root.append(el('p',`第 ${r.line} 条：${r.error}`));return;}
      preview=manager.merge(inventory,rows,{updateExisting:q('[data-inventory-overwrite]').checked,presetMode:q('[data-inventory-import-preset]').value});
      const counts=preview.changes.reduce((acc,r)=>(acc[r.action]=(acc[r.action]??0)+1,acc),{});
      root.append(el('p',Object.entries(counts).map(([k,v])=>`${k} ${v} 张`).join(' · ')+'。确认后写入卡库。'));
      const list=el('ul');for(const r of preview.changes)list.append(el('li',`${r.action} · ${r.name} (${r.id}) · ${describeGrowth(r.growth)}`));root.append(list);
      q('[data-inventory-apply]').disabled=false;
    }catch(error){q('[data-inventory-preview-results]').textContent=`不能导入：${error.message}`;}
  }
  q('[data-inventory-editor]').addEventListener('toggle',()=>{if(q('[data-inventory-editor]').open)render();});
  for(const key of ['kind',...filterKeys])q(`[data-inventory-${key}]`).addEventListener(key==='query'?'input':'change',()=>{
    if(key==='kind'){selected.clear();q('[data-inventory-normal]').value='';selectionChanged();}
    if(key==='band'){q('[data-inventory-character]').value='';q('[data-inventory-character]').querySelectorAll('option').forEach(o=>o.hidden=Boolean(o.value&&q('[data-inventory-band]').value&&o.dataset.band!==q('[data-inventory-band]').value));}
    if(key==='mission'){q('[data-inventory-effect]').value='';q('[data-inventory-effect]').querySelectorAll('option').forEach(o=>o.hidden=Boolean(o.value&&q('[data-inventory-mission]').value&&!o.value.startsWith(q('[data-inventory-mission]').value+':')));}
    page=0;render();
  });
  q('[data-inventory-reset]').addEventListener('click',()=>{for(const key of filterKeys)q(`[data-inventory-${key}]`).value=key==='sort'?'rarity':'';for(const key of ['character','effect'])q(`[data-inventory-${key}]`).querySelectorAll('option').forEach(o=>o.hidden=false);attributes.reset();page=0;render();});
  q('[data-inventory-select-visible]').addEventListener('click',()=>{filtered().forEach(c=>selected.add(c.id));render();selectionChanged();});
  q('[data-inventory-clear-selection]').addEventListener('click',()=>{selected.clear();render();selectionChanged();});
  q('[data-inventory-prev]').addEventListener('click',()=>{page--;render();});
  q('[data-inventory-next]').addEventListener('click',()=>{page++;render();});
  q('[data-inventory-add]').addEventListener('click',()=>action(()=>commit(manager.batch(inventory,[...selected]),`已将所选 ${selected.size} 张卡加入卡库；已有养成保留。`)));
  q('[data-inventory-remove]').addEventListener('click',()=>action(()=>{
    const next=structuredClone(inventory);for(const k of ['member','support'])next[`${k}CardIds`]=next[`${k}CardIds`].filter(id=>!selected.has(id));
    commit(next,'已移出所选卡片，可撤销。');selected.clear();render();
  }));
  for(const button of workbench.querySelectorAll('[data-inventory-batch]'))button.addEventListener('click',()=>action(()=>{
    const mode=button.dataset.inventoryBatch,patch={};
    for(const f of kind()==='member'?growthFields:growthFields.slice(0,2)) {
      const input=q(`[data-inventory-growth="${f}"]`);if(input.value==='')continue;
      if(mode==='custom'&&!input.checkValidity())throw new Error(`${growthLabels[f]}填写无效`);patch[f]=Number(input.value);
    }
    if(mode==='custom'&&!Object.keys(patch).length)throw new Error('请填写至少一项养成');
    commit(manager.batch(inventory,[...selected],{mode,patch}),`已更新 ${selected.size} 张卡的养成，可撤销。`);
  }));
  q('[data-inventory-undo]').addEventListener('click',()=>{if(!undo)return;inventory=undo;undo=null;clearPreview();persist('已撤销上次修改。');workbench.cardInventory=inventory;onChange(inventory);render();selectionChanged();});
  q('[data-inventory-use]').addEventListener('click',()=>onUse());
  q('[data-inventory-from-draft]').addEventListener('click',()=>action(()=>{
    const rows=[];
    for(const k of ['member','support'])for(const slot of workbench.draft.slots) {
      const id=slot[`${k}CardId`];if(!id||rows.some(r=>r.id===id))continue;
      const raw=Object.fromEntries(Object.entries(workbench.draft.modifiers.growth?.[id]??{}).filter(([field,value])=>growthFields.includes(field)&&value!==undefined));
      const g=manager.preset(id,k,'level',{...manager.preset(id,k),...raw});
      rows.push({id,kind:k,patch:{...g,...raw}});
    }
    if(!rows.length)throw new Error('当前编成还没有卡片');
    commit(manager.merge(inventory,rows).inventory,'已加入当前编成，已有卡的养成保留。');
  }));
  q('[data-inventory-export]').addEventListener('click',()=>download('otonote-inventory.json',JSON.stringify(inventory,null,2),'application/json'));
  q('[data-inventory-template]').addEventListener('click',()=>download('otonote-inventory-template.csv','\uFEFF类型,卡片ID,等级,突破阶数,觉醒阶数,演出技能,激奏技能\n成员,member-card-1,1,1,1,1,1\n留影,support-card-1,1,1,,,\n','text/csv;charset=utf-8'));
  q('[data-inventory-preview]').addEventListener('click',preparePreview);
  q('[data-inventory-apply]').addEventListener('click',()=>action(()=>{if(preview)commit(preview.inventory,'导入完成，已有卡库已合并。可撤销上次修改。');}));
  for(const selector of ['[data-inventory-paste]','[data-inventory-import-kind]','[data-inventory-import-preset]','[data-inventory-overwrite]'])q(selector).addEventListener('input',()=>{fileRequest++;clearPreview();});
  q('[data-inventory-import]').addEventListener('change',async event=>{
    const current=++fileRequest;clearPreview();
    try{const file=event.target.files[0];if(!file)return;if(file.size>2_000_000)throw new Error('文件过大（最多 2 MB）');const text=await file.text();if(current!==fileRequest)return;q('[data-inventory-paste]').value=text;preparePreview();}
    catch(error){if(current===fileRequest)status.textContent=`读取失败：${error.message}`;}finally{event.target.value='';}
  });
  setupAccountGrowthImport(workbench,{getInventory:()=>inventory,replaceInventory:commit});
  render();return {get inventory(){return inventory;},validate:manager.validate};
}
