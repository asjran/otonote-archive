import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
import { createGekisouLuckMachine, createScoringRandom, luckNoteCategory, weightedScoringDraw } from '../src/lib/scoring-rules/gekisou-luck.mjs';
import { createGekisouSongCalculator, normalizeGekisouScenario } from '../src/lib/scoring-rules/gekisou-song-score.mjs';
import { gekisouRankingBonus } from '../src/lib/scoring-rules/gekisou-rules.mjs';
import { optimizeInventory } from '../src/lib/inventory-optimizer.mjs';
import { formalJudgementType } from '../src/lib/scoring-rules/formal-judgement.mjs';
import { reconstructFormalChart } from '../src/lib/scoring-rules/formal-chart.mjs';
import { scoringScenarioSearch, readScoringScenarioSearch } from '../src/lib/scoring-rules/scenario-search.mjs';
import { parseTeamDraftSearch } from '../src/lib/team-draft.mjs';
const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const chart = JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10003803.json', import.meta.url)));
const draft = () => createTeamDraft({ slots: [1,2,3,4,5].map(i => ({ memberCardId: `member-card-${i}`, supportCardId: `support-card-${i}` })), selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty });

test('native encrypted lookup gives progressively lower RUSH continuation probability', () => {
  assert.deepEqual(rules.native.luckChanceTypesByRushCombo, [0,4,3,2]);
  assert.deepEqual(rules.native.luckPointsByResult, [0,5,10,10]);
  const m = createGekisouLuckMachine(rules, { random: () => 0.99 });
  m.addGauge(140); assert.equal(m.consume(), 3);
  assert.equal(m.state.gaugeMax, 70); assert.equal(m.state.bonusPoints, 10);
  m.addGauge(70); assert.equal(m.consume(), 3); assert.equal(m.state.rushCombo, 2);
  for (let i=0;i<20;i++) { m.addGauge(70); m.consume(); }
  assert.equal(m.scoreFactorPercent(), 110); assert.ok(m.state.bonusPoints > 100);
  m.addBonusPoints(1000); assert.equal(m.scoreFactorPercent(), 110);
});
test('LUCK ranking points do not multiply notes and leaving RUSH disables its single handle', () => {
  const draws=[.99,0,0];
  const m=createGekisouLuckMachine(rules,{random:()=>draws.shift()??0});
  m.addBonusPoints(1000);assert.equal(m.scoreFactorPercent(),100);
  m.addGauge(140);assert.equal(m.consume(),3);assert.equal(m.scoreFactorPercent(),110);
  // First RUSH continuation distribution is SUPER or RUSH, never NO LUCK.
  m.addGauge(70);assert.equal(m.consume(),2);assert.equal(m.scoreFactorPercent(),100);
  assert.equal(m.state.bonusPoints,1020);
});
test('prefetched result survives later guarantees; all guarantees consumed by a draw', () => {
  const m = createGekisouLuckMachine(rules, { random: () => 0 });
  m.addGauge(140); assert.equal(m.consume(), 0); // also prefetches NO LUCKY
  m.addMinimum(1, 1); m.addMinimum(2, 1);
  m.addGauge(140); assert.equal(m.consume(), 0); // previous next is retained
  assert.equal(m.state.next, 2); // draws with maximum guarantee
  m.addGauge(140); assert.equal(m.consume(), 2);
  assert.equal(m.state.next, 0); // both guarantees consumed together
});
test('native gauge boundaries: add uses >=; changing maximum uses >', () => {
  const m = createGekisouLuckMachine(rules, { random: () => 0.99 });
  m.addGauge(210); assert.equal(m.state.pendingLots, 1); assert.equal(m.state.gauge, 70);
  m.consume(); assert.equal(m.state.gaugeMax, 70); assert.equal(m.state.pendingLots, 0);
  assert.equal(m.state.gauge, 70); // no automatic >= conversion on max change
  m.addGauge(0); assert.equal(m.state.pendingLots, 1); assert.equal(m.state.gauge, 0);
});
test('AP base points are not deterministic and hold/guide categories differ', () => {
  const low = createGekisouLuckMachine(rules, { random: () => 0 });
  const high = createGekisouLuckMachine(rules, { random: () => 0.99 });
  assert.equal(low.addNote(1), 9); assert.equal(high.addNote(1), 7);
  assert.equal(low.addNote(21, 5, 1), 4); assert.equal(low.addNote(101), 0);
  assert.equal(luckNoteCategory(120), 1); assert.equal(luckNoteCategory(42), 0);
  assert.equal(low.addNote(1, 2), 0);
  assert.throws(() => weightedScoringDraw([], () => 0, '_id'), /Empty/);
});
test('seeded randomness and scenario validation are reproducible', () => {
  const a = createScoringRandom(0), b = createScoringRandom(0);
  for(let i=0;i<100;i++) assert.equal(a(),b());
  assert.deepEqual(normalizeGekisouScenario().ranks,[1,1,1]);
  for(const s of [{ ranks:[1,1] },{ ranks:[1,1,6] },{ timingOffsetMs:51 },{ batches:0 },{ seed:-1 },{frameRate:24}]) assert.throws(()=>normalizeGekisouScenario(s));
});
test('recommendation links preserve the draft and every Gekisou scenario input', () => {
  const d=draft(), scenario={ranks:[3,1,2],timingOffsetMs:25,batches:4,seed:123,frameRate:120,
    opponents:Array.from({length:4},()=>({sections:Array.from({length:3},()=>({combo:100,luckPoints:200,just:80,noteScore:500000,perfectCount:100}))}))};
  const query=scoringScenarioSearch(d,'gekisou',scenario);
  assert.deepEqual(parseTeamDraftSearch(query).draft,d);
  assert.deepEqual(readScoringScenarioSearch(query),{mode:'gekisou',scenario:normalizeGekisouScenario(scenario)});
  assert.deepEqual(readScoringScenarioSearch(scoringScenarioSearch(d,'ordinary')),{mode:'ordinary',scenario:null});
  assert.throws(()=>readScoringScenarioSearch('?scoreMode=other'));
  assert.throws(()=>readScoringScenarioSearch('?scoreMode=gekisou&gekisouScenario=not-json'));
});
test('a JUST count skill can win the section and improve score without increasing power', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard)m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard)s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  const baseline=createGekisouSongCalculator(r,chart).calculate(draft());
  const opponent={sections:baseline.sections.map(s=>({combo:0,luckPoints:0,just:Math.floor(s.just)+1,noteScore:0,perfectCount:0}))};
  const scenario={opponents:[opponent]};
  const before=createGekisouSongCalculator(r,chart,{scenario}).calculate(draft());
  r.tables.MemberCard.find(m=>m._id===1)._gekisouSkillID=16;
  const after=createGekisouSongCalculator(r,chart,{scenario}).calculate(draft());
  assert.equal(after.power,before.power);
  assert.equal(after.sections[2].noteScore,before.sections[2].noteScore);
  assert.equal(before.sections[2].rank,2);
  assert.equal(after.sections[2].rank,1);
  assert.deepEqual(after.sections[2].rankProbabilities,[1,0,0,0,0]);
  assert.ok(after.expectedScore>before.expectedScore);
  assert.equal(after.scenario.rankingModel,'opponent_section_results');
});
test('RUSH ranking-point skills change the rank metric but not note score at a fixed rank', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard)m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard)s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  const before=createGekisouSongCalculator(r,chart).calculate(draft());
  r.tables.MemberCard.find(m=>m._id===1)._gekisouSkillID=14;
  const after=createGekisouSongCalculator(r,chart).calculate(draft());
  assert.equal(after.power,before.power);
  assert.equal(after.sections[1].noteScore,before.sections[1].noteScore);
  assert.equal(after.expectedScore,before.expectedScore);
  assert.ok(after.sections[1].luckPoints>before.sections[1].luckPoints);
});
test('JUST cumulative score updates at the skill frame and cannot boost earlier notes in that frame', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard)m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard)s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  r.tables.SupportCard.find(s=>s._id===1)._gekisouSupportSkillId01=1;
  const c={...chart,bpmEvents:[{tick:0,bpm:125}],skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:2.5}],gekisouRanges:undefined,
    notes:[0,1000,2010,2011,2040].map((tick,i)=>({id:`phase${i}`,type:'tap',tick}))};
  const a=createGekisouSongCalculator(r,c).calculate(draft(),{includeTrace:true});
  const supportCommands=a.bestSample.factorCommands.filter(c=>c.source?.startsWith('support:0:'));
  assert.equal(supportCommands[0].timeMs,2016);
  const notes=a.bestSample.notes.filter(n=>n.sectionIndex===3);
  assert.equal(notes[0].scoreUpFactor,notes[1].scoreUpFactor);
  assert.ok(notes[2].scoreUpFactor>notes[1].scoreUpFactor);
});
test('COMBO threshold activates from the previous G frame and backdates its count bonus', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard)m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard)s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  r.tables.MemberCard.find(m=>m._id===1)._gekisouSkillID=12;
  for(const condition of r.tables.SkillCondition.filter(c=>c._conditionType===7005))condition._conditionValues=[2];
  const c={...chart,bpmEvents:[{tick:0,bpm:125}],skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:2.5}],gekisouRanges:undefined,
    notes:[100,110,110,160,1000,2000].map((tick,i)=>({id:`threshold${i}`,type:'tap',tick}))};
  const a=createGekisouSongCalculator(r,c).calculate(draft(),{includeTrace:true});
  const start=a.bestSample.skillTransitions.find(t=>t.source.startsWith('member:0:'));
  assert.equal(start.timeMs,a.bestSample.notes[1].timeMs);
  assert.ok(start.frame> a.bestSample.notes[1].inputFrame);
  // +4 begins on the LAST judgement of the previous frame. The earlier
  // simultaneous note shares its timestamp but must not receive the bonus.
  assert.equal(a.sections[0].combo,12);
});
test('conversion charges wait for the next input frame and only the successful source is consumed', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard)m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard)s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  for(const id of [1,2])r.tables.SupportCard.find(s=>s._id===id)._gekisouSupportSkillId01=81;
  for(const condition of r.tables.SkillCondition.filter(c=>c._conditionType===1030))condition._conditionValues=[1];
  const c={...chart,bpmEvents:[{tick:0,bpm:125}],skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:2.5}],gekisouRanges:undefined,
    notes:[0,1000,2000,2001,2030,2031].map((tick,i)=>({id:`t${i}`,type:'tap',tick}))};
  const result=createGekisouSongCalculator(r,c,{scenario:{timingOffsetMs:30}}).calculate(draft(),{includeTrace:true});
  const notes=result.bestSample.notes.filter(n=>n.sectionIndex===3);
  assert.equal(notes[0].inputFrame,notes[1].inputFrame);
  assert.deepEqual(notes.map(n=>n.judgement),[5,5,6,6]);
});
test('native judgement mapping excludes tap slide ends from JUST, retains critical input', () => {
  const windows = new Set(rules.tables.LiveJudgementTiming.filter(r=>r._assistLevel===0&&r._noteSimulateJudgement===6).map(r=>r._noteJudgementType));
  for(const type of [1,20,40,41,42,101,102]) assert.ok(windows.has(formalJudgementType(type)),String(type));
  for(const type of [21,22,60,61,62,63,104,105,120]) assert.ok(!windows.has(formalJudgementType(type)),String(type));
  assert.equal(formalJudgementType(1,true),2);assert.equal(formalJudgementType(20,true),15);
  const c={bpmEvents:[{tick:0,bpm:120}],notes:[{id:'critical',type:'tap',tick:480,critical:true}]};
  assert.equal(reconstructFormalChart(c)[0].critical,true);
});
test('three arithmetic fixtures use integer percent and separate truncation', () => {
  const scores=[635973,741911,1372309], bonuses=[2353100,2745070,5077543];
  scores.forEach((sectionScore,i)=>assert.equal(gekisouRankingBonus(rules,{missions:[1,2,3],sectionIndex:i+1,rank:1,sectionScore}).additionalScore,bonuses[i]));
  assert.equal(bonuses.reduce((a,b)=>a+b),10175713);
  // Arithmetic only: no old screenshot or recorded run is used as an oracle.
  assert.equal(bonuses[0]+bonuses[1],5098170);
  const sectionScore=16777217;
  assert.equal(gekisouRankingBonus(rules,{missions:[1,2,3],sectionIndex:1,rank:1,sectionScore}).additionalScore,
    Number(BigInt(sectionScore)*370n/100n));
});
test('AP zero offset differs from AP outside JUST window and support conversion contributes', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard) m._gekisouSkillID=0;
  for(const s of r.tables.SupportCard) s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  const a=createGekisouSongCalculator(r,chart).calculate(draft());
  const b=createGekisouSongCalculator(r,chart,{scenario:{timingOffsetMs:30}}).calculate(draft());
  assert.ok(a.sections[2].rawJust>0); assert.equal(b.sections[2].rawJust,0);
  assert.ok(a.expectedScore>b.expectedScore);
  r.tables.SupportCard.find(s=>s._id===1)._gekisouSupportSkillId01=81;
  const c=createGekisouSongCalculator(r,chart,{scenario:{timingOffsetMs:30}}).calculate(draft());
  assert.ok(c.sections[2].rawJust>0); assert.ok(c.expectedScore>b.expectedScore);
});
test('trace is additive, scenario ranks change only awards, and uncertainty remains explicit', () => {
  const calc=createGekisouSongCalculator(rules,chart), a=calc.calculate(draft(),{includeTrace:true});
  const b=createGekisouSongCalculator(rules,chart,{scenario:{ranks:[2,2,2]}}).calculate(draft());
  const sample=a.bestSample;
  assert.equal(a.scenario.settlementModel,'multiplayer_first_eligible_frame');
  for(const section of sample.sections) {
    assert.equal(section.noteScore,section.scoreQuery.endScore-section.scoreQuery.startScore);
    assert.equal(section.finalNoteScore,sample.notes.filter(n=>n.scoreSectionIndex===section.index).reduce((sum,n)=>sum+n.score,0));
  }
  assert.equal(sample.score,sample.notes.reduce((s,n)=>s+n.score,0)+sample.sections.reduce((s,n)=>s+n.rankingBonus,0));
  for(let i=0;i<3;i++) assert.equal(a.sections[i].noteScore,b.sections[i].noteScore);
  assert.ok(a.expectedScore>b.expectedScore); assert.equal(a.standardError,null); assert.equal(a.sampleCount,120);
  const replicated=createGekisouSongCalculator(rules,chart,{scenario:{batches:2}}).calculate(draft());
  assert.ok(replicated.standardError>0);assert.equal(replicated.sampleCount,240);
  assert.equal(replicated.scoreDistribution.kind,'seed_samples');assert.equal(replicated.scoreDistribution.complete,false);
  assert.equal(replicated.scoreDistribution.count,240);assert.equal(replicated.scoreDistribution.minimum,replicated.minimumScore);
  assert.ok(Math.abs(replicated.scoreDistribution.mean-replicated.expectedScore)<1e-8);
  assert.equal(a.verificationStatus,'source_informed_frame_replay');
  assert.deepEqual(calc.calculate(draft()),calc.calculate(draft()));
  assert.ok(calc.upperBound(a.power,50)>a.maximumScore);
});
test('LUCK entry gauge tickets drain on empty frames before the first note', () => {
  const r=structuredClone(rules);
  for(const m of r.tables.MemberCard) m._gekisouSkillID=20;
  for(const c of r.tables.SkillCondition.filter(c=>c._conditionType===4011)) c._conditionValues=[100];
  const c={...chart,bpmEvents:[{tick:0,bpm:125}],skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:3}],gekisouRanges:undefined,
    notes:[0,250,1250,1400,2000,2250].map((tick,i)=>({id:`n${i}`,type:'tap',tick}))};
  const a=createGekisouSongCalculator(r,c).calculate(draft(),{includeTrace:true});
  const beforeNote=a.bestSample.luckEvents.filter(e=>e.origin==='empty_frame'&&e.timeMs<1250);
  assert.equal(beforeNote.length,5);assert.equal(beforeNote[0].timeMs,1016);
  assert.ok(beforeNote.every((e,i)=>!i||e.timeMs>beforeNote[i-1].timeMs));
  const fast=createGekisouSongCalculator(r,c,{scenario:{frameRate:120}}).calculate(draft(),{includeTrace:true});
  assert.ok(fast.bestSample.luckEvents[1].timeMs<a.bestSample.luckEvents[1].timeMs);
});
test('score search can prefer a weaker support when its JUST skill raises total score', async () => {
  // Controlled tradeoff fixture: two legal choices, same four locked pairs.
  // The test asserts the complete-song objective, not a rarity/power proxy.
  const r=structuredClone(rules),d=draft();
  for(const s of r.tables.SupportCard) s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;
  const weaker=r.tables.SupportCard.find(s=>s._id===6);
  weaker._performancePowerMax=weaker._technicPowerMax=weaker._visualPowerMax=1;
  weaker._gekisouSupportSkillId01=1;weaker._supportSkillId01=0;
  d.modifiers.growth={};
  for(let i=1;i<=6;i++)for(const kind of ['member','support'])d.modifiers.growth[`${kind}-card-${i}`]={level:1,rank:1,awake:1};
  const args={rules:r,draft:d,chart,scope:'owned',inventory:{memberCardIds:[1,2,3,4,5],supportCardIds:[1,2,3,4,5,6]},
    constraints:{leaderId:3,lockedPairs:[1,2,3,4].map(i=>({memberCardId:i,supportCardId:i}))},
    mode:'gekisou',topN:1,maxEvaluations:0,yieldControl:async()=>{}};
  const power=await optimizeInventory({...args,objective:'formation_power'});
  const score=await optimizeInventory({...args,objective:'expected_song_score'});
  assert.equal(score.optimality,'best_within_simulation');
  assert.ok(score.results[0].power<power.results[0].power);
  assert.ok(score.results[0].draft.slots.some(s=>s.supportCardId==='support-card-6'));
  const c=score.results[0].comparison;
  assert.ok(c.scoreDelta>0);assert.ok(c.powerDelta<0);assert.ok(c.sectionDeltas[2].totalScore>0);
  assert.equal(Object.values(c.powerSourceDeltas).reduce((a,b)=>a+b),c.powerDelta);
});
test('all released member and support effects resolve across all levels under AP', () => {
  const d=draft();
  // Small authored chart keeps this an effect-family coverage check; it does
  // not claim equivalence to a recorded native execution.
  const c={...chart,bpmEvents:[{tick:0,bpm:125}],skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:2.5}],
    gekisouRanges:undefined,notes:[0,250,1000,1250,2000,2250].map((tick,i)=>({id:`t${i}`,type:'tap',tick}))};
  for (const kind of ['Member','Support']) for (const card of rules.tables[`${kind}Card`]) for(const level of [1,5]) {
    const value=structuredClone(d),key=`${kind.toLowerCase()}-card-${card._id}`;
    // Replace same character for member variants, avoiding illegal duplication.
    const index=kind==='Member'?value.slots.findIndex(s=>rules.tables.MemberCard.find(m=>`member-card-${m._id}`===s.memberCardId)._characterID===card._characterID):-1;
    value.slots[index<0?0:index][`${kind.toLowerCase()}CardId`]=key;
    if(kind==='Support') {const duplicate=value.slots.findIndex((s,i)=>i!==0&&s.supportCardId===key);if(duplicate>=0)value.slots[duplicate].supportCardId='support-card-1';}
    value.modifiers.growth={[key]:kind==='Member'?{gekisouSkillLevel:level}:{rank:level}};
    assert.ok(Number.isFinite(createGekisouSongCalculator(rules,c).calculate(value).expectedScore),key);
  }
});
test('optimizer uses Gekisou score, preserves the scenario in checkpoints, and reports incomplete search',async()=>{
  const opts={rules,chart,draft:draft(),objective:'expected_song_score',mode:'gekisou',maxEvaluations:1,topN:1,yieldControl:async()=>{}};
  const result=await optimizeInventory(opts);
  assert.equal(result.mode,'gekisou');assert.equal(result.optimality,'incomplete');assert.equal(result.results.length,1);
  const best=result.results[0];assert.equal(best.value,createGekisouSongCalculator(rules,chart).calculate(best.draft).expectedScore);
  assert.equal(best.sections.length,3);
  await assert.rejects(()=>optimizeInventory({...opts,checkpoint:result.checkpoint,gekisouScenario:{ranks:[2,2,2]}}),/input_mismatch/);
});

test('cancelling a placement sweep retains the entire matching for checkpoint resume', async () => {
  const controller = new AbortController();
  const c = {...chart, bpmEvents:[{tick:0,bpm:125}], skillTimings:[0,1,2,3,4],
    feverRanges:[{start:0,end:.5},{start:1,end:1.5},{start:2,end:2.5}], gekisouRanges:undefined,
    notes:[100,1100,2100].map((tick,i)=>({id:`cancel${i}`,type:'tap',tick}))};
  const opts = {rules, chart:c, draft:draft(), mode:'gekisou', objective:'expected_song_score',
    constraints:{leaderId:3,lockedPairs:[1,2,3,4,5].map(id=>({memberCardId:id,supportCardId:id}))},
    topN:1, maxEvaluations:0, yieldControl:async()=>{}};
  const interrupted = await optimizeInventory({...opts, signal:controller.signal,
    onProgress:p=>{if(p.phase==='placements')controller.abort();}});
  assert.equal(interrupted.status,'cancelled');
  assert.equal(interrupted.evaluated,0);
  assert.equal(interrupted.checkpoint.frontier.length,1);
  const resumed = await optimizeInventory({...opts,checkpoint:interrupted.checkpoint});
  assert.equal(resumed.status,'completed');
  assert.equal(resumed.evaluated,1);
  assert.equal(resumed.results[0].value,createGekisouSongCalculator(rules,c).calculate(resumed.results[0].draft).expectedScore);
});
