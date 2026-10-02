import {setupQuickOptions} from './tool-quick-options.mjs';
import {filterCalculatorCards,cardPlacementConflict} from './calculator-card-model.mjs';
import {cardElement as el,skillPeek,closeSkillPopover,cardIdentity,setupAttributeFilter} from './calculator-card-ui.mjs';
export function setupCalculatorCardPicker(workbench) {
  const root=workbench.querySelector('.team-card-picker');if(!root)return null;
  const q=s=>root.querySelector(s),cards=[...workbench.data.memberCards,...workbench.data.supportCards],pageSize=12;
  let page=0,preview=null,kind='member';
  const attribute=setupAttributeFilter(q('[data-card-attributes]'),()=>{page=0;renderList();});
  const controls={query:'search',band:'band',character:'character',rarity:'rarity',owned:'owned',mission:'mission',effect:'effect',normal:'normal',sort:'sort'};
  function filters(){return {kind,attributes:attribute.values,...Object.fromEntries(Object.entries(controls).map(([key,suffix])=>[key,q(`[data-card-${suffix}]`).value]))};}
  function growth(card){return workbench.draft.modifiers.growth?.[card.id]??workbench.cardInventory?.growth?.[card.id];}
  function previewCard(){
    const container=q('[data-card-preview]');container.replaceChildren();
    if(!preview){container.append(el('p','点选左侧卡片，在这里查看技能，再放入队伍。'));q('[data-card-apply]').disabled=true;return;}
    container.append(cardIdentity(workbench,preview),el('p',growth(preview)?'技能按已设置的养成显示。':'技能按未突破、技能 Lv.1 显示；可在编队中调整养成。','card-growth-note'),skillPeek(workbench,preview,{growth:growth(preview),leader:workbench.activeSlot===2},container));
    const conflict=cardPlacementConflict(preview,workbench.draft,workbench.activeSlot,(...args)=>workbench.cardFor(...args));
    const same=workbench.draft.slots[workbench.activeSlot][`${kind}CardId`]===preview.id;
    const button=q('[data-card-apply]');button.disabled=conflict>=0||same;
    button.textContent=same?'已在当前位置':`放入位置 ${workbench.activeSlot+1} 的${kind==='member'?'成员':'留影'}`;
    q('[data-card-placement]').textContent=conflict>=0?`${kind==='member'?'同一角色':'这张留影'}已在位置 ${conflict+1}，请切换到该位置更换。`:same?'可继续选择其他卡片比较技能。':'确认放入后才会替换当前卡片。';
  }
  const shortcuts=setupQuickOptions(root);
  function renderList(){
    shortcuts.sync();
    closeSkillPopover(workbench);
    const f=filters(),list=filterCalculatorCards(cards,f,workbench.cardInventory),pages=Math.max(1,Math.ceil(list.length/pageSize));page=Math.min(page,pages-1);
    const container=q('[data-card-results]');container.replaceChildren();
    for(const card of list.slice(page*pageSize,(page+1)*pageSize)){
      const tile=el('article',null,'team-picker-tile'),b=el('button',null,'team-picker-card');b.type='button';b.dataset.teamCard='';b.dataset.cardId=card.id;b.dataset.kind=card.kind;
      b.setAttribute('aria-label',`预览 ${card.shortLabel}`);b.setAttribute('aria-pressed',String(preview?.id===card.id));
      b.append(cardIdentity(workbench,card));
      const state=el('span',null,'card-selection-state');
      const placed=workbench.draft.slots.findIndex(s=>s[`${kind}CardId`]===card.id);
      state.textContent=placed>=0?`已编入 · 位置 ${placed+1}`:(workbench.cardInventory?.[`${kind}CardIds`]??[]).includes(card.id)?'已拥有':'未录入卡库';b.append(state);
      tile.append(b,skillPeek(workbench,card,{growth:growth(card),leader:workbench.activeSlot===2},b));
      const place=el('button','放入队伍','card-place-direct');place.type='button';place.disabled=cardPlacementConflict(card,workbench.draft,workbench.activeSlot,(...args)=>workbench.cardFor(...args))>=0||placed===workbench.activeSlot;place.addEventListener('click',()=>{preview=card;previewCard();q('[data-card-apply]').click();});tile.append(place);

      b.addEventListener('click',()=>{preview=card;renderList();previewCard();});container.append(tile);
    }
    q('[data-card-count]').textContent=`找到 ${list.length} 张${kind==='member'?'成员卡':'留影'}`;
    q('[data-card-page]').textContent=`${page+1} / ${pages}`;q('[data-card-prev]').disabled=page===0;q('[data-card-next]').disabled=page===pages-1;q('[data-card-empty]').hidden=list.length>0;
    q('[data-clear-card]').textContent=`清空当前位置的${kind==='member'?'成员':'留影'}`;
  }
  const sync=()=>{kind=workbench.pickerKind;const current=workbench.cardFor(kind,workbench.draft.slots[workbench.activeSlot][`${kind}CardId`]);if(!preview||preview.kind!==kind)preview=current;root.querySelectorAll('[data-picker-kind]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.pickerKind===kind)));q('[data-card-slot]').value=String(workbench.activeSlot);renderList();previewCard();};
  root.querySelectorAll('[data-picker-kind]').forEach(b=>b.addEventListener('click',()=>{workbench.pickerKind=b.dataset.pickerKind;preview=null;page=0;q('[data-card-normal]').value='';sync();}));
  for(const suffix of Object.values(controls))q(`[data-card-${suffix}]`).addEventListener(suffix==='search'?'input':'change',()=>{
    if(suffix==='band'){q('[data-card-character]').value='';q('[data-card-character]').querySelectorAll('option').forEach(o=>{o.hidden=Boolean(o.value&&q('[data-card-band]').value&&o.dataset.band!==q('[data-card-band]').value);});}
    if(suffix==='mission'){q('[data-card-effect]').value='';q('[data-card-effect]').querySelectorAll('option').forEach(o=>o.hidden=Boolean(o.value&&q('[data-card-mission]').value&&!o.value.startsWith(q('[data-card-mission]').value+':')));}
    page=0;renderList();
  });
  q('[data-card-reset]').addEventListener('click',()=>{for(const suffix of Object.values(controls))q(`[data-card-${suffix}]`).value=suffix==='sort'?'rarity':'';root.querySelectorAll('option').forEach(o=>o.hidden=false);attribute.reset();page=0;renderList();});
  q('[data-card-prev]').addEventListener('click',()=>{page--;renderList();});q('[data-card-next]').addEventListener('click',()=>{page++;renderList();});
  q('[data-card-slot]').addEventListener('change',()=>{workbench.activeSlot=Number(q('[data-card-slot]').value);workbench.renderSlots();workbench.renderPickerState();workbench.productionPower?.settings();});
  q('[data-card-apply]').addEventListener('click',()=>{if(!preview||cardPlacementConflict(preview,workbench.draft,workbench.activeSlot,(...a)=>workbench.cardFor(...a))>=0)return;workbench.draft.slots[workbench.activeSlot][`${kind}CardId`]=preview.id;
    const owned=workbench.cardInventory?.growth?.[preview.id];if(owned&&!workbench.draft.modifiers.growth?.[preview.id]){workbench.draft.modifiers.growth??={};workbench.draft.modifiers.growth[preview.id]=structuredClone(owned);}
    const next=workbench.draft.slots.findIndex(s=>!s[`${kind}CardId`]);if(next>=0)workbench.activeSlot=next;
    workbench.commit();q('[data-card-placement]').textContent=`已放入位置 ${workbench.activeSlot+1}。可以切换成员／留影或继续选择其他位置。`;
  });
  q('[data-clear-card]').addEventListener('click',()=>{workbench.draft.slots[workbench.activeSlot][`${kind}CardId`]=null;preview=null;workbench.commit();});
  workbench.addEventListener('preset-inventory-changed',()=>{renderList();previewCard();});
  return {sync};
}
