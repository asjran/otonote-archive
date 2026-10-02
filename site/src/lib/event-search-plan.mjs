// Representative charts are a first result, not a proof about unvisited songs.
// The full pass always includes every eligible chart and uses the same scorer.
export function planEventSearch(candidates,rules,draft,limit=6){
  const picked=new Map(),types=new Map(rules.tables.LiveMusic.map(m=>[`music-${m._id}`,m._musicType]));
  const add=c=>{if(c&&picked.size<limit)picked.set(c.id,c);};
  add(candidates.find(c=>c.trackId===draft.selectedSongId&&c.difficulty===draft.selectedDifficulty));
  const ranked=[...candidates].sort((a,b)=>b.level-a.level||(a.seconds??Infinity)-(b.seconds??Infinity)||a.id.localeCompare(b.id));
  const seenTypes=new Set();
  for(const c of ranked){const type=types.get(c.trackId);if(!seenTypes.has(type)){add(c);seenTypes.add(type);}}
  for(const c of [...candidates].sort((a,b)=>(a.seconds??Infinity)-(b.seconds??Infinity)||b.level-a.level||a.id.localeCompare(b.id)))add(c);
  return {quick:[...picked.values()],full:[...picked.values(),...candidates.filter(c=>!picked.has(c.id))]};
}
