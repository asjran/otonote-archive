import test from 'node:test';
import assert from 'node:assert/strict';
import {createSharedTeamRules} from './fixtures/shared-team-rules.mjs';
import {bandItemGroups,bandItemEffects,validateBandItemTotals} from '../../packages/scoring/scoring-rules/band-item-totals.mjs';
import {maximizeAccount} from '../src/lib/workbench-account-model.mjs';
import {createPersonalGrowthStore} from '../src/lib/personal-growth-store.mjs';
import {createTeamWorkspaceStore} from '../src/lib/team-workspace-store.mjs';
import {createTeamDraft} from '../src/lib/team-draft.mjs';
import {createInventoryManager} from '../src/lib/inventory-manager.mjs';
import {bandItemMaxLevel,withBandItemLevels} from '../../packages/scoring/scoring-rules/band-item-levels.mjs';
import {readFileSync} from 'node:fs';

function rulesWithFutureEffects() {
  const rules=createSharedTeamRules();
  rules.tables.BandItemLevel=[101,102].flatMap(_bandItemId=>Array.from({length:30},(_,i)=>({_bandItemId,_level:i+1,_playerRank:1})));
  for(const id of [101,102])for(let level=31;level<=50;level++)rules.tables.BandItemSkillEffect.push({_bandItemId:id,_level:level,_skillEffectType:1000,_skillTargetIDs:[],_effectValue:level});
  return rules;
}
const memory=()=>{const values=new Map();return {getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v),get length(){return values.size;},key:i=>[...values.keys()][i]};};

test('upgrade levels bound account editing, calculation, totals and maximize even when future effects exist',()=>{
  const rules=rulesWithFutureEffects(),group=bandItemGroups(rules)[0];
  assert.deepEqual(group.items.map(i=>i.maxLevel),[30,30]);assert.equal(group.maxTotal,60);
  assert.equal(bandItemEffects(rules,{bandItems:{101:30}}).length,1);
  assert.throws(()=>bandItemEffects(rules,{bandItems:{101:31}}));
  assert.deepEqual(validateBandItemTotals(rules,{1:60}),{1:60});
  assert.throws(()=>validateBandItemTotals(rules,{1:61}));
  assert.deepEqual(maximizeAccount({},rules,[],'instruments').bandItems,{101:30,102:30});
  const store=createPersonalGrowthStore({rules,context:{region:'global',serverId:'global-hmt'},storage:memory()});
  assert.throws(()=>store.saveAccount({bandItems:{101:31}}));
});

test('reading old account data repairs only over-cap instruments and preserves its exact original backup',()=>{
  const rules=rulesWithFutureEffects(),storage=memory();
  const store=createPersonalGrowthStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  const manager=createInventoryManager(rules);
  const old={...store.empty(),inventory:manager.batch(manager.empty(),['member-card-1','support-card-1'],{patch:{level:2}}),account:{bandItems:{101:50,102:7},bandItemTotals:{1:100},characterRanks:{1:3}}};
  const raw=JSON.stringify(old);storage.setItem(store.key,raw);
  const profile=store.read();
  assert.deepEqual(profile.account,{bandItems:{101:30,102:7},bandItemTotals:{1:60},characterRanks:{1:3}});
  assert.deepEqual(profile.inventory,old.inventory);
  assert.ok(Array.from({length:storage.length},(_,i)=>storage.key(i)).some(k=>k!==store.key&&storage.getItem(k)===raw));
  assert.deepEqual(store.read(),profile);
  assert.match(store.migrationNotice,/原始备份/);
});

test('current production caps come from all 25 upgrade tables, not the 50-level effect definitions',()=>{
  const rules=JSON.parse(readFileSync(new URL('../../packages/scoring/data/formal-scoring-rules.json',import.meta.url)));
  const groups=bandItemGroups(rules);assert.equal(groups.length,5);
  for(const group of groups){assert.equal(group.maxTotal,150);assert.equal(group.items.length,5);assert.ok(group.items.every(i=>i.maxLevel===30));}
});

test('caps follow changed upgrade rows and reject gaps or missing upgrade data',()=>{
  const rules=rulesWithFutureEffects();rules.tables.BandItemLevel.push({_bandItemId:101,_level:31,_playerRank:1});
  assert.equal(bandItemMaxLevel(rules,101),31);
  assert.equal(bandItemGroups(rules)[0].maxTotal,61);
  const missing=rulesWithFutureEffects();delete missing.tables.BandItemLevel;
  assert.throws(()=>bandItemMaxLevel(missing,101),/缺少/);
  const gap=rulesWithFutureEffects();gap.tables.BandItemLevel=gap.tables.BandItemLevel.filter(r=>r._level!==2);
  assert.throws(()=>bandItemEffects(gap,{bandItems:{101:2}}));assert.equal(bandItemGroups(gap)[0].supported,false);
});

test('old content uses the matching upgrade projection without mutating the sealed rules',()=>{
  const rules=rulesWithFutureEffects(),rows=rules.tables.BandItemLevel;delete rules.tables.BandItemLevel;
  const projection={sourceReleaseId:rules.sourceReleaseId,items:[101,102].map(masterId=>({masterId,levels:rows.filter(r=>r._bandItemId===masterId).map(r=>({level:r._level,playerRank:r._playerRank}))}))};
  assert.throws(()=>withBandItemLevels(rules,{...projection,sourceReleaseId:'another-release'}),/版本不一致/);
  const restored=withBandItemLevels(rules,projection);
  assert.equal(bandItemMaxLevel(restored,101),30);assert.equal(rules.tables.BandItemLevel,undefined);
  assert.equal(withBandItemLevels(rules,projection),restored);
});

test('quota failure leaves the original record intact and still opens a safe account',()=>{
  const rules=rulesWithFutureEffects(),storage=memory(),store=createPersonalGrowthStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  const raw=JSON.stringify({...store.empty(),account:{bandItems:{101:50}}});storage.setItem(store.key,raw);
  storage.setItem=()=>{throw Error('quota');};
  assert.equal(store.read().account.bandItems[101],30);assert.equal(storage.getItem(store.key),raw);
  assert.match(store.migrationNotice,/保存修正失败/);
});

test('malformed and wrong-server profiles are never repaired or overwritten',()=>{
  const rules=rulesWithFutureEffects(),storage=memory(),store=createPersonalGrowthStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  for(const profile of [{...store.empty(),account:{bandItems:{101:'50'}}},{...store.empty(),serverId:'global-en',account:{bandItems:{101:50}}},{...store.empty(),account:[]}]){
    const raw=JSON.stringify(profile);storage.setItem(store.key,raw);assert.throws(()=>store.read());assert.equal(storage.getItem(store.key),raw);assert.equal(storage.length,1);
  }
});

test('saved teams and recent drafts migrate together and retain their exact original backup',()=>{
  const rules=rulesWithFutureEffects(),storage=memory(),store=createTeamWorkspaceStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  const draft=createTeamDraft({slots:Array.from({length:5},(_,i)=>({memberCardId:`member-card-${i+1}`,supportCardId:`support-card-${i+1}`})),modifiers:{bandItems:{101:50},bandItemTotals:{1:100},memoryPoints:{1:17}}});
  const old={...store.empty(),teams:[{id:'original',name:'Existing',draft}],recentDraft:draft,revision:4};
  const raw=JSON.stringify(old);storage.setItem(store.key,raw);const state=store.read();
  assert.equal(state.revision,5);assert.equal(state.teams[0].id,'original');
  for(const entry of [state.teams[0].draft,state.recentDraft]){assert.equal(entry.modifiers.bandItems[101],30);assert.equal(entry.modifiers.bandItemTotals[1],60);assert.equal(entry.modifiers.memoryPoints[1],17);}
  assert.equal(store.read().revision,5);
  assert.ok(Array.from({length:storage.length},(_,i)=>storage.key(i)).some(k=>k!==store.key&&storage.getItem(k)===raw));
  assert.throws(()=>store.setRecentDraft(draft,{expectedRevision:5}));
});

test('different old records never overwrite an earlier backup, including failure after the backup write',()=>{
  const rules=rulesWithFutureEffects(),storage=memory(),store=createPersonalGrowthStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  const original=JSON.stringify({...store.empty(),account:{bandItems:{101:50}}});storage.setItem(store.key,original);store.read();
  const second=JSON.stringify({...store.empty(),account:{bandItems:{101:40}}});storage.setItem(store.key,second);
  const write=storage.setItem;storage.setItem=(key,value)=>{if(key===store.key)throw Error('quota');write(key,value);};
  assert.equal(store.read().account.bandItems[101],30);assert.equal(storage.getItem(store.key),second);
  assert.equal(storage.getItem(store.key+':band-item-caps:v1:backup:1'),original);
  assert.equal(storage.getItem(store.key+':band-item-caps:v1:backup:2'),second);
});

test('legacy team migration clamps account levels without altering the selected original preset',()=>{
  const rules=rulesWithFutureEffects(),storage=memory(),store=createTeamWorkspaceStore({rules,context:{region:'global',serverId:'global-hmt'},storage});
  const draft=createTeamDraft({slots:Array.from({length:5},(_,i)=>({memberCardId:`member-card-${i+1}`,supportCardId:`support-card-${i+1}`})),modifiers:{bandItems:{101:50}}});
  const key='ournotes:presets:global:global-hmt:old',raw=JSON.stringify({schemaVersion:1,region:'global',serverId:'global-hmt',candidates:[{name:'Legacy',draft}]});
  storage.setItem(key,raw);assert.equal(store.migrateLegacy(key).teams[0].draft.modifiers.bandItems[101],30);assert.equal(storage.getItem(key),raw);
});
