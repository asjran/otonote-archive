import { createFormationCalculator } from './scoring-rules/formation-power.mjs';
import { createFormalSongCalculator } from './scoring-rules/formal-song-score.mjs';
import { inspectGekisouScenario } from './scoring-rules/gekisou-rules.mjs';
import { stableSnapshotHash } from './scoring-engine.mjs';
/** One unchanged team across explicit song weights. Uniform weights are an
 * input assumption and say nothing about server matchmaking probabilities. */
export function calculateSongPool({rules,draft,songs,mode='power'}) {
  if(!['power','ordinary','gekisou'].includes(mode))throw new Error('Unknown song pool mode');
  if(!Array.isArray(songs)||!songs.length)throw new Error('曲池不能为空');
  const seen=new Set(),formation=createFormationCalculator(rules);
  const rows=songs.map(song=>{
    const id=song.trackId??song.chart?.trackId,difficulty=song.chart?.difficulty??draft.selectedDifficulty,weight=song.weight??1;
    if(typeof weight!=='number'||!Number.isFinite(weight)||weight<=0)throw new Error('曲池权重必须为正数');
    const key=`${id}:${difficulty}`;if(seen.has(key))throw new Error('曲池包含重复歌曲与难度');seen.add(key);
    const master=rules.tables.LiveMusic.find(r=>`music-${r._id}`===id);if(!master)throw new Error('曲池歌曲版本不一致');
    const input={...draft,selectedSongId:id,selectedDifficulty:difficulty};
    const result=mode==='power'?formation.calculate(input):mode==='ordinary'?createFormalSongCalculator(rules,song.chart).calculate(input):inspectGekisouScenario(rules,input,song.chart);
    return {trackId:id,difficulty,weight,attribute:master._musicType,missions:[1,2,3].map(i=>master[`_gekisouMission${i}`]),power:mode==='power'?result.total.total:result.power,
      ...(mode==='ordinary'?{expectedScore:result.expectedScore,minimumScore:result.minimumScore,maximumScore:result.maximumScore}:{}),result};
  });
  const totalWeight=rows.reduce((s,r)=>s+r.weight,0);if(!Number.isFinite(totalWeight))throw new Error('曲池权重总和溢出');
  const average=field=>rows.reduce((s,r)=>s+r[field]*(r.weight/totalWeight),0);
  return {status:mode==='gekisou'?'incomplete_rules':mode==='ordinary'||rules.verificationStatus==='reference_compatible'?'estimated':'code_calculated',mode,
    sourceReleaseId:rules.sourceReleaseId,ruleSetVersion:rules.ruleSetVersion,inputHash:stableSnapshotHash({draft,songs,mode,version:rules.ruleSetVersion}),
    expectedPower:average('power'),minimumPower:Math.min(...rows.map(r=>r.power)),maximumPower:Math.max(...rows.map(r=>r.power)),
    ...(mode==='ordinary'?{expectedScore:average('expectedScore'),worstScore:Math.min(...rows.map(r=>r.minimumScore))}:{}),
    rows,warnings:['同一支队伍固定用于整个曲池；省略权重视为等权，不代表服务器选曲概率。']};
}
