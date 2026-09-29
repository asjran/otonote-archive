import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { maximumPairing, partitionPairing } from '../src/lib/scoring-rules/maximum-pairing.mjs';
import { optimizeInventory, gekisouPlacements } from '../src/lib/inventory-optimizer.mjs';
import { optimizeProductionPairing } from '../src/lib/production-optimizer.mjs';
import { resolveSearchInput } from '../src/lib/scoring-rules/formation-input.mjs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const draft = () => createTeamDraft({ slots: [1,2,3,4,5].map(i => ({ memberCardId: `member-card-${i}`, supportCardId: `support-card-${i}` })), selectedSongId: 'music-100001' });
const yieldControl = async () => {};
test('Gekisou placement search covers all 24 pair orders while retaining the leader', () => {
  const d = draft(), placements = gekisouPlacements(d);
  assert.equal(placements.length, 24);
  assert.equal(new Set(placements.map(p => p.slots.map(s => s.memberCardId).join(','))).size, 24);
  for (const p of placements) {
    assert.deepEqual(p.slots[2], d.slots[2]);
    assert.deepEqual(p.slots.map(s => JSON.stringify(s)).sort(), d.slots.map(s => JSON.stringify(s)).sort());
  }
});
function brute(edges, n, constraints = {}) {
  const found = [];
  function visit(chosen, start) {
    if (chosen.length === n) {
      if (constraints.required?.some(k => !chosen.some(e => e.key === k)) || constraints.requiredMembers?.some(m => !chosen.some(e => e.member === m)) || constraints.requiredSupports?.some(s => !chosen.some(e => e.support === s))) return;
      found.push({ edges: chosen, weight: chosen.reduce((a,e) => a + e.weight,0) }); return;
    }
    for(let i = start; i < edges.length; i++) {
      const e = edges[i];
      if(constraints.forbidden?.includes(e.key) || chosen.some(c => c.member===e.member || c.character===e.character || c.support===e.support)) continue;
      visit([...chosen,e], i+1);
    }
  }
  visit([],0); return found.sort((a,b) => b.weight-a.weight);
}
test('residual matching and Lawler partition agree with independent exhaustive enumeration', () => {
  for (let seed = 1; seed < 25; seed++) {
    const edges = Array.from({length:4}, (_,m) => Array.from({length:3},(_,s) => ({key:`${m}|${s}`,member:m,support:s,character:Math.floor(m/2),weight:(m*31+s*19+seed*m*s*11)%47-15}))).flat();
    const c = { requiredMembers: [seed%4], requiredSupports: [seed%3], forbidden: [`${seed%4}|${(seed+1)%3}`], required: [] };
    const all = brute(edges,2,c), best = maximumPairing({edges,count:2,...c});
    assert.equal(best?.weight, all[0]?.weight);
    if (!best) continue;
    const children = partitionPairing(c,best).flatMap(child => brute(edges,2,child));
    const signature = r => r.edges.map(e=>e.key).sort().join(',');
    assert.equal(new Set(children.map(signature)).size, children.length);
    assert.deepEqual(children.map(signature).sort(), all.filter(r => signature(r)!==signature(best)).map(signature).sort());
  }
});
test('selected search matches exhaustive 600 formation candidates', async () => {
  const expected = await optimizeProductionPairing({rules,draft:draft(),topN:10,yieldControl});
  const actual = await optimizeInventory({rules,draft:draft(),topN:10,yieldControl,maxEvaluations:0});
  assert.equal(actual.optimality,'proven_within_model');
  assert.deepEqual(actual.results.map(r=>r.value),expected.results.map(r=>r.value));
});
test('budgeted search resumes, and changed inputs reject its checkpoint', async () => {
  const first = await optimizeInventory({rules,draft:draft(),topN:10,maxEvaluations:1,yieldControl});
  assert.equal(first.status,'budget_exhausted'); assert.ok(first.optimalityGap>=0);
  const second = await optimizeInventory({rules,draft:draft(),topN:10,maxEvaluations:0,checkpoint:first.checkpoint,yieldControl});
  const full = await optimizeInventory({rules,draft:draft(),topN:10,maxEvaluations:0,yieldControl});
  assert.deepEqual(second.results,full.results);
  await assert.rejects(optimizeInventory({rules,draft:draft(),topN:9,checkpoint:first.checkpoint,yieldControl}), /input_mismatch/);
});
test('owned pool requires explicit growth and full inventory can select unselected cards', async () => {
  const d = draft(); const inventory={memberCardIds:[1,2,3,4,5,6],supportCardIds:[1,2,3,4,5,6]};
  assert.throws(()=>resolveSearchInput(rules,d,{scope:'owned',inventory}),/养成/);
  d.modifiers.growth={};
  for(let i=1;i<=6;i++) for(const kind of ['member','support']) d.modifiers.growth[`${kind}-card-${i}`]={level:1,rank:1,awake:1};
  const result=await optimizeInventory({rules,draft:d,scope:'owned',inventory,constraints:{requiredMemberIds:[6],lockedPairs:[{memberCardId:6,supportCardId:6}]},topN:1,maxEvaluations:0,yieldControl});
  assert.equal(result.status,'completed');
  assert.ok(result.results[0].draft.slots.some(s=>s.memberCardId==='member-card-6'&&s.supportCardId==='support-card-6'));
});
test('song objectives use full scoring, and upper bounds cover the exhaustive optimum', async () => {
  const chart=JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10000103.json', import.meta.url)));
  const d=draft();d.selectedDifficulty=chart.difficulty;
  const exhaustive=await optimizeProductionPairing({rules,draft:d,chart,objective:'expected_song_score',topN:1,yieldControl});
  const partial=await optimizeInventory({rules,draft:d,chart,objective:'expected_song_score',maxEvaluations:1,topN:1,yieldControl});
  assert.ok(partial.upperBound>=exhaustive.results[0].value);
  const full=await optimizeInventory({rules,draft:d,chart,objective:'expected_song_score',maxEvaluations:0,topN:1,yieldControl,checkpoint:partial.checkpoint});
  assert.equal(full.results[0].value,exhaustive.results[0].value);
  assert.equal(full.optimality,'proven_within_model');
});
test('theoretical full inventory produces legal reproducible maximum-power formation', async () => {
  const result=await optimizeInventory({rules,draft:draft(),scope:'theoretical',topN:1,maxEvaluations:0,yieldControl});
  assert.equal(result.status,'completed');assert.equal(result.optimalityGap,0);
  assert.ok(result.results[0].power>result.baseline);
  assert.equal(new Set(result.results[0].draft.slots.map(s=>rules.tables.MemberCard.find(r=>`member-card-${r._id}`===s.memberCardId)._characterID)).size,5);
});
test('same-character variants are excluded; infeasible mandatory pairs never claim an optimum',async()=>{
  const duplicate=rules.tables.MemberCard.find(r=>r._characterID===rules.tables.MemberCard[0]._characterID&&r._id!==1);
  const d=draft();d.slots[1].memberCardId=`member-card-${duplicate._id}`;
  assert.throws(()=>resolveSearchInput(rules,d),/不同角色/);
  const result=await optimizeInventory({rules,draft:draft(),constraints:{lockedPairs:[{memberCardId:1,supportCardId:1},{memberCardId:2,supportCardId:1}]},yieldControl});
  assert.equal(result.status,'no_feasible_formation');assert.equal(result.optimality,'infeasible');assert.equal(result.results.length,0);
});
test('pause during search returns a resumable incomplete result',async()=>{
  const controller=new AbortController();
  const result=await optimizeInventory({rules,draft:draft(),signal:controller.signal,yieldControl,onProgress:p=>{if(p.phase==='search')controller.abort();}});
  assert.equal(result.status,'cancelled');assert.equal(result.optimality,'incomplete');assert.ok(result.checkpoint);
});
