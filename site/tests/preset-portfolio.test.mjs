import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { preparePresetDraft, presetWindowCardCount, selectPresetPortfolio, comparePresetReplacement, evaluatePresetPool } from '../src/lib/preset-portfolio.mjs';
import { generatePresetCandidates } from '../src/lib/preset-candidates.mjs';
import { createInventoryManager } from '../src/lib/inventory-manager.mjs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
import { replayGekisouFrames } from '../src/lib/scoring-rules/gekisou-frame-replay.mjs';
const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const chart = JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10003803.json', import.meta.url)));
chart.sourceReleaseId = rules.sourceReleaseId;
const draft = () => createTeamDraft({ selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty,
  slots: [1,2,3,4,5].map(i => ({ memberCardId: `member-card-${i}`, supportCardId: `support-card-${i}` })) });
const matrix = () => ({ candidates: ['balanced','a','b','redundant'].map(id => ({id})),
  songs: [{trackId:'a',weight:1},{trackId:'b',weight:1}],
  scores: [[80,100,10,79],[80,10,100,79]].map(r => r.map(expectedScore => ({expectedScore}))) });
test('portfolio maximizes per-song coverage and measures redundant slots', () => {
  const m = matrix(), two = selectPresetPortfolio(m, 2), all = selectPresetPortfolio(m, 4);
  assert.equal(two.expectedScore,90); assert.deepEqual(two.selectedIds,['balanced','a']);
  assert.equal(two.rows[0].candidateId,'a'); assert.equal(two.rows[1].candidateId,'balanced');
  assert.equal(all.expectedScore,100); assert.deepEqual(all.selectedIds,['a','b']);
  assert.equal(all.contributions.find(c=>c.candidateId==='redundant').additionalGain,0);
  assert.equal(all.contributions.find(c=>c.candidateId==='balanced').selected,false);
  m.songs[0].weight=9;
  assert.equal(selectPresetPortfolio(m,1).selectedIds[0],'a');
  assert.throws(()=>selectPresetPortfolio(m,0));
  m.scores[0][0].expectedScore=NaN; assert.throws(()=>selectPresetPortfolio(m,2),/矩阵/);
});
test('replacement retains both improvements and regressions, respects other presets', () => {
  const m=matrix(), single=comparePresetReplacement(m,['balanced'],'balanced','a');
  assert.equal(single.expectedDelta,-25); assert.equal(single.improvedSongs,1); assert.equal(single.worsenedSongs,1);
  assert.equal(comparePresetReplacement(m,['balanced','b'],'balanced','a').expectedDelta,10);
  m.scores[0][0].sections=[{index:1,missionType:3,totalScore:30}];
  m.scores[0][1].sections=[{index:1,missionType:3,totalScore:40}];
  assert.deepEqual(comparePresetReplacement(m,['balanced'],'balanced','a').rows[0].sectionDeltas,[{index:1,missionType:3,scoreDelta:10}]);
});
test('maximizing trainable growth never grants awakening or breakthrough', () => {
  const d=draft(); d.modifiers.growth={'member-card-1':{rank:2,awake:2,level:1,skillLevel:1,gekisouSkillLevel:2},'support-card-1':{rank:3,level:1}};
  const before=structuredClone(d), p=preparePresetDraft(rules,d);
  assert.deepEqual(d,before);
  assert.equal(p.modifiers.growth['member-card-1'].rank,2); assert.equal(p.modifiers.growth['member-card-1'].awake,2);
  assert.equal(p.modifiers.growth['member-card-1'].skillLevel,5); assert.ok(p.modifiers.growth['member-card-1'].level>1);
  assert.equal(p.modifiers.growth['support-card-1'].rank,3); assert.equal(p.modifiers.growth['support-card-1'].skillLevel,undefined);
  assert.equal(preparePresetDraft(rules,d,{maximizeTrainable:false}).modifiers.growth['member-card-1'].level,1);
});
test('4004 uses the two millisecond base on each side and continuous level 5 stays active', () => {
  const ranges=[{index:1,missionType:3,startMs:0,endMs:10000}];
  const effect={key:'window',active:true,missionType:3,probability:100,trigger:[{_conditionType:7020}],
    definition:{_skillEffectType:4004,_skillTriggerType:2,_effectValue:20000,_activationTimeSecond:0}};
  for(const offset of [-7,-6,6,7]) {
    const timeline={events:[100,9000].map(timeMs=>({timeMs,type:1,critical:false,weight:100,comboFactor:1}))};
    const replay=replayGekisouFrames(rules,timeline,ranges,[effect],{ranks:[1],timingOffsetMs:offset,frameRate:60},1);
    assert.deepEqual(replay.events.map(e=>e.judgement),Array(2).fill(Math.abs(offset)<=6?6:5));
  }
  effect.definition._effectValue=30000;
  for(const offset of [8,9]) {
    const replay=replayGekisouFrames(rules,{events:[{timeMs:100,type:1}]},ranges,[effect],{ranks:[1],timingOffsetMs:offset,frameRate:60},1);
    assert.equal(replay.events[0].judgement,offset===8?6:5);
  }
});
test('pool evaluates real ordinary charts, validates versions and rejects duplicate songs', async () => {
  const d=draft(), candidates=[{id:'one',name:'one',draft:d,sourceReleaseId:rules.sourceReleaseId}], songs=[{trackId:chart.trackId,chart}];
  const result=await evaluatePresetPool({rules,candidates,songs,mode:'ordinary'});
  assert.ok(result.portfolio.expectedScore>0); assert.equal(result.portfolio.rows[0].candidateId,'one');
  assert.deepEqual(d,draft()); assert.ok(result.inputHash);
  await assert.rejects(evaluatePresetPool({rules,candidates,songs:[...songs,...songs],mode:'ordinary'}),/重复/);
  await assert.rejects(evaluatePresetPool({rules,candidates:[{...candidates[0],sourceReleaseId:'bad'}],songs}),/版本/);
  await assert.rejects(evaluatePresetPool({rules,candidates,songs:[{...songs[0],chart:{...chart,sourceReleaseId:'bad'}}]}),/版本/);
});
test('window limit excludes two-window presets without hiding the reason', async () => {
  const d=draft(); d.slots[0].supportCardId='support-card-31'; d.slots[1].supportCardId='support-card-32';
  assert.equal(presetWindowCardCount(rules,preparePresetDraft(rules,d)),2);
  const candidates=[{id:'two',name:'two',draft:d,sourceReleaseId:rules.sourceReleaseId}];
  await assert.rejects(evaluatePresetPool({rules,candidates,songs:[{trackId:chart.trackId,chart}]}),/没有符合/);
});
test('owned seed generation preserves actual ranks and does not invent unowned cards', async () => {
  const manager=createInventoryManager(rules), d=draft();
  let inventory=manager.empty();
  for(const kind of ['member','support']) inventory=manager.merge(inventory,[1,2,3,4,5].map(i=>({id:`${kind}-card-${i}`,kind,patch:{}}))).inventory;
  const result=await generatePresetCandidates({rules,draft:d,inventory,songs:[{trackId:chart.trackId,difficulty:chart.difficulty}],mode:'ordinary'});
  assert.equal(result.candidates.length,1);
  for(const slot of result.candidates[0].draft.slots) for(const kind of ['member','support']) {
    const id=slot[`${kind}CardId`]; assert.ok(inventory[`${kind}CardIds`].includes(id));
    assert.equal(result.candidates[0].draft.modifiers.growth[id].rank,1);
  }
  assert.equal(inventory.growth['member-card-1'].level,1);
});
