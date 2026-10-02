import { requireInteger } from './formation-power.mjs';

export function normalizeGekisouOpponents(input = []) {
  if (!Array.isArray(input) || input.length > 4) throw new Error('激奏最多填写四位对手');
  return input.map((opponent, index) => {
    if (!opponent || !Array.isArray(opponent.sections) || opponent.sections.length !== 3) throw new Error(`对手 ${index + 1} 需要三段数据`);
    return { id: `opponent-${index + 1}`, sections: opponent.sections.map(s => {
      const result = {};
      for (const key of ['combo', 'luckPoints', 'just', 'noteScore', 'perfectCount']) result[key] = requireInteger(s?.[key], `opponent ${key}`, 0, 0x7fffffff);
      return result;
    }) };
  });
}

// GekisouRankingCalculator.CompareCombo/LuckTotalPoint/JustCount first compare
// their mission count; CommonCompare (0x60ab284) then compares Score (interface
// slot 7), PerfectCount (slot 6), both descending. All AP players have input.
export function compareGekisouSection(a, b, missionType) {
  const primary = { 1: 'combo', 2: 'luckPoints', 3: 'just' }[missionType];
  if (!primary) throw new Error('Unknown Gekisou mission');
  for (const field of [primary, 'noteScore', 'perfectCount']) {
    requireInteger(a[field], field, 0, 0x7fffffff); requireInteger(b[field], field, 0, 0x7fffffff);
    if (a[field] !== b[field]) return a[field] > b[field] ? -1 : 1;
  }
  return 0;
}

export function rankGekisouSection(candidate, opponents, missionType) {
  // CalculateRanking 0x60aa878 advances the GROUP index on a nonzero compare;
  // GetPlayerRank 0x60a78fc returns group index + 1. Ties use dense ranking.
  const sorted = [{ id: 'self', ...candidate }, ...opponents.map((s, i) => ({ id: `opponent-${i + 1}`, ...s }))]
    .sort((a, b) => compareGekisouSection(a, b, missionType));
  let rank = 1;
  for (let i = 0; i < sorted.length; i++) {
    if (i && compareGekisouSection(sorted[i - 1], sorted[i], missionType)) rank++;
    if (sorted[i].id === 'self') return rank;
  }
  throw new Error('Missing ranking candidate');
}
