import {calculateFormalNoteCore} from './scoring-rules/formal-note-core.mjs';

/** Small server-precomputed table. Client input scales the +100% gain; no chart
 * reconstruction or card search happens when changing comparison parameters. */
export function buildSkillWindowReference(rules,timeline,power=100000){
  const setting=key=>Number(rules.tables.LiveSettings.find(r=>r._key===key)?._value);
  const common={totalPower:power,scoreAdjustmentFactor:setting('note_score_adjustment_factor'),
    musicScoreLevelFactor:timeline.difficultyFactor,judgementFactorPercent:rules.tables.LiveJudgementParameter.find(r=>r._noteSimulateJudgement===5)._scorePercent,
    luckScoreFactorPercent:100,convertedNoteCount:timeline.convertedNoteCount,eventBonusFactor:1,
    lifeOnusFactor:setting('note_score_life_onus_factor'),assistModeNoteScoreFactor:1,currentLife:setting('life_base')};
  const increments=timeline.skillTimes.map(()=>Array(41).fill(0));
  for(const event of timeline.events){
    const params={...common,noteFactorPercent:event.weight,comboBonusFactor:event.comboFactor};
    const gain=calculateFormalNoteCore({...params,scoreUpFactor:2}).score-calculateFormalNoteCore({...params,scoreUpFactor:1}).score;
    for(const [position,start] of timeline.skillTimes.entries()){
      const elapsed=event.timeMs-start;
      // Windows include their start and exclude their end, including exact .5s boundaries.
      if(elapsed>=0&&elapsed<20000)increments[position][Math.floor(elapsed/500)+1]+=gain;
    }
  }
  const gainsByPosition=increments.map(values=>{let gain=0;return values.map(value=>gain+=value);});
  return {version:'ournotes-skill-windows-v2',power,chartHash:timeline.chartHash,
    gains:Array.from({length:41},(_,i)=>gainsByPosition.reduce((sum,values)=>sum+values[i],0)),gainsByPosition,
    startsSeconds:timeline.skillTimes.map(t=>t/1000)};
}
