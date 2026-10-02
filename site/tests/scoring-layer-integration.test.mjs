import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createTeamDraft} from '../src/lib/team-draft.mjs';
import {createFormalSongCalculator} from '../src/lib/scoring-rules/formal-song-score.mjs';
import {createGekisouSongCalculator} from '../src/lib/scoring-rules/gekisou-song-score.mjs';

const sourceRules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const chart=JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10003803.json',import.meta.url)));
for(const mode of ['ordinary','gekisou']) test(`${mode}: per-note event rounding precedes section awards and fixed scores`,()=>{
  const rules=structuredClone(sourceRules);
  // Deterministic team: identical ordinary skills, no support/random effects.
  for(const m of rules.tables.MemberCard){m._liveSkillID=1;m._gekisouSkillID=0;}
  for(const s of rules.tables.SupportCard){s._supportSkillId01=s._supportSkillId02=0;s._gekisouSupportSkillId01=s._gekisouSupportSkillId02=0;}
  const music=rules.tables.LiveMusic.find(m=>`music-${m._id}`===chart.trackId);
  music._gekisouMission1=music._gekisouMission2=music._gekisouMission3=1;
  rules.tables.Event=[{_id:999}];
  const draft=createTeamDraft({slots:[1,2,3,4,5].map(id=>({memberCardId:`member-card-${id}`,supportCardId:`support-card-${id}`})),selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty});
  const factory=mode==='ordinary'?createFormalSongCalculator:createGekisouSongCalculator;
  const before=factory(rules,chart).calculate(draft,{includeTrace:true});
  const eventFactor=Math.fround(1.00013),fixed=7;
  // Synthetic adapter exercises future bonus composition; no released event
  // is claimed to have these deliberately small boundary-sensitive bonuses.
  const adapter={sourceReleaseId:rules.sourceReleaseId,supports:e=>e._id===999,
    resolve:()=>({effects:[{phase:'note_score'},{phase:'fixed_score'}]}),
    handlers:{note_score:p=>({...p,eventBonusFactor:eventFactor}),fixed_score:s=>s+fixed}};
  draft.modifiers.event={id:999,sourceReleaseId:rules.sourceReleaseId};
  const after=factory(rules,chart,{eventAdapters:[adapter]}).calculate(draft,{includeTrace:true});
  const notes=mode==='ordinary'?before.bestOrderNotes:before.bestSample.notes;
  const adjusted=notes.map(n=>Math.floor(Math.fround(n.score*eventFactor)));
  const noteTotal=adjusted.reduce((s,n)=>s+n,0);
  assert.notEqual(noteTotal,Math.floor(Math.fround(notes.reduce((s,n)=>s+n.score,0)*eventFactor)));
  assert.equal(after.power,before.power);
  if(mode==='ordinary'){
    assert.equal(after.expectedScore,noteTotal+fixed);
    assert.equal(after.eventFixedScoreGain,fixed);
  }else{
    let awards=0;
    for(const section of before.bestSample.sections){
      const subtotal=adjusted.reduce((s,n,i)=>s+(notes[i].scoreSectionIndex===section.index?n:0),0);
      // ConfirmSoloGekisouRanking / NetworkGekisouRankingUpdater use an
      // integer 64-bit product divided by 100, not float32 multiplication.
      const award=Number(BigInt(subtotal)*BigInt(section.rankingPercent)/100n);
      const actual=after.bestSample.sections[section.index-1];
      assert.equal(actual.noteScore,subtotal);assert.equal(actual.rankingBonus,award);
      awards+=award;
    }
    assert.equal(after.expectedScore,noteTotal+awards+fixed);
    assert.equal(after.bestSample.eventFixedScore,fixed);
  }
});
