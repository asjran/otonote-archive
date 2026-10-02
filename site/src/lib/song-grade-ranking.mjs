import {rankSongRows} from './song-ranking-view.mjs';
import {compareSongSkills,songSkillProfileKey} from './song-skill-profile.mjs';
export const SCORE_GRADES=['D','C','B','A','S','SS'];
export function validGradeThresholds(rows){
  if(!Array.isArray(rows)||rows.length!==6)return null;
  const sorted=rows.map(r=>({rank:r.rank,score:r.requiredScore??r.score})).sort((a,b)=>a.rank-b.rank);
  return sorted.every((r,i)=>r.rank===i+2&&Number.isSafeInteger(r.score)&&r.score>=0&&(i?r.score>sorted[i-1].score:r.score===0))?sorted:null;
}
export function gradeAtScore(thresholds,score){
  if(!Number.isSafeInteger(score)||score<0)throw Error('分数需为非负整数');
  const rows=validGradeThresholds(thresholds);if(!rows)return null;
  return rows.findLast(r=>score>=r.score).rank;
}
export function selectGradeReference(row,edition){
  if(edition)return row.gradeReferences?.[edition];
  const refs=['global','jp'].map(key=>row.gradeReferences?.[key]).filter(Boolean);
  return refs.find(r=>r.verified)??refs[0];
}
export function customSkillScore(row,{skillPercent=100,skillSeconds=5}={}){
  if(!Number.isFinite(skillPercent)||skillPercent<0||skillPercent>1000||!Number.isInteger(skillSeconds*2)||skillSeconds<0||skillSeconds>20)throw Error('加分比例需为 0–1000%，持续时间需为 0–20 秒（每档 0.5 秒）');
  if(!Number.isFinite(row.baseScore))return null;
  if(!skillPercent||!skillSeconds)return row.baseScore;
  const gain=skillSeconds===5?row.skillScoreGain:row.skillReference?.gains?.[skillSeconds*2];
  return Number.isFinite(gain)?row.baseScore+gain*skillPercent/100:null;
}
/** Linear reference from the published fixed-power benchmark. Native per-note
 * rounding prevents this being an exact inverse or a guarantee for a real team.
 * Never apply an edition's thresholds to an unverified edition's benchmark.
 */
export function songGradeReference(row,{edition,targetRank=5,profile='none',score=null,skillPercent=100,skillSeconds=5,skills}={}){
  if(![2,3,4,5,6,7].includes(targetRank)||!['none','benchmark','custom'].includes(profile))throw Error('Invalid grade reference settings');
  const reference=selectGradeReference(row,edition),thresholds=validGradeThresholds(reference?.thresholds);
  const targetScore=thresholds?.find(r=>r.rank===targetRank)?.score??null;
  const replay=skills&&row.skillReplay&&row.skillReplay.profileKey===songSkillProfileKey(skills,row.skillReplay.frameRate)?row.skillReplay:null;
  const skillComparison=profile==='custom'&&skills?(replay?{distribution:replay.distribution,positionContributions:null}:compareSongSkills(row,skills)):null;
  const benchmarkScore=profile==='none'?row.baseScore:profile==='custom'?(skills?skillComparison?.distribution.mean??null:customSkillScore(row,{skillPercent,skillSeconds})):row.expectedScore;
  const usable=reference?.verified&&row.benchmark?.power>0&&Number.isFinite(benchmarkScore)&&benchmarkScore>0;
  const requiredPower=usable&&targetScore!=null?targetScore*row.benchmark.power/benchmarkScore:null;
  return {...row,gradeReference:reference,thresholds,targetRank,targetScore,requiredPower,benchmarkScore,
    ...(skills&&profile==='custom'?{scoreDistribution:skillComparison?.distribution??null,positionContributions:skillComparison?.positionContributions??null}:{}),
    displayPower:requiredPower==null?null:Math.ceil(requiredPower/1000)*1000,
    enteredScore:score,enteredRank:score==null?null:gradeAtScore(thresholds,score),
    targetGap:score==null||targetScore==null?null:Math.max(0,targetScore-score)};
}
export function rankGradeRows(rows,options={}){
  const filtered=rankSongRows(rows,{...options,metric:'expectedScore'}).filter(r=>selectGradeReference(r,options.edition));
  const result=filtered.map(r=>songGradeReference(r,options)).sort((a,b)=>(a.requiredPower??Infinity)-(b.requiredPower??Infinity)||(a.durationSeconds??Infinity)-(b.durationSeconds??Infinity)||a.id.localeCompare(b.id));
  let rank=0;
  return result.map((r,i)=>{if(r.requiredPower==null)return {...r,rank:null};if(!i||r.requiredPower!==result[i-1].requiredPower)rank=i+1;return {...r,rank};});
}
