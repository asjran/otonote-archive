import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { optimizePractical, practicalNeighbours, legalPracticalDraft, scoreCloseness } from '../src/lib/practical-optimizer.mjs';
import { skillOrdersFor } from '../src/lib/scoring-rules/skill-order-sampling.mjs';
import { createCandidateEvaluator } from '../src/lib/formation-candidate-evaluator.mjs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
import { resolveSearchInput } from '../src/lib/scoring-rules/formation-input.mjs';
const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const chart = JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10003803.json', import.meta.url)));
chart.sourceReleaseId = rules.sourceReleaseId;
const draft = () => createTeamDraft({ selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty,
  slots: [1,2,3,4,5].map(i => ({ memberCardId: `member-card-${i}`, supportCardId: `support-card-${i}` })) });
const yieldControl = async () => {};

test('screening orders are unique and balanced; full scoring remains 120', () => {
  const orders = skillOrdersFor('screen'); assert.equal(orders.length,10);
  assert.equal(new Set(orders.map(o=>o.join())).size,10);
  for (let position=0;position<5;position++) for(let slot=0;slot<5;slot++) assert.equal(orders.filter(o=>o[position]===slot).length,2);
  assert.equal(skillOrdersFor().length,120); assert.throws(()=>skillOrdersFor('unknown'));
  orders[0][0]=99; assert.notEqual(skillOrdersFor('screen')[0][0],99);
});
test('ordinary practical recommendation finishes fixed stages and only returns full scores', async () => {
  const d=draft(), original=structuredClone(d);
  const result=await optimizePractical({rules,chart,draft:d,yieldControl});
  assert.equal(result.status,'completed'); assert.equal(result.optimality,'practical_checked'); assert.equal(result.checkpoint,null);
  assert.ok(result.practical.finalists<=6); assert.ok(result.results.length>0);
  assert.ok(result.results[0].value >= result.baseline);
  assert.equal(result.closeness,null);
  assert.ok(result.practical.stages.every(s=>s.total!==null&&s.completed===s.total));
  assert.deepEqual(d,original);
  const evaluator=createCandidateEvaluator({rules,chart,objective:'expected_song_score'});
  for(const r of result.results){assert.equal(r.scorePrecision,'full');assert.equal(r.orderCount,120);assert.equal(r.value,evaluator.score(r.draft).value);}
  const repeat=await optimizePractical({rules,chart,draft:d,yieldControl});
  assert.deepEqual(repeat.results.map(r=>[r.id,r.value]),result.results.map(r=>[r.id,r.value]));
});
test('fixed neighbour pass retains required cards, locked pair and leader', async () => {
  const d=draft(), constraints={leaderId:'member-card-3',requiredMemberIds:['member-card-1'],requiredSupportIds:['support-card-1'],lockedPairs:[d.slots[0]]};
  const result=await optimizePractical({rules,chart,draft:d,constraints,yieldControl});
  for(const r of result.results){assert.equal(r.draft.slots[2].memberCardId,'member-card-3');assert.ok(r.draft.slots.some(s=>s.memberCardId==='member-card-1'&&s.supportCardId==='support-card-1'));}
  const input=resolveSearchInput(rules,d,{constraints});
  const neighbours=[...practicalNeighbours(d,input.inventory)];assert.equal(neighbours.length,54);
  const characters=id=>rules.tables.MemberCard.find(c=>`member-card-${c._id}`===id)._characterID;
  const illegal=structuredClone(d);illegal.slots[0].memberCardId='member-card-2';assert.equal(legalPracticalDraft(illegal,input,characters),false);
});
test('owned rank and awakening are not promoted by practical search', async () => {
  const d=draft(); d.modifiers.growth={};
  for(const slot of d.slots){d.modifiers.growth[slot.memberCardId]={level:1,rank:1,awake:1,skillLevel:1,gekisouSkillLevel:1};d.modifiers.growth[slot.supportCardId]={level:1,rank:1};}
  const inventory={memberCardIds:d.slots.map(s=>s.memberCardId),supportCardIds:d.slots.map(s=>s.supportCardId)};
  const r=await optimizePractical({rules,chart,draft:d,scope:'owned',inventory,yieldControl});
  for(const candidate of r.results)assert.deepEqual(candidate.draft.modifiers.growth,d.modifiers.growth);
});
test('cancellation before final scoring is incomplete and exposes no screening scores', async () => {
  const controller=new AbortController();
  const r=await optimizePractical({rules,chart,draft:draft(),signal:controller.signal,yieldControl,
    onProgress:p=>{if(p.stage==='快速模拟候选')controller.abort();}});
  assert.equal(r.status,'cancelled'); assert.equal(r.optimality,'incomplete');assert.deepEqual(r.results,[]);
  assert.equal(r.practical.stages.at(-1).total,null);
});
test('LUCK overlap is marked close and unknown errors are not interpreted as zero', () => {
  assert.equal(scoreCloseness({value:100,standardError:2},{value:99,standardError:2}).kind,'close');
  assert.equal(scoreCloseness({value:100,standardError:null},{value:90,standardError:2}).kind,'unknown');
  assert.equal(scoreCloseness({value:100,standardError:NaN},{value:90,standardError:2}).kind,'unknown');
  assert.equal(scoreCloseness({value:100,standardError:1},{value:90,standardError:1}).kind,'separated');
  assert.equal(scoreCloseness({value:100},{value:99},'maximum_song_score'),null);
});
test('Gekisou finals use 120 orders and at least two LUCK batches', async () => {
  const d=draft();d.slots[0].supportCardId='support-card-31';
  const r=await optimizePractical({rules,chart,draft:d,mode:'gekisou',gekisouScenario:{batches:1,timingOffsetMs:5},yieldControl});
  assert.equal(r.status,'completed');assert.ok(r.practical.directions.some(d=>d.id==='window'&&d.status==='generated'));
  assert.ok(r.results[0].value>=r.baseline);
  for(const c of r.results){assert.equal(c.orderCount,120);assert.equal(c.scenario.batches,2);assert.equal(c.scorePrecision,'full');assert.ok(Number.isFinite(c.standardError));}
});
test('required JUST window card stays present and is not described as a no-window seed', async () => {
  const d=draft();d.slots[0].supportCardId='support-card-31';
  const r=await optimizePractical({rules,chart,draft:d,mode:'gekisou',objective:'formation_power',
    constraints:{requiredSupportIds:['support-card-31']},yieldControl});
  assert.equal(r.status,'completed');
  assert.match(r.practical.directions.find(d=>d.id==='mission-3').label,/保留必选判卡/);
  for(const c of r.results)assert.ok(c.draft.slots.some(s=>s.supportCardId==='support-card-31'));
});
