const cache=new WeakMap();

/** Upgrade rows are authoritative; effect rows may describe unreleased levels. */
export function bandItemLevels(rules,id) {
  if(!cache.has(rules)) {
    const items=new Map((rules.tables.BandItem??[]).map(item=>[item._id,new Set()]));
    if(items.size&&!Array.isArray(rules.tables.BandItemLevel))throw Error('缺少乐器升级等级表，请更新资料后重试');
    for(const row of rules.tables.BandItemLevel??[]) {
      if(!items.has(row._bandItemId)||!Number.isSafeInteger(row._level)||row._level<1)throw Error('乐器升级等级表无效');
      items.get(row._bandItemId).add(row._level);
    }
    for(const levels of items.values())if(!levels.size)throw Error('乐器升级等级表不完整');
    cache.set(rules,items);
  }
  return cache.get(rules).get(Number(id));
}
export function bandItemMaxLevel(rules,id) {
  const levels=bandItemLevels(rules,id);
  if(!levels)throw Error(`Unknown instrument ${id}`);
  return Math.max(...levels);
}
export function validateBandItemLevel(rules,id,level) {
  const levels=bandItemLevels(rules,id);
  if(!levels)throw Error(`Unknown instrument ${id}`);
  if(!Number.isSafeInteger(level)||level<0||(level>0&&!levels.has(level)))throw Error(`Unknown instrument/level ${id}/${level}`);
  return level;
}

const projectionCache=new WeakMap();
/** Old sealed snapshots retain the upgrade rows in their band-item projection. */
export function withBandItemLevels(rules,projection) {
  if(!rules?.tables||rules.tables.BandItemLevel)return rules;
  if(projectionCache.has(rules))return projectionCache.get(rules);
  if(!projection||projection.sourceReleaseId!==rules.sourceReleaseId||!Array.isArray(projection.items))throw Error('乐器升级资料与计算规则版本不一致');
  const levels=projection.items.flatMap(item=>item.levels.map(level=>({_bandItemId:item.masterId,_level:level.level,_playerRank:level.playerRank})));
  const next={...rules,tables:{...rules.tables,BandItemLevel:levels}};
  for(const item of next.tables.BandItem??[])bandItemMaxLevel(next,item._id);
  projectionCache.set(rules,next);return next;
}
