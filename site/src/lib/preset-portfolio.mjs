import { createFormationCalculator } from './scoring-rules/formation-power.mjs';
import { createFormalSongCalculator } from './scoring-rules/formal-song-score.mjs';
import { createGekisouSongCalculator, normalizeGekisouScenario } from './scoring-rules/gekisou-song-score.mjs';
import { resolveGekisouSkills } from './scoring-rules/gekisou-rules.mjs';
import { stableSnapshotHash } from './scoring-engine.mjs';

export function preparePresetDraft(rules, draft, { maximizeTrainable = true } = {}) {
  const result = structuredClone(draft), calculator = createFormationCalculator(rules);
  if (result.slots?.length !== 5 || result.slots.some(s => !s.memberCardId || !s.supportCardId)) throw new Error('预设需要五张成员和五张留影');
  result.modifiers ??= {};
  result.modifiers.growth = { ...result.modifiers.growth };
  for (const slot of result.slots) for (const kind of ['member', 'support']) {
    const id = slot[`${kind}CardId`], type = kind === 'member' ? 'Member' : 'Support';
    const row = calculator.card(id, kind), previous = result.modifiers.growth[id] ?? {};
    const actual = calculator.resolveGrowth(row, type, previous);
    result.modifiers.growth[id] = { ...previous, rank: actual.rank,
      level: maximizeTrainable ? calculator.resolveGrowth(row, type, { ...previous, level: undefined }).level : actual.level,
      ...(kind === 'member' ? { awake: actual.awake, skillLevel: maximizeTrainable ? 5 : previous.skillLevel ?? 1,
        gekisouSkillLevel: maximizeTrainable ? 5 : previous.gekisouSkillLevel ?? 1 } : {}) };
  }
  calculator.calculate(result); // Also rejects duplicate characters/supports.
  return result;
}

export function presetWindowCardCount(rules, draft) {
  return new Set(resolveGekisouSkills(rules, draft).filter(s => s.effects.some(e =>
    e.definition._skillEffectType === 4004)).map(s => `${s.kind}:${s.sourceCardId}`)).size;
}

/** Selection is based on a per-song maximum, never on averaged team power.
 * Greedy marginal coverage is deterministic but is not a global optimum. */
export function selectPresetPortfolio(matrix, limit) {
  const { candidates, songs, scores } = matrix;
  if (!candidates?.length || !songs?.length || scores?.length !== songs.length) throw new Error('预设或曲池为空');
  if (!Number.isInteger(limit) || limit < 1 || limit > candidates.length) throw new Error('保留队伍数无效');
  const totalWeight = songs.reduce((sum, s) => sum + s.weight, 0);
  if (!Number.isFinite(totalWeight) || songs.some(s => !Number.isFinite(s.weight) || s.weight <= 0)) throw new Error('曲池权重必须为正数');
  if (scores.some(row => row.length !== candidates.length || row.some(s => !Number.isFinite(s.expectedScore) || s.expectedScore < 0))) throw new Error('候选分数矩阵无效');
  const weights = songs.map(s => s.weight / totalWeight);
  const average = values => values.reduce((sum, value, i) => sum + value * weights[i], 0);
  const selected = [], steps = []; let best = songs.map(() => 0);
  while (selected.length < limit) {
    let winner = -1, gain = -Infinity, values;
    for (let c = 0; c < candidates.length; c++) {
      if (selected.includes(c)) continue;
      const next = scores.map((row, s) => Math.max(best[s], row[c].expectedScore));
      const improvement = average(next.map((v, s) => v - best[s]));
      if (improvement > gain) { winner = c; gain = improvement; values = next; }
    }
    if (selected.length && gain <= 0) break;
    selected.push(winner); best = values;
    steps.push({ candidateId: candidates[winner].id, marginalGain: gain, expectedScore: average(best) });
  }
  // Later specialists can completely replace an earlier generalist. Do not
  // spend a game preset slot on a team that no longer adds coverage.
  for (const c of [...selected]) {
    const others = selected.filter(i => i !== c);
    if (others.length && scores.every((row, s) => Math.max(...others.map(i => row[i].expectedScore)) === best[s])) {
      selected.splice(selected.indexOf(c), 1);
    }
  }
  steps.length = 0;
  let previous = songs.map(() => 0);
  for (const c of selected) {
    const values = scores.map((row, s) => Math.max(previous[s], row[c].expectedScore));
    steps.push({ candidateId: candidates[c].id, marginalGain: average(values.map((v, s) => v - previous[s])), expectedScore: average(values) });
    previous = values;
  }
  const rows = songs.map((song, s) => {
    const ranked = [...selected].sort((a, b) => scores[s][b].expectedScore - scores[s][a].expectedScore || a - b);
    const [winner, runner] = ranked, result = scores[s][winner];
    const gap = runner == null ? null : result.expectedScore - scores[s][runner].expectedScore;
    return { ...song, candidateId: candidates[winner].id, alternateId: runner == null ? null : candidates[runner].id,
      ...result, gap, gapPercent: runner == null || !scores[s][runner].expectedScore ? null : gap / scores[s][runner].expectedScore * 100 };
  });
  const contributions = candidates.map((candidate, c) => {
    const without = selected.filter(i => i !== c);
    return { candidateId: candidate.id, selected: selected.includes(c),
      recommendedSongs: rows.filter(row => row.candidateId === candidate.id).length,
      singleTeamScore: average(scores.map(row => row[c].expectedScore)),
      additionalGain: average(scores.map((row, s) => Math.max(0, row[c].expectedScore - best[s]))),
      removalLoss: selected.includes(c) && without.length ? average(scores.map((row, s) => best[s] - Math.max(...without.map(i => row[i].expectedScore)))) : null };
  });
  return { method: 'greedy_marginal_coverage', requestedLimit: limit, selectedIds: selected.map(i => candidates[i].id),
    expectedScore: average(best), steps, rows, contributions };
}

/** Compare an actual replacement, including songs that become worse. */
export function comparePresetReplacement(matrix, selectedIds, beforeId, afterId) {
  const indices = new Map(matrix.candidates.map((c, i) => [c.id, i]));
  if (!selectedIds.includes(beforeId) || !indices.has(afterId) || selectedIds.some(id => !indices.has(id))) throw new Error('换队对象无效');
  const before = selectedIds.map(id => indices.get(id));
  const after = [...new Set(selectedIds.map(id => indices.get(id === beforeId ? afterId : id)))];
  const totalWeight = matrix.songs.reduce((s, r) => s + r.weight, 0);
  const rows = matrix.songs.map((song, s) => {
    const winner = indices => indices.reduce((best, c) => matrix.scores[s][c].expectedScore > matrix.scores[s][best].expectedScore ? c : best);
    const oldResult = matrix.scores[s][winner(before)], newResult = matrix.scores[s][winner(after)];
    const oldScore = oldResult.expectedScore, newScore = newResult.expectedScore;
    return { ...song, before: oldScore, after: newScore, delta: newScore - oldScore,
      sectionDeltas: (newResult.sections ?? []).map((section, i) => ({ index: section.index, missionType: section.missionType,
        scoreDelta: section.totalScore - oldResult.sections[i].totalScore })),
      percent: oldScore ? (newScore - oldScore) / oldScore * 100 : null };
  });
  return { beforeId, afterId, rows, expectedDelta: rows.reduce((s, r) => s + r.delta * (r.weight / totalWeight), 0),
    improvedSongs: rows.filter(r => r.delta > 0).length, worsenedSongs: rows.filter(r => r.delta < 0).length };
}

export async function evaluatePresetPool({ rules, candidates, songs, mode = 'gekisou', scenario,
  limit = 3, maximizeTrainable = true, maxWindowCards = 1 }, { onProgress, yieldControl = async () => {} } = {}) {
  if (!['ordinary', 'gekisou'].includes(mode)) throw new Error('请选择普通或激奏模式');
  const normalizedScenario = mode === 'gekisou' ? normalizeGekisouScenario(scenario) : null;
  if (![0, 1].includes(maxWindowCards)) throw new Error('判卡上限只能为 0 或 1');
  if (!Array.isArray(candidates) || !candidates.length || candidates.length > 100) throw new Error('请准备 1–100 支候选预设');
  if (!Array.isArray(songs) || !songs.length) throw new Error('曲池不能为空');
  const ids = new Set(), omitted = [];
  const prepared = candidates.flatMap(c => {
    if (typeof c.id !== 'string' || !c.id || ids.has(c.id)) throw new Error('预设 ID 无效或重复'); ids.add(c.id);
    if (c.sourceReleaseId !== rules.sourceReleaseId) throw new Error(`${c.name}: 预设版本不一致`);
    const draft = preparePresetDraft(rules, c.draft, { maximizeTrainable });
    const windowCards = presetWindowCardCount(rules, draft);
    if (mode === 'gekisou' && windowCards > maxWindowCards) { omitted.push({ id: c.id, reason: `含 ${windowCards} 张扩窗卡，超过上限` }); return []; }
    return [{ ...c, draft, windowCards }];
  });
  if (!prepared.length) throw new Error('没有符合判卡上限的预设');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new Error('保留队伍数无效');
  const seen = new Set(), summaries = [], scores = [], warnings = new Set();
  for (const [s, song] of songs.entries()) {
    const chart = song.chart, weight = song.weight ?? 1;
    if (!chart || chart.trackId !== song.trackId || chart.sourceReleaseId !== rules.sourceReleaseId) throw new Error('曲池谱面缺失或版本不一致');
    if (!Number.isFinite(weight) || weight <= 0) throw new Error('曲池权重必须为正数');
    const key = `${chart.trackId}:${chart.difficulty}`;
    if (seen.has(key)) throw new Error('曲池包含重复歌曲与难度'); seen.add(key);
    const calculator = mode === 'gekisou' ? createGekisouSongCalculator(rules, chart, { scenario: normalizedScenario }) : createFormalSongCalculator(rules, chart);
    const master = rules.tables.LiveMusic.find(m => `music-${m._id}` === song.trackId);
    if (!master) throw new Error('曲池歌曲不存在');
    summaries.push({ trackId: chart.trackId, difficulty: chart.difficulty, weight, title: song.title ?? chart.trackId,
      missions: [1, 2, 3].map(i => master[`_gekisouMission${i}`]), attribute: master._musicType });
    const row = [];
    for (const [c, candidate] of prepared.entries()) {
      const input = { ...candidate.draft, selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty };
      const result = calculator.calculate(input);
      result.warnings?.forEach(w => warnings.add(w));
      row.push({ expectedScore: result.expectedScore, minimumScore: result.minimumScore, maximumScore: result.maximumScore,
        power: result.power, sections: result.sections ?? [], standardError: result.standardError ?? null });
      onProgress?.({ completed: s * prepared.length + c + 1, total: songs.length * prepared.length });
      await yieldControl();
    }
    scores.push(row);
  }
  const matrix = { candidates: prepared, songs: summaries, scores };
  return { schemaVersion: 1, sourceReleaseId: rules.sourceReleaseId, ruleSetVersion: rules.ruleSetVersion,
    inputHash: stableSnapshotHash({ rules: stableSnapshotHash(rules), candidates: prepared, songs, mode, scenario: normalizedScenario, limit, maximizeTrainable, maxWindowCards }),
    mode, scenario: normalizedScenario, maximizeTrainable, maxWindowCards, matrix, omitted,
    portfolio: selectPresetPortfolio(matrix, Math.min(limit, prepared.length)),
    warnings: [...(songs.length > 1 ? ['默认等权是比较条件，不代表服务器抽选概率。', '多曲推荐采用贪心覆盖，不保证全卡库最优。'] : ['仅比较已保存的候选队伍，不保证全卡库最优。']),
      '按 AP 模拟；FC 中的非 PERFECT 判定尚未逐音符输入。', ...warnings] };
}
