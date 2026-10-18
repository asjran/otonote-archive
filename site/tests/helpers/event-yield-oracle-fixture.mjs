import {readFileSync} from 'node:fs';
import {createTeamDraft} from '../../src/lib/team-draft.mjs';

export function eventYieldOracleFixture(){
 const rules=JSON.parse(readFileSync(new URL('../../../packages/scoring/data/formal-scoring-rules.json',import.meta.url)));
 const chart={id:'music-chart-10003803',trackId:'music-100038',difficulty:'expert',sourceReleaseId:rules.sourceReleaseId,
  bpmEvents:[{tick:0,bpm:125}],skillTimings:[1,2,3,4,5],feverRanges:[],
  notes:Array.from({length:12},(_,i)=>({id:`oracle-${i}`,type:'tap',tick:i*397+1}))};
 const music=rules.tables.LiveMusic.find(r=>`music-${r._id}`===chart.trackId);music._liveScoreRankGroup=999;
 Object.assign(rules.tables,{
  Event:[{_id:1,_eventType:1,_eventItemId:43,_liveEventPointGroup:1,_liveEventRewardGroup:1,_challengeLiveEventPointGroup:1,_challengeLiveEventRewardGroup:1}],
  EventEffect:[
   {_resourceTypeConstraint:2,_memberCardId:1,_eventBonusType:0,value:4300},
   {_resourceTypeConstraint:3,_supportCardId:6,_eventBonusType:1,value:7200},
   {_resourceTypeConstraint:2,_memberCardId:3,_eventBonusType:2,value:1000},
  ].map((row,i)=>({...row,_id:i+1,_eventId:1,...Object.fromEntries([1,2,3,4,5].map(n=>[`_rank${n}EffectValue`,row.value+n*137]))})),
  ChallengeMusic:[{_eventId:1,_liveMusicId:music._id,_musicType:music._musicType,_gekisouMission1:0,_gekisouMission2:0,_gekisouMission3:0}],
  LiveScoreRank:[2,3,4,5,6,7].map((rank,i)=>({_group:999,_liveScoreRank:rank,_requiredScore:i*31000})),
  LiveMusicBoostBonus:[{_consumedLiveBoostCount:1,_eventPointRate:5,_liveMusicRewardRate:5}],
  ChallengeMusicBoostBonus:[200,400].map(cost=>({_consumedChallengePointCount:cost,_eventPointRate:cost/200,_liveMusicRewardRate:cost/200})),
  LiveChallengePoint:[2,3,4,5,6,7].map(rank=>({_scoreRank:rank,_value:rank})),
 });
 for(const prefix of ['Live','ChallengeLive']){
  // A non-monotone reward row catches treating score grade as an assumed
  // monotone currency bound. Grade remains explicitly the first grade goal.
  rules.tables[prefix+'EventPoint']=[2,3,4,5,6,7].map((rank,i)=>({_group:1,_scoreRank:rank,_value:[100,150,140,220,250,270][i]}));
  rules.tables[prefix+'EventReward']=[2,3,4,5,6,7].map((rank,i)=>({_eventGroup:1,_scoreRank:rank,_resourceType:1,_resourceId:43,_resourceCount:[140,180,170,260,280,310][i],_probability:10000}));
 }
 const draft=createTeamDraft({selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,
  slots:[1,2,3,4,5].map(i=>({memberCardId:`member-card-${i}`,supportCardId:`support-card-${i}`}))});
 const inventory={memberCardIds:draft.slots.map(s=>s.memberCardId),supportCardIds:[1,2,3,4,5,6].map(i=>`support-card-${i}`),growth:{}};
 for(const id of inventory.memberCardIds)inventory.growth[id]={level:1,rank:1,awake:1,skillLevel:1,gekisouSkillLevel:1};
 for(const id of inventory.supportCardIds)inventory.growth[id]={level:1,rank:1};
 draft.modifiers.growth=structuredClone(inventory.growth);
 const candidate={id:chart.id,trackId:chart.trackId,difficulty:chart.difficulty,seconds:100,title:'oracle'};
 const challengeRows=[{song:{id:'a',seconds:101},reward:{scoreRank:4},bonuses:{rewardBP:3300,eventPointBP:1700}},
  {song:{id:'b',seconds:99},reward:{scoreRank:3},bonuses:{rewardBP:5300,eventPointBP:4100}}];
 return {rules,chart,draft,inventory,candidate,challengeRows,scope:'owned',eventId:1,budget:11,startingCP:399,maxEvaluations:0};
}
