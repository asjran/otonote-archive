export function compareEventPlans(a,b,goal='badges'){
 if(goal==='grade'&&a.reward.scoreRank!==b.reward.scoreRank)return b.reward.scoreRank-a.reward.scoreRank;
 const metric=goal==='eventPoints'?'eventPoints':'badges',other=metric==='badges'?'eventPoints':'badges';
 return b.total[metric]-a.total[metric]||b.total[other]-a.total[other]||(a.song?.seconds??Infinity)-(b.song?.seconds??Infinity)||b.expectedScore-a.expectedScore;
}

export const EVENT_YIELD_GOAL_LABELS={badges:'道具总收益优先',eventPoints:'活动 pt 总收益优先',grade:'先最高档位，再道具收益'};
export function eventYieldGoals(goal,mode){
 if(goal==='both')return ['badges','eventPoints'];
 if(!Object.hasOwn(EVENT_YIELD_GOAL_LABELS,goal))throw Error('Invalid event yield goal');
 return [mode==='challenge'&&goal==='grade'?'badges':goal];
}

/** Keep each currency's own leaders; never add incompatible reward currencies
 * or discard the point leader through an item-only top-N truncation. */
export function selectEventYieldRows(rows,goal='both',limit=10){
 const goals=eventYieldGoals(goal),count=Math.max(1,Math.floor(limit/goals.length));
 const result=[],seen=new Map();
 for(const target of goals){
  const songs=new Set();
  const eligible=rows.filter(r=>!r.recommendationGoals||r.recommendationGoals.includes(target));
  for(const row of [...eligible].sort((a,b)=>compareEventPlans(a,b,target))){
   if(songs.has(row.song.id))continue;
   songs.add(row.song.id);
   const key=JSON.stringify([row.song.id,row.id,row.total,row.continuation?.consumption]);
   if(seen.has(key))seen.get(key).recommendationGoals.push(target);
   else{const selected={...row,recommendationGoals:[target]};seen.set(key,selected);result.push(selected);}
   if(songs.size>=count)break;
  }
 }
 return result;
}
