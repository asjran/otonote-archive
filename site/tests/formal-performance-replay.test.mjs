import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createTeamDraft } from '../src/lib/team-draft.mjs';
import { createPerformanceTemplate, validatePerformance, createPerformanceSongCalculator } from '../src/lib/scoring-rules/formal-performance-replay.mjs';
import { createFormalSongCalculator } from '../src/lib/scoring-rules/formal-song-score.mjs';
import { createLifeReplay, applyLifeCommand, createComboReplay } from '../src/lib/scoring-rules/formal-performance-state.mjs';

const read = name => JSON.parse(readFileSync(new URL(name, import.meta.url)));
const rules = read('../src/data/formal-scoring-rules.json');
const chart = read('../public/data/music-charts/music-chart-10000103.json');
const native = read('./fixtures/formal-performance-state-native.json');
const draft = () => createTeamDraft({ slots: [1,2,3,4,5].map(id => ({ memberCardId: `member-card-${id}`, supportCardId: `support-card-${id}` })),
  selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty, modifiers: { tgwCardRank: 2 } });

function fixture(times) {
  const r = structuredClone(rules), c = { ...chart, bpmEvents: [{ tick: 0, bpm: 125 }], skillTimings: [1,10,20,30,40], feverRanges: [],
    notes: times.map((tick,i) => ({ id: `tap-${i}`, type: 'tap', tick })) };
  r.tables.LiveMusicScore.find(row => row._id === 10000103)._musicScoreLevel = 5;
  for (const support of r.tables.SupportCard) support._supportSkillId01 = support._supportSkillId02 = 0;
  for (const effect of r.tables.LiveSkillEffect) effect._effectValue = 0;
  const d = draft();
  return { r, c, d, p: createPerformanceTemplate(r,c) };
}

test('life command arithmetic, late-prefix cache and combo states reproduce intact client methods', () => {
  assert.equal(native.clientSha256, rules.nativeSha256);
  for (const row of native.commands) assert.deepEqual(applyLifeCommand(row.state,row.command,1000),row.expected);
  for (const history of native.histories) {
    const life = createLifeReplay(1000, (256 - 50) * 40);
    for (const op of history) if (op.add) life.add(op.add); else assert.equal(life.at(op.timeMs),op.expected);
  }
  for (const row of native.combos) {
    const combo = createComboReplay([]);
    row.judgements.forEach((judgement,i) => {
      combo.add(row.times[i],judgement);
      const { timeMs: _time, judgement: _judgement, ...state } = combo.state;
      assert.deepEqual(state,row.expected[i]);
    });
    for (const query of row.queries) assert.equal(combo.at(query.timeMs).combo,query.expected);
  }
});

test('explicit AP fixed order matches existing full sweep at every supported ideal frame rate', () => {
  for (const frameRate of [30,60,120]) {
    const d = draft(), ap = createFormalSongCalculator(rules,chart,{frameRate}).calculate(d);
    const p = createPerformanceTemplate(rules,chart,{frameRate});p.skillOrder = ap.bestOrder;
    const result = createPerformanceSongCalculator(rules,chart,{performance:p}).calculate(d,{includeTrace:true});
    assert.equal(result.expectedScore,ap.maximumScore);
    assert.equal(result.baseScore,ap.baseScore);
    assert.equal(result.performance.maxCombo,768);
    assert.equal(result.performance.fullCombo,true);
    assert.equal(result.bestOrderNotes.reduce((sum,note)=>sum+note.score,0),result.expectedScore);
    assert.equal(result.orderCount,1);
    assert.equal(result.scorePrecision,'explicit_performance');
  }
});

test('distinct member skills and support types reproduce the selected AP order', () => {
  const characters=new Set(), skillIds=new Set();
  const members=rules.tables.MemberCard.filter(row=>{
    if(characters.has(row._characterID)||skillIds.has(row._liveSkillID))return false;
    characters.add(row._characterID);skillIds.add(row._liveSkillID);return true;
  }).slice(0,5);
  const supports=[...new Map(rules.tables.SupportCard.map(row=>[row._supportSkillId01,row])).values()].slice(0,5);
  const d=draft();d.slots=members.map((row,i)=>({memberCardId:`member-card-${row._id}`,supportCardId:`support-card-${supports[i]._id}`}));
  const ap=createFormalSongCalculator(rules,chart).calculate(d);
  const p=createPerformanceTemplate(rules,chart);p.skillOrder=ap.bestOrder;
  const result=createPerformanceSongCalculator(rules,chart,{performance:p}).calculate(d);
  assert.equal(result.expectedScore,ap.maximumScore);
});

test('explicit clocks reproduce the same timestamps and require enough tail frames', () => {
  const {r,c,d,p}=fixture([1000,1100,6001]);
  const ordinary=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d);
  p.frames=Array.from({length:2800},(_,i)=>({timeMs:Math.floor(i*1000/60),deltaSeconds:1/60}));
  const explicit=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d);
  assert.equal(explicit.timingModel.clock,'explicit_frames');
  assert.equal(explicit.expectedScore,ordinary.expectedScore);
  p.frames=p.frames.slice(0,2450);
  assert.throws(()=>createPerformanceSongCalculator(r,c,{performance:p}).calculate(d),/未覆盖/);
});

test('input contract requires exact chart coverage, explicit frame order and current model hash', () => {
  const p = createPerformanceTemplate(rules,chart);
  assert.equal(validatePerformance(rules,{...chart,sourceReleaseId:rules.sourceReleaseId},p).valid,true);
  const change = mutate => { const value=structuredClone(p); mutate(value); return value; };
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.judgements.pop())),/全部/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.judgements[1].scoreIndex=0)),/重复/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.judgements[0].timeMs++)),/时间/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.judgements[0].judgement=7)),/1 至 6/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.skillOrder=[0,0,1,2,3])),/排列/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.chartHash='other')),/不匹配/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.initialLife=100)),/不支持/);
  assert.throws(()=>validatePerformance(rules,chart,change(v=>v.frames=[{timeMs:0,deltaSeconds:0}])),/未覆盖/);
});

test('GOOD continues combo, BAD resets it, and simultaneous notes share the prior combo', () => {
  const {r,c,d,p}=fixture([100,200,200,300,400,500]);
  r.tables.LiveComboScoreBonus=[{_comboBonusType:0,_requiredComboCount:2,_bonusFactor:0.5}];
  [5,3,4,2,5,6].forEach((j,i)=>p.judgements[i].judgement=j);
  // The rule-table-only combo change does not change projected chart identity.
  const result=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d,{includeTrace:true});
  assert.deepEqual(result.bestOrderNotes.map(n=>n.combo),[0,1,1,3,0,1]);
  assert.deepEqual(result.bestOrderNotes.map(n=>n.comboFactor),[1,1,1,1.5,1,1]);
  assert.equal(result.performance.life,950);
  assert.equal(result.performance.maxCombo,3);
  assert.equal(result.performance.fullCombo,false);
  assert.ok(result.bestOrderNotes[5].score>result.bestOrderNotes[4].score);
});

test('zero life is preserved; recovery cannot revive and score penalty uses life captured per input', () => {
  const {r,c,d,p}=fixture([...Array.from({length:10},(_,i)=>100+i*20),1001,2000]);
  p.judgements.slice(0,10).forEach(n=>n.judgement=1);
  r.tables.SupportCard.find(row=>row._id===1)._supportSkillId01=51;
  const result=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d,{includeTrace:true});
  assert.equal(result.performance.life,0);
  assert.equal(result.performance.lowestLife,0);
  assert.equal(result.performance.totalDamage,1000);
  assert.equal(result.performance.recoveryAmount,200); // Matching band branch.
  assert.equal(result.bestOrderNotes.at(-1).lifeAtInput,0);
  const healthy=structuredClone(p);healthy.judgements.forEach(n=>n.judgement=5);
  const ap=createPerformanceSongCalculator(r,c,{performance:healthy}).calculate(d,{includeTrace:true});
  assert.equal(ap.performance.life,1200);
  assert.ok(result.bestOrderNotes.at(-1).score<ap.bestOrderNotes.at(-1).score/2);
});

test('recovery phase precedes life-threshold skills and target bonuses follow converted judgement', () => {
  const {r,c,d,p}=fixture([100,200,300,400,1000,1100,1200]);
  p.judgements.slice(0,4).forEach(n=>n.judgement=1); // 600 HP before skill.
  r.tables.SupportCard.find(row=>row._id===1)._supportSkillId01=51;
  for (const row of r.tables.SupportSkillEffect.filter(row=>row._supportSkillID===51)) row._effectValue=100; // +100 => 700
  const effect=r.tables.LiveSkillEffect.find(row=>row._liveSkillID===1&&row._level===1);
  effect._skillConditionGroup=14; effect._skillEffectType=2004;effect._skillTargetIDs=[41,46];effect._effectValue=10000;
  p.judgements[5].judgement=4;
  const result=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d,{includeTrace:true});
  assert.equal(result.skillTrace.find(row=>row.type===2004).currentLife,700);
  assert.equal(result.skillTrace.find(row=>row.type===2004).active,true);
  assert.equal(result.bestOrderNotes[4].lifeAtInput,600);
  assert.equal(result.bestOrderNotes[5].scoreUpFactor,1);
  assert.equal(result.bestOrderNotes[6].scoreUpFactor,2);
});

test('conversion starts after its activation-frame input, consumes only successful conversions and expires after input', () => {
  const {r,c,d,p}=fixture([1000,1010,1100,1200,1300,1400,6001]);
  r.tables.SupportCard.find(row=>row._id===1)._supportSkillId01=31;
  p.judgements.forEach(note=>note.judgement=4);p.judgements[2].judgement=5;
  const result=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d,{includeTrace:true});
  assert.deepEqual(result.bestOrderNotes.map(n=>n.judgement),[4,5,5,5,5,4,4]);
  assert.equal(result.performance.convertedCount,3);
  assert.deepEqual(result.stateTrace.find(row=>row.timeMs>=1300).converters,[]);
  assert.ok(result.skillScoreGain>0); // Conversion contributes to whole-skill gain.
  // One remaining conversion applies on the frame that unregisters by time.
  const limited=structuredClone(p);limited.judgements.forEach(note=>note.judgement=5);limited.judgements.at(-1).judgement=4;
  const edge=createPerformanceSongCalculator(r,c,{performance:limited}).calculate(d,{includeTrace:true});
  assert.equal(edge.bestOrderNotes.at(-1).judgement,5);
});

test('delayed and early inputs preserve arrival order, historical combo and frozen life', () => {
  const {r,c,d,p}=fixture([100,200,300]);
  p.judgements[0].judgement=1;p.judgements[0].inputFrame=30;
  p.judgements[1].inputFrame=0;p.judgements[2].inputFrame=40;
  const result=createPerformanceSongCalculator(r,c,{performance:p}).calculate(d,{includeTrace:true});
  assert.equal(result.bestOrderNotes[1].lifeAtInput,1000);
  assert.equal(result.bestOrderNotes[2].lifeAtInput,900);
  assert.deepEqual(result.bestOrderNotes.map(n=>n.combo),[0,0,1]);
  assert.equal(result.performance.maxCombo,2);
});

test('unsupported conversion targets fail explicitly instead of using the ordinary path silently', () => {
  const {r,c,d,p}=fixture([1100]);
  r.tables.SupportCard.find(row=>row._id===1)._supportSkillId01=31;
  r.tables.SupportSkillEffect.find(row=>row._supportSkillID===31&&row._level===1)._effectValue=6;
  assert.throws(()=>createPerformanceSongCalculator(r,c,{performance:p}).calculate(d),/Unsupported judgement conversion/);
});
