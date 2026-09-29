import { prepareFormalChart } from './scoring-rules/formal-song-score.mjs';
import { calculateFormalNoteCore } from './scoring-rules/formal-note-core.mjs';
import { createGekisouSongCalculator } from './scoring-rules/gekisou-song-score.mjs';
import { scoringRulesAvailable } from './scoring-release-gate.mjs';
import { gekisouRankingBonus } from './scoring-rules/gekisou-rules.mjs';

const f32 = Math.fround;
const ratio = (a, b) => Number.isFinite(a) && Number.isFinite(b) && b > 0 ? a / b : null;
export { RANKING_METRICS, rankingMetrics, rankSongRows } from './song-ranking-view.mjs';
export const SONG_RANKING_BENCHMARK = Object.freeze({
  version: 'neutral-chart-v2', power: 100000, skillPercent: 100, skillSeconds: 5,
  scenario: Object.freeze({ ranks: Object.freeze([1, 1, 1]), batches: 2, seed: 20260927, timingOffsetMs: 0, frameRate: 60 })
});

/** An explicit comparison model, not a fabricated team or an optimized score. */
function referenceScore(rules, timeline, settings) {
  const setting = key => Number(rules.tables.LiveSettings.find(r => r._key === key)?._value);
  const judgement = rules.tables.LiveJudgementParameter.find(r => r._noteSimulateJudgement === 5)._scorePercent;
  const value = f32(Math.floor(f32(f32(settings.skillPercent / 100) * 100000)) / 100000);
  const commands = (settings.skillSeconds > 0 ? timeline.skillTimes : []).flatMap(time => [
    { time, value, ending: false }, { time: time + settings.skillSeconds * 1000, value: -value, ending: true }
  ]).sort((a, b) => a.time - b.time || Number(b.ending) - Number(a.ending));
  let cursor = 0, factor = 1, baseScore = 0, score = 0;
  for (const event of timeline.events) {
    while (cursor < commands.length && commands[cursor].time <= event.timeMs) factor = f32(factor + commands[cursor++].value);
    const params = { totalPower: settings.power, scoreAdjustmentFactor: setting('note_score_adjustment_factor'),
      musicScoreLevelFactor: timeline.difficultyFactor, noteFactorPercent: event.weight, judgementFactorPercent: judgement,
      comboBonusFactor: event.comboFactor, luckScoreFactorPercent: 100, convertedNoteCount: timeline.convertedNoteCount,
      eventBonusFactor: 1, lifeOnusFactor: setting('note_score_life_onus_factor'), assistModeNoteScoreFactor: 1, currentLife: setting('life_base') };
    baseScore += calculateFormalNoteCore({ ...params, scoreUpFactor: 1 }).score;
    score += calculateFormalNoteCore({ ...params, scoreUpFactor: factor }).score;
  }
  return { power: settings.power, baseScore, expectedScore: score, minimumScore: score, maximumScore: score,
    skillScoreGain: score - baseScore, warnings: timeline.warnings };
}

export function calculateRankingRow({ rules, chart, track, mode = 'ordinary' }) {
  if (!['ordinary', 'gekisou'].includes(mode)) throw new Error('无效的演出模式');
  if (!scoringRulesAvailable(rules, chart.sourceReleaseId)) throw new Error('计分规则与谱面版本不一致');
  if (chart.trackId !== track.id) throw new Error('歌曲与谱面不一致');
  const timeline = prepareFormalChart(rules, chart);
  const ordinary = referenceScore(rules, timeline, SONG_RANKING_BENCHMARK);
  const input = { selectedSongId: chart.trackId, selectedDifficulty: chart.difficulty, modifiers: {} };
  const result = mode === 'ordinary' ? ordinary : createGekisouSongCalculator(rules, chart, {
    scenario: SONG_RANKING_BENCHMARK.scenario, referenceProfile: SONG_RANKING_BENCHMARK
  }).calculate(input);
  const weight = timeline.events.reduce((sum, event) => sum + event.weight, 0);
  return {
    id: chart.id, trackId: chart.trackId, title: track.title, difficulty: chart.difficulty, level: timeline.level,
    bands: track.bandIds, bandLabels: track.bandLabels, attribute: track.musicTypeLabel,
    chartSeconds: chart.duration, audioSeconds: track.audioDuration ?? null,
    expectedScore: result.expectedScore, minimumScore: result.minimumScore, maximumScore: result.maximumScore,
    power: result.power, baseScore: ordinary.baseScore, skillScoreGain: ordinary.skillScoreGain,
    scoreMultiplier: ratio(result.expectedScore, result.power), skillMultiplier: ratio(ordinary.expectedScore, ordinary.baseScore),
    difficultyFactor: timeline.difficultyFactor, comboFactor: ratio(timeline.events.reduce((sum, e) => sum + e.weight * e.comboFactor, 0), weight),
    eventCount: timeline.events.length, convertedNoteCount: timeline.convertedNoteCount,
    ...(mode === 'gekisou' ? { gekisouMultiplier: ratio(result.expectedScore, ordinary.expectedScore),
      rankingBonus: result.rankingBonus, rankingBonusShare: result.rankingBonusShare,
      sections: result.sections.map(section => ({ ...section, rankingPercent: gekisouRankingBonus(rules, {
        missions: result.sections.map(s => s.missionType), sectionIndex: section.index,
        rank: SONG_RANKING_BENCHMARK.scenario.ranks[section.index - 1], sectionScore: 0
      }).percent })),
      standardError: result.standardError, sampleCount: result.sampleCount } : {}),
  };
}
