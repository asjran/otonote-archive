import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { gekisouMissionPattern, gekisouRankingBonus, gekisouComboFactor, resolveGekisouSkills, inspectGekisouScenario } from '../src/lib/scoring-rules/gekisou-rules.mjs';
import { calculateSongPool } from '../src/lib/song-pool.mjs';
import { resolveEventContext } from '../src/lib/scoring-rules/event-rules.mjs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
import { createFormationCalculator } from '../src/lib/scoring-rules/formation-power.mjs';
const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const chart=JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10000103.json',import.meta.url)));
const draft=()=>createTeamDraft({slots:[1,2,3,4,5].map(i=>({memberCardId:`member-card-${i}`,supportCardId:`support-card-${i}`})),selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty});
test('Gekisou mission pattern and ranking rewards are separate from base note score',()=>{
  assert.equal(gekisouMissionPattern([1,1,1]),1);assert.equal(gekisouMissionPattern([3,1,2]),2);assert.equal(gekisouMissionPattern([2,2,3]),3);assert.equal(gekisouMissionPattern([0,1,2]),0);
  for(const [missions,percent] of [[[1,1,1],250],[[1,2,3],370],[[1,1,3],333]]) {
    const r=gekisouRankingBonus(rules,{missions,sectionIndex:1,rank:1,sectionScore:101});assert.equal(r.percent,percent);assert.equal(r.additionalScore,Math.floor(101*percent/100));
  }
  assert.throws(()=>gekisouRankingBonus(rules,{missions:[1,1,1],sectionIndex:1,rank:6,sectionScore:1}));
  assert.equal(gekisouComboFactor(rules,0),1);assert.equal(gekisouComboFactor(rules,100000),Math.fround(1.3));
});
test('Gekisou skills use their own level and support rank; current cards resolve all condition data',()=>{
  const d=draft();d.modifiers.growth={'member-card-1':{skillLevel:5,gekisouSkillLevel:2},'support-card-1':{rank:3}};
  const s=resolveGekisouSkills(rules,d);assert.equal(s.find(x=>x.kind==='member'&&x.slotIndex===0).level,2);
  assert.equal(s.find(x=>x.kind==='support'&&x.slotIndex===0).level,3);
  for(const member of rules.tables.MemberCard){const v=draft();v.slots[0].memberCardId=`member-card-${member._id}`;resolveGekisouSkills(rules,v);}
  for(const support of rules.tables.SupportCard){const v=draft();v.slots[0].supportCardId=`support-card-${support._id}`;resolveGekisouSkills(rules,v);}
});
test('incomplete Gekisou state machine cannot produce an apparently complete score',()=>{
  const r=inspectGekisouScenario(rules,draft(),chart);assert.equal(r.score,null);assert.equal(r.optimizerEligible,false);assert.equal(r.sections.length,3);assert.ok(r.blockers.length>0);
});
test('song pool keeps one team, applies song-specific bonuses, and uses explicit weights',()=>{
  const songs=[{trackId:'music-100001',weight:2},{trackId:'music-100026',weight:1}];
  const result=calculateSongPool({rules,draft:draft(),songs});
  const calculator=createFormationCalculator(rules),expected=songs.map(s=>calculator.calculate({...draft(),selectedSongId:s.trackId}).total.total);
  assert.ok(Math.abs(result.expectedPower-(expected[0]*2/3+expected[1]/3))<1e-8);assert.equal(result.minimumPower,Math.min(...expected));
  assert.throws(()=>calculateSongPool({rules,draft:draft(),songs:[songs[0],songs[0]]}),/重复/);
  assert.throws(()=>calculateSongPool({rules,draft:draft(),songs:[{...songs[0],weight:0}]}),/正数/);
});
test('unknown or cross-release events fail closed and phase destinations stay separate',()=>{
  assert.equal(resolveEventContext(rules,null).status,'no_event');
  const context={id:1,sourceReleaseId:rules.sourceReleaseId};assert.throws(()=>resolveEventContext(rules,context),/不在/);
  assert.throws(()=>resolveEventContext(rules,{...context,sourceReleaseId:'other'}),/release_mismatch/);
  const r=structuredClone(rules);r.tables.Event=[{_id:1}];assert.throws(()=>resolveEventContext(r,context),/unsupported_event/);
  const adapter={sourceReleaseId:rules.sourceReleaseId,supports:()=>true,resolve:()=>({effects:[{phase:'event_points',value:200}]})};
  assert.deepEqual(resolveEventContext(r,context,[adapter]).effects,[{phase:'event_points',value:200}]);
  assert.throws(()=>createFormationCalculator(r).calculate({...draft(),modifiers:{event:context}}),/unsupported_event/);
});
test('event phase dispatch does not apply points or reward effects to note score', async()=>{
  const {createEventPipeline}=await import('../src/lib/scoring-rules/event-rules.mjs');
  const r=structuredClone(rules);r.tables.Event=[{_id:1}];
  const context={id:1,sourceReleaseId:r.sourceReleaseId};
  const adapter={sourceReleaseId:r.sourceReleaseId,supports:()=>true,resolve:()=>({effects:[{phase:'event_points',value:2}]}),handlers:{event_points:(value,effects)=>value*effects[0].value}};
  const pipeline=createEventPipeline(r,context,[adapter]);
  assert.equal(pipeline.apply('note_score',123),123);assert.equal(pipeline.apply('event_points',123),246);
  assert.throws(()=>createEventPipeline(r,context,[{...adapter,handlers:{}}]),/Missing event phase/);
  assert.throws(()=>resolveEventContext(r,42),/Invalid event/);
});
test('future audited event adapter reaches power and note phases without conflating fixed score with skill gain',async()=>{
  const {createFormalSongCalculator}=await import('../src/lib/scoring-rules/formal-song-score.mjs');
  const r=structuredClone(rules);r.tables.Event=[{_id:1}];
  const d=draft(),normal=createFormalSongCalculator(r,chart).calculate(d);
  d.modifiers.event={id:1,sourceReleaseId:r.sourceReleaseId};
  const adapter={sourceReleaseId:r.sourceReleaseId,supports:()=>true,resolve:()=>({effects:[{phase:'fixed_score',value:123}]}),handlers:{fixed_score:score=>score+123}};
  const calculator=createFormalSongCalculator(r,chart,{eventAdapters:[adapter]});
  const result=calculator.calculate(d,{includeTrace:true});
  assert.equal(result.expectedScore,normal.expectedScore+123);assert.equal(result.skillScoreGain,normal.skillScoreGain);assert.equal(result.eventFixedScoreGain,123);assert.equal(result.bestOrderFixedScore,123);
  assert.throws(()=>calculator.upperBound(1000,1),/audited upper bound/);
  const powerAdapter={...adapter,resolve:()=>({effects:[{phase:'member_power'}]}),handlers:{member_power:values=>values.map(v=>v+100)}};
  const a=createFormationCalculator(r,{eventAdapters:[powerAdapter]}).calculate(d);
  const b=createFormationCalculator(r).calculate(draft());
  assert.equal(a.breakdown.member.total-b.breakdown.member.total,1500);
});
