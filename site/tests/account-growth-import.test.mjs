import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {convertGrowthSnapshot,growthModifiersForDraft} from '../src/lib/account-growth-import.mjs';
import {createTeamDraft,serializeTeamDraftSearch} from '../src/lib/team-draft.mjs';
const rules=JSON.parse(fs.readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const vip=[{rank:1,requiredPoints:0},{rank:2,requiredPoints:2000}];
const fixture=()=>({format:'ournotes-growth-snapshot',schemaVersion:1,source:{region:'TW/HK/MO'},
  coverage:{memberCards:'observed',supportCards:'observed',bandItems:'observed',characterRanks:'observed',tgw:'observed'},
  growth:{memberCards:[{masterId:1,exp:70,cardRank:1,awakeCount:1,liveSkillLevel:2,gekisouSkillLevel:3}],
    supportCards:[{masterId:1,exp:0,cardRank:1,duplicateCount:0}],bandItems:[],characterRanks:[{characterId:1,exp:1}],tgw:{point:2000}}});

test('maps five groups to inventory and account modifiers, recomputing levels',()=>{
  const input=fixture();input.derived={growth:{tgw:{level:21},memberCards:[{masterId:1,level:999}]}};
  const original=JSON.stringify(input),result=convertGrowthSnapshot(input,rules,vip);
  assert.deepEqual(result.inventory.growth['member-card-1'],{level:2,rank:1,awake:1,skillLevel:2,gekisouSkillLevel:3});
  assert.equal(result.modifiers.characterRanks[1],2);assert.equal(result.modifiers.tgwCardRank,2);
  assert.deepEqual(result.modifiers.bandItems,{});assert.equal(JSON.stringify(input),original);
  assert.deepEqual(convertGrowthSnapshot(result.safeSnapshot,rules,vip).inventory,result.inventory);
});
test('does not turn missing account groups into zero or overwrite candidates',()=>{
  const input=fixture();input.growth.tgw=null;input.coverage.tgw='not_observed';
  input.growth.bandItems=null;input.coverage.bandItems='not_observed';
  const result=convertGrowthSnapshot(input,rules,vip);
  assert.equal(result.summary.tgw,null);assert.equal(Object.hasOwn(result.modifiers,'tgwCardRank'),false);
  assert.equal(Object.hasOwn(result.modifiers,'bandItems'),false);
});
test('drops private and unknown fields from saved snapshot',()=>{
  const input=fixture();input.password='PRIVATE';input.source.token='PRIVATE';input.growth.memberCards[0].credential='PRIVATE';
  assert.equal(JSON.stringify(convertGrowthSnapshot(input,rules,vip)).includes('PRIVATE'),false);
});
test('applies account bonuses and selected growth without sharing the full inventory',()=>{
  const converted=convertGrowthSnapshot(fixture(),rules,vip);
  for(let i=100;i<600;i++)converted.modifiers.growth[`member-card-${i}`]={level:1,rank:1};
  const draft=createTeamDraft({slots:[{memberCardId:'member-card-1'}],
    modifiers:{memoryBonuses:{1:50},tgwCardRank:1,growth:{'member-card-1':{level:1}}}});
  const before=JSON.stringify(draft),next=growthModifiersForDraft(converted,draft);
  assert.deepEqual(Object.keys(next.growth),['member-card-1']);
  assert.equal(next.growth['member-card-1'].level,2);assert.equal(next.tgwCardRank,2);
  assert.deepEqual(next.memoryBonuses,{1:50});assert.equal(JSON.stringify(draft),before);
  assert.ok(serializeTeamDraftSearch({...draft,modifiers:next}).length<2000);
  next.growth['member-card-1'].level=10;assert.equal(converted.inventory.growth['member-card-1'].level,2);
});
test('rejects incompatible, unknown, repeated and invalid data atomically',()=>{
  for(const change of [s=>s.schemaVersion=2,s=>s.source.region='JP',
    s=>s.growth.memberCards.push({...s.growth.memberCards[0]}),s=>s.growth.memberCards[0].masterId=999999999,
    s=>s.growth.memberCards[0].exp=-1,s=>s.growth.memberCards[0].awakeCount=0,
    s=>s.growth.memberCards[0].liveSkillLevel='2',s=>s.growth.memberCards[0].exp=2147483647,
    s=>s.growth.tgw.point=true,s=>s.coverage.supportCards='not_observed']) {
    const input=fixture();change(input);assert.throws(()=>convertGrowthSnapshot(input,rules,vip));
  }
});
