import {createFormalSongCalculator} from './scoring-rules/formal-song-score.mjs';
import {createEventEfficiency} from './scoring-rules/event-efficiency.mjs';
import {serializeTeamDraftSearch} from './team-draft.mjs';
import {scoreGradeProbabilities} from './scoring-rules/score-distribution.mjs';

export const AP_BASES=['expectedScore','minimumScore','maximumScore'];
// Older rule artifacts omit grade tables; catalog score rewards carry the same
// per-song lines. This only supplements thresholds, never the score arithmetic.
export function withAPScoreThresholds(rules,tracks){
 if(rules.tables.LiveScoreRank?.length)return rules;
 const rows=new Map();
 for(const music of rules.tables.LiveMusic){
   const ranks=tracks.find(t=>t.id===`music-${music._id}`)?.soloRewards?.scoreRanks;
   if(!ranks||music._liveScoreRankGroup==null)continue;
   for(const r of ranks)rows.set(`${music._liveScoreRankGroup}:${r.rank}`,{_group:music._liveScoreRankGroup,_liveScoreRank:r.rank,_requiredScore:r.requiredScore});
 }
 return {...rules,tables:{...rules.tables,LiveScoreRank:[...rows.values()]}};
}
export function scoreThresholds(rules,musicId){
 const music=rules.tables.LiveMusic.find(m=>m._id===musicId);
 if(!music)throw Error('歌曲不属于当前版本');
 const rows=(rules.tables.LiveScoreRank??[]).filter(r=>r._group===music._liveScoreRankGroup).sort((a,b)=>a._liveScoreRank-b._liveScoreRank);
 if(rows.length!==6||rows.some((r,i)=>r._liveScoreRank!==i+2||!Number.isFinite(r._requiredScore)))throw Error('缺少完整档位分数线');
 return rows.map(r=>({rank:r._liveScoreRank,score:r._requiredScore}));
}
export function applyAPBasis(row,basis='expectedScore'){
 if(!AP_BASES.includes(basis))throw Error('Invalid AP score basis');
 const rank=score=>{if(!Number.isFinite(score)||score<0)throw Error('Invalid AP score');return Math.max(...row.thresholds.filter(r=>score>=r.score).map(r=>r.rank));};
 const scoreRank=rank(row[basis]),next=row.thresholds.find(r=>r.rank===scoreRank+1);
 return {...row,scoreBasis:basis,estimatedScore:row[basis],scoreRank,minimumRank:rank(row.minimumScore),maximumRank:rank(row.maximumScore),nextRank:next?.rank??null,nextRankGap:next?Math.max(0,Math.ceil(next.score-row[basis])):null,
   gradeProbabilities:row.scoreDistribution?scoreGradeProbabilities(row.scoreDistribution,row.thresholds):null};
}
export function estimateAPChart({rules,draft,chart,candidate,mode='ordinary',eventId,basis='expectedScore'}){
 if(!['ordinary','challenge'].includes(mode))throw Error('AP 判档支持普通或挑战，激奏需使用团队结算评分。');
 const next=structuredClone(draft);next.modifiers??={};delete next.modifiers.event;
 next.selectedSongId=candidate.trackId;next.selectedDifficulty=candidate.difficulty;
 let eventAdapters=[];
 if(mode==='challenge'){
   const model=createEventEfficiency({tables:rules.tables,sourceReleaseId:rules.sourceReleaseId,eventId});
   next.modifiers.event={id:eventId,sourceReleaseId:rules.sourceReleaseId};eventAdapters=[model.challengeAdapter(rules)];
 }
 const score=createFormalSongCalculator(rules,chart,{eventAdapters}).calculate(next);
 return applyAPBasis({...candidate,mode,eventId,power:score.power,expectedScore:score.expectedScore,minimumScore:score.minimumScore,maximumScore:score.maximumScore,
   orderCount:score.orderCount,scoreDistribution:score.scoreDistribution,inputHash:score.inputHash,sourceReleaseId:score.sourceReleaseId,ruleSetVersion:score.ruleSetVersion,
   thresholds:scoreThresholds(rules,Number(candidate.trackId.split('-').at(-1)))},basis);
}
export function eventToolSearch(draft,{mode='ordinary',eventId,scoreRank,boost,cost,basis}={}){
 const next=structuredClone(draft);next.modifiers??={};delete next.modifiers.event;
 const params=new URLSearchParams(serializeTeamDraftSearch(next));
 params.set('eventMode',mode);
 for(const [name,value] of Object.entries({eventId,scoreRank,boost,cost,apBasis:basis}))if(value!=null)params.set(name,String(value));
 return '?'+params;
}
