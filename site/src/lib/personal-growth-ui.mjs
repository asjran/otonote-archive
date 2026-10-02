import {setupInventoryEditor} from './inventory-editor-ui.mjs';
import {createTeamDraft} from './team-draft.mjs';
import {gameServer, currentServerContext} from './game-servers.mjs';

class PersonalGrowthWorkbench extends HTMLElement {
 connectedCallback() {
  if(this.ready)return;this.ready=true;
  this.data=JSON.parse(this.querySelector('[data-personal-growth-data]').textContent);
  this.draft=createTeamDraft();
  const q=s=>this.querySelector(s),context=currentServerContext();
  q('[data-profile-server]').textContent=gameServer(context.serverId)?.label??'请先选择区服';
  this.editor=setupInventoryEditor(this,{onChange:()=>this.summary(),onUse:()=>{}});
  const form=q('[data-profile-account-form]');
  for(const row of this.data.vipRanks){const option=document.createElement('option');option.value=row.rank;option.textContent=`Lv.${row.rank}`;q('[data-profile-tgw]').append(option);}
  for(const [kind,rows] of [['instruments',this.data.instruments],['characters',this.data.characters]]) {
   for(const row of rows) {
    const label=document.createElement('label'),input=document.createElement('input');label.textContent=row.name;
    input.type='number';input.step='1';input.min=kind==='instruments'?'0':'1';input.placeholder='未记录';
    input.max=String(kind==='instruments'?Math.max(0,...this.data.formalRules.tables.BandItemSkillEffect.filter(r=>r._bandItemId===row.id).map(r=>r._level)):Math.max(...this.data.formalRules.tables.CharacterRank.map(r=>r._rank)));
    input.dataset.accountKind=kind;input.dataset.accountId=row.id;label.append(input);q(`[data-profile-${kind}]`).append(label);
   }
  }
  const restore=()=>{
   try {const account=this.personalGrowthStore.read()?.account??{};
    q('[data-profile-tgw]').value=account.tgwCardRank??'';
    for(const input of form.querySelectorAll('[data-account-kind]'))input.value=account[input.dataset.accountKind==='instruments'?'bandItems':'characterRanks']?.[input.dataset.accountId]??'';
    q('[data-profile-account-status]').textContent='';
   }catch(error){q('[data-profile-account-status]').textContent=error.message;}
  };
  form.addEventListener('submit',event=>{
   event.preventDefault();if(!form.reportValidity())return;
   try {const account={};
    if(q('[data-profile-tgw]').value!=='')account.tgwCardRank=Number(q('[data-profile-tgw]').value);
    for(const input of form.querySelectorAll('[data-account-kind]'))if(input.value!=='') {
     const field=input.dataset.accountKind==='instruments'?'bandItems':'characterRanks';(account[field]??={})[input.dataset.accountId]=Number(input.value);
    }
    this.personalGrowthStore.saveAccount(account);this.summary();q('[data-profile-account-status]').textContent='账号养成已保存。';
   }catch(error){q('[data-profile-account-status]').textContent=`未保存：${error.message}`;}
  });
  form.addEventListener('input',()=>{q('[data-profile-account-status]').textContent='有尚未保存的修改。';});
  q('[data-profile-account-reset]').addEventListener('click',restore);
  this.addEventListener('personal-growth-changed',()=>{restore();this.summary();});
  this.summary();restore();
 }
 summary() {
  const output=this.querySelector('[data-profile-summary]');
  try {const profile=this.personalGrowthStore.read();
   if(!profile){output.textContent='尚未保存养成。可导入 JSON、登录读取，或手动录入卡库。';return;}
   const {inventory,account}=profile;
   output.textContent=`成员卡 ${inventory.memberCardIds.length} 张 · 留影 ${inventory.supportCardIds.length} 张 · 乐器 ${account.bandItems?`${Object.keys(account.bandItems).length} 件`:'未记录'} · 角色评级 ${account.characterRanks?`${Object.keys(account.characterRanks).length} 名`:'未记录'} · TGW ${account.tgwCardRank??'未记录'}`;
  }catch(error){output.textContent=`养成未载入：${error.message}。原记录未修改。`;}
 }
 commit(){this.summary();}
}
if(!customElements.get('personal-growth-workbench'))customElements.define('personal-growth-workbench',PersonalGrowthWorkbench);
