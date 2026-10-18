import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {optimizeChallenge,createChallengeSearchSession} from '../src/lib/challenge-optimizer.mjs';
import {createTeamDraft} from '../src/lib/team-draft.mjs';
import {createEventEfficiency} from '../../packages/scoring/scoring-rules/event-efficiency.mjs';
import {createFormalSongCalculator} from '../../packages/scoring/scoring-rules/formal-song-score.mjs';
import {createFormalSkillResolver} from '../../packages/scoring/scoring-rules/formal-skills.mjs';
import {createOrdinaryScoreBound} from '../../packages/scoring/scoring-rules/ordinary-score-bound.mjs';
import {maximumPairing,partitionPairing} from '../../packages/scoring/scoring-rules/maximum-pairing.mjs';
import {compilePairingModels,draftFromPairing} from '../src/lib/inventory-optimizer.mjs';
import {resolveSearchInput} from '../../packages/scoring/scoring-rules/formation-input.mjs';
import {createBonusConstrainedScoreEnvelopeBound} from '../../packages/scoring/scoring-rules/bonus-constrained-score-bound.mjs';
import {calculateFormalNoteCore} from '../../packages/scoring/scoring-rules/formal-note-core.mjs';

export function fixture(seed=1) {
  const rules=JSON.parse(readFileSync(new URL('../../packages/scoring/data/formal-scoring-rules.json',import.meta.url)));
  const chart={id:'music-chart-10003803',trackId:'music-100038',difficulty:'expert',sourceReleaseId:rules.sourceReleaseId,
    bpmEvents:[{tick:0,bpm:125}],skillTimings:[1,2,3,4,5],feverRanges:[],
    notes:Array.from({length:16},(_,i)=>({id:String(i),type:'tap',tick:i*449+1}))};
  rules.tables.Event=[{_id:1,_eventType:1}];
  rules.tables.ChallengeMusic=[{_eventId:1,_liveMusicId:100038,_musicType:2,_gekisouMission1:0,_gekisouMission2:0,_gekisouMission3:0}];
  rules.tables.EventEffect=[];
  const template=rules.tables.LiveSkillEffect.find(e=>e._liveSkillID===1&&e._level===1);
  for(let i=1;i<=6;i++){
    const id=900000+i;
    rules.tables.MemberCard.find(m=>m._id===i)._liveSkillID=id;
    rules.tables.LiveSkillEffect.push({...template,_id:id,_liveSkillID:id,_effectValue:(seed*1711+i*2333)%18000,
      _activationTimeSecond:.021+i*.717,_skillConditionGroup:0});
  }
  const draft=createTeamDraft({selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,
    slots:[1,2,3,4,5].map(i=>({memberCardId:`member-card-${i}`,supportCardId:`support-card-${i}`}))});
  const inventory={memberCardIds:[1,2,3,4,5,6].map(i=>`member-card-${i}`),supportCardIds:draft.slots.map(s=>s.supportCardId),growth:{}};
  for(const id of inventory.memberCardIds)inventory.growth[id]={level:1,rank:1,awake:1,skillLevel:1,gekisouSkillLevel:1};
  for(const id of inventory.supportCardIds)inventory.growth[id]={level:1,rank:1};
  if(seed===2){
    rules.tables.MemberCard.find(m=>m._id===6)._characterID=1;
    for(const [i,id] of inventory.memberCardIds.entries())Object.assign(inventory.growth[id],{level:3+i*2,rank:1+i%3,awake:1+i%2});
    for(const [i,id] of inventory.supportCardIds.entries())Object.assign(inventory.growth[id],{level:2+i,rank:1+i%3});
    rules.tables.EventEffect=[{_id:1,_eventId:1,_resourceTypeConstraint:2,_eventBonusType:2,_memberCardId:6,
      ...Object.fromEntries([1,2,3,4,5].map(rank=>[`_rank${rank}EffectValue`,rank*1000]))}];
  }
  draft.modifiers.growth=structuredClone(inventory.growth);
  return {rules,chart,draft,inventory,eventId:1,yieldControl:async()=>{}};
}
function* permutations(a){if(!a.length){yield [];return;}for(let i=0;i<a.length;i++)for(const tail of permutations(a.filter((_,j)=>j!==i)))yield [a[i],...tail];}

test('best-only challenge certificate does not certify reference alternatives',async()=>{
  const input=fixture();input.inventory.memberCardIds.pop();
  const result=await optimizeChallenge({...input,maxEvaluations:0});
  assert.equal(result.certifiedSearch.proofTarget,'best');
  assert.equal(result.certifiedSearch.bestProven,true);
  assert.equal(result.certifiedSearch.certifiedCount,1);
  assert.equal(result.certifiedSearch.topNComplete,false);
  assert.equal(result.certifiedSearch.optimalityGap,0);
});

test('chunked pause and continuation retain every unresolved branch and immutable job inputs',async()=>{
  const input=fixture(2),original=structuredClone(input.draft);let paused=false;
  const session=createChallengeSearchSession({...input,maxEvaluations:1,shouldPause:()=>paused});
  const full=await optimizeChallenge({...input,maxEvaluations:0});
  let result=await session.run();const initialExpanded=result.certifiedSearch.expanded;
  // A UI may edit its live draft; a retained session owns its original input.
  input.draft.modifiers.tgwCardRank=21;
  result.results[0].value=Number.MAX_SAFE_INTEGER;
  paused=true;
  const stopped=await session.run();
  assert.equal(stopped.certifiedSearch.expanded,initialExpanded);
  assert.ok(stopped.results[0].value<Number.MAX_SAFE_INTEGER,'returned snapshots cannot change the incumbent');
  result=stopped;
  paused=false;
  for(let i=0;i<2000&&!result.certifiedSearch.bestProven;i++)result=await session.run();
  assert.equal(result.certifiedSearch.bestProven,true);
  assert.equal(result.results[0].value,full.results[0].value);
  assert.deepEqual(result.results[0].draft.modifiers,full.results[0].draft.modifiers);
  assert.equal(original.modifiers.tgwCardRank,undefined);
});

test('power-linear coefficients cover native int32 powers and fractional score factors',()=>{
  const {rules,chart}=fixture(),song=createFormalSongCalculator(rules,chart),coefficients=song.powerLinearUpperBound();
  const setting=key=>Number(rules.tables.LiveSettings.find(r=>r._key===key)._value);
  const judgement=rules.tables.LiveJudgementParameter.find(r=>r._noteSimulateJudgement===5)._scorePercent;
  for(const power of [1,3,127,65535,1048577,16777215,16777217,0x7fffffff])for(const factor of [.00001,.49999,1,1.000001,2.17]){
    for(const [i,event] of song.timeline.events.entries()){
      if(coefficients[i]*power*factor>=0x7ffff000)continue; // Native scoring rejects overflowing note scores.
      const score=calculateFormalNoteCore({totalPower:power,scoreAdjustmentFactor:setting('note_score_adjustment_factor'),
        musicScoreLevelFactor:song.timeline.difficultyFactor,noteFactorPercent:event.weight,judgementFactorPercent:judgement,
        comboBonusFactor:event.comboFactor,scoreUpFactor:factor,luckScoreFactorPercent:100,
        convertedNoteCount:song.timeline.convertedNoteCount,eventBonusFactor:1,lifeOnusFactor:1,assistModeNoteScoreFactor:1,currentLife:1000}).score;
      assert.ok(coefficients[i]*power*factor>=score,`${power} ${factor} ${i}`);
    }
  }
});

test('joint power/skill bounds dominate independent exhaustive teams in every tested partition',async()=>{
  for(const seed of [1,2]){
    const f=fixture(seed),model=createEventEfficiency({tables:f.rules.tables,sourceReleaseId:f.rules.sourceReleaseId,eventId:1});
    f.draft.modifiers.event={id:1,sourceReleaseId:f.rules.sourceReleaseId};
    const eventAdapters=[model.challengeAdapter(f.rules)],input=resolveSearchInput(f.rules,f.draft,{scope:'owned',inventory:f.inventory});
    const song=createFormalSongCalculator(f.rules,f.chart,{eventAdapters}),resolver=createFormalSkillResolver(f.rules),pairs=new Map();
    for(const m of input.inventory.memberCardIds)for(const s of input.inventory.supportCardIds)pairs.set(`${m}|${s}`,resolver({slots:[{memberCardId:m,supportCardId:s}],modifiers:input.draft.modifiers})[0]);
    const models=await compilePairingModels(f.rules,input,{eventAdapters}),maxima={maximumScore:0,expectedScore:0};
    for(const model of models){
      const root={leader:model.leader,required:[],forbidden:[]},solution=maximumPairing({edges:model.edges,requiredMembers:[model.leader]});
      const rows=[];
      for(const omitted of input.inventory.memberCardIds.filter(m=>m!==model.leader)){
        const members=input.inventory.memberCardIds.filter(m=>m!==omitted);
        if(new Set(members.map(m=>f.rules.tables.MemberCard.find(r=>`member-card-${r._id}`===m)._characterID)).size!==5)continue;
        for(const order of permutations(input.inventory.supportCardIds)){
          const edges=members.map((m,i)=>model.edges.find(e=>e.member===m&&e.support===order[i]));
          const d=draftFromPairing(input,model.leader,edges),scores=song.calculate(d),keys=edges.map(e=>e.key);
          rows.push({keys,scores});for(const metric of Object.keys(maxima))maxima[metric]=Math.max(maxima[metric],scores[metric]);
        }
      }
      for(const metric of Object.keys(maxima)){
        const bound=createOrdinaryScoreBound({song,pairSkills:pairs,legacyFactor:10,input,metric,jointPowerBound:true,bonusConstraintBound:true});
        for(const state of [root,...partitionPairing(root,solution)]){
          const solved=maximumPairing({edges:model.edges,required:state.required,forbidden:state.forbidden,requiredMembers:[model.leader]});
          if(!solved)continue;
          const exact=Math.max(...rows.filter(r=>state.required.every(k=>r.keys.includes(k))&&state.forbidden.every(k=>!r.keys.includes(k))).map(r=>r.scores[metric]));
          assert.ok(bound(state,model,solved,()=>draftFromPairing(input,model.leader,solved.edges))>=exact,`${seed} ${model.leader} ${metric}`);
          const conditionalExact=Math.max(0,...rows.filter(r=>state.required.every(k=>r.keys.includes(k))&&state.forbidden.every(k=>!r.keys.includes(k))&&r.keys.some(k=>k.startsWith('member-card-6|'))).map(r=>r.scores[metric]));
          const conditionalUpper=bound.withMinimumBonus(state,model,solved,()=>draftFromPairing(input,model.leader,solved.edges),e=>e.member==='member-card-6'?100:0,100);
          assert.ok(conditionalUpper>=conditionalExact,`conditional native score: ${seed} ${model.leader} ${metric}`);
          const normalized=bound.normalizedPowerEnvelope(exact+1);
          assert.ok(normalized);assert.equal(bound.normalizedPowerEnvelope(0),null);
          const ratioBound=createBonusConstrainedScoreEnvelopeBound({...normalized,integerScore:false});
          const available=model.edges.filter(e=>!state.forbidden.includes(e.key));
          const normalizedUpper=ratioBound(available,solved.edges.filter(e=>state.required.includes(e.key)),model.leader,solved,0,e=>e.member==='member-card-6'?100:0,100);
          assert.ok(normalizedUpper>=conditionalExact/(exact+1),`normalized native score: ${seed} ${model.leader} ${metric}`);
          for(const cutoff of [exact-1,exact,Infinity]){
            const upper=bound.withCutoff(state,model,solved,()=>draftFromPairing(input,model.leader,solved.edges),cutoff);
            assert.ok(upper>=exact,`cutoff ${cutoff}: ${seed} ${model.leader} ${metric}`);
          }
        }
      }
    }
    for(const [objective,metric] of [['maximum_song_score','maximumScore'],['expected_song_score','expectedScore']]){
      const r=await optimizeChallenge({...f,objective,maxEvaluations:0});
      assert.equal(r.results[0].value,maxima[metric]);assert.equal(r.certifiedSearch.bestProven,true);
    }
  }
});


test('safe joint cutoff avoids native per-note bounds and remains valid with all pairs locked',async()=>{
  const f=fixture(2),event=createEventEfficiency({tables:f.rules.tables,sourceReleaseId:f.rules.sourceReleaseId,eventId:1});
  f.draft.modifiers.event={id:1,sourceReleaseId:f.rules.sourceReleaseId};
  const eventAdapters=[event.challengeAdapter(f.rules)],input=resolveSearchInput(f.rules,f.draft,{scope:'owned',inventory:f.inventory});
  const original=createFormalSongCalculator(f.rules,f.chart,{eventAdapters});
  let nativeBounds=0;
  const song={...original,upperBound(...args){nativeBounds++;return original.upperBound(...args);}};
  const resolver=createFormalSkillResolver(f.rules),pairSkills=new Map();
  for(const m of input.inventory.memberCardIds)for(const s of input.inventory.supportCardIds)
    pairSkills.set(`${m}|${s}`,resolver({slots:[{memberCardId:m,supportCardId:s}],modifiers:input.draft.modifiers})[0]);
  const [model]=await compilePairingModels(f.rules,input,{eventAdapters});
  const solution=maximumPairing({edges:model.edges,requiredMembers:[model.leader]});
  const draft=()=>draftFromPairing(input,model.leader,solution.edges);
  for(const metric of ['maximumScore','expectedScore','minimumScore']){
    const bound=createOrdinaryScoreBound({song,pairSkills,legacyFactor:10,input,metric,jointPowerBound:true,bonusConstraintBound:true});
    const state={leader:model.leader,required:solution.edges.map(e=>e.key),forbidden:[]};
    const before=nativeBounds,early=bound.withCutoff(state,model,solution,draft,Infinity);
    assert.ok(Number.isFinite(early));
    assert.equal(nativeBounds,before,'joint proof does not need native per-note bounds');
    const full=bound(state,model,solution,draft);
    assert.ok(nativeBounds>before);
    assert.ok(early>=full);
    assert.ok(full>=song.calculate(draft())[metric]);
    assert.equal(bound.withCutoff(state,model,solution,draft,-Infinity),full);
  }
});
