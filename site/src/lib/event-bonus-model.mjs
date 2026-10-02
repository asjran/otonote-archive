/** Merge destinations for the same eligibility condition; retain every rank value. */
export function groupEventBonuses(effects) {
  const groups = new Map();
  for (const effect of effects) {
    const constraints = effect.constraints;
    const key = JSON.stringify(Object.keys(constraints).sort().map(key => [key, constraints[key]]));
    if (!groups.has(key)) groups.set(key, {constraints, names:effect.targetNames, effects:[], kind:constraints.memberCardId || constraints.supportCardId ? 'card' : constraints.bandId ? 'band' : constraints.cardType ? 'attribute' : 'other'});
    groups.get(key).effects.push(effect);
  }
  return [...groups.values()].sort((a,b) => ['band','attribute','card','other'].indexOf(a.kind) - ['band','attribute','card','other'].indexOf(b.kind));
}

/** Matches JP MasterEventEffect.GetEffectPercentageByRank: floor(raw / 100).
 * The bonus-detail presenter uses this integer percentage for all five ranks.
 * Evidence: output/verification/event-bonus-20260930/disassembly.txt, 0x5802558.
 * This formats one condition; do not use displayed integers to calculate payouts.
 */
export function eventBonusPercentage(value) {
  return typeof value === 'number' && Number.isFinite(value) ? Math.floor(value / 100) : null;
}
