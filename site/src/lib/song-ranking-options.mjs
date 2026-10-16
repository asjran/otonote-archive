import { RANKING_METRICS, rankSongRows } from './song-ranking-view.mjs';
import { songGradeReference } from './song-grade-ranking.mjs';

// Presentation-only metrics. Shared scoring and optimizer bounds stay unchanged.
export const RANKING_OPTIONS = Object.freeze({
  expectedScore: ['平均参考分', 'Mean reference score', 'score'],
  efficiency: ['每秒得分', 'Score per second', 'efficiency'],
  minimumScore: ['最低参考分', 'Minimum reference score', 'score'],
  maximumScore: ['最高参考分', 'Maximum reference score', 'score'],
  p10Score: ['P10 参考分', 'P10 reference score', 'score'],
  p10Efficiency: ['P10 每秒得分', 'P10 score per second', 'efficiency'],
  requiredPower: ['达档参考综合力', 'Estimated power for grade', 'power', 'asc'],
  durationSeconds: ['歌曲时长', 'Song duration', 'seconds', 'asc'],
  level: ['谱面等级', 'Chart level', 'number', 'asc'],
  skillScoreGain: ['普通技能净增分', 'Ordinary skill score gain', 'score'],
  skillShare: ['普通技能得分占比', 'Ordinary skill score share', 'percent'],
  scoreSpread: ['最高与最低参考分差', 'Reference score spread', 'score', 'asc'],
  scoreMultiplier: ['转分倍率', 'Score multiplier', 'ratio'],
  skillMultiplier: ['普通技能增益倍率', 'Ordinary skill multiplier', 'ratio'],
  difficultyFactor: ['难度倍率', 'Difficulty multiplier', 'ratio'],
  comboFactor: ['加权连击倍率', 'Weighted combo multiplier', 'ratio'],
  eventCount: ['计分判定数', 'Scoring event count', 'number'],
  averageDensity: ['平均判定密度', 'Average scoring event density', 'density'],
  peakDensity: ['最密一秒判定数', 'Peak scoring events in one second', 'number'],
  bpmMax: ['最高 BPM', 'Maximum BPM', 'number'],
  gekisouMultiplier: ['激奏 / 普通得分倍率', 'Gekisou / ordinary multiplier', 'ratio'],
  rankingBonusShare: ['激奏名次奖励占比', 'Gekisou placement bonus share', 'percent']
});
export const defaultRankingDirection = metric => RANKING_OPTIONS[metric]?.[3] ?? 'desc';
export const editionName = (edition, en = false) => edition === 'jp' ? (en ? 'JP' : '日服') : (en ? 'Global' : '国际版');

const ranges = [
  ['minLevel', 'maxLevel', '等级', 'Level', 1, 40],
  ['minSeconds', 'maxSeconds', '时长', 'Duration', 0, 3600],
  ['minBpm', 'maxBpm', 'BPM', 'BPM', 0, 2000],
  ['minDensity', 'maxDensity', '平均判定密度', 'Average density', 0, 10000],
  ['minValue', 'maxValue', '排序值', 'Sort value', 0, Number.MAX_SAFE_INTEGER]
];
export function validateRankingOptions(options, en = false) {
  const parsed = { ...options };
  const parse = (key, label, min, max) => {
    const raw = options[key];
    if (raw == null || raw === '' || raw === 'all') return null;
    const value = Number(raw);
    if (!Number.isFinite(value) || value < min || value > max) throw new Error(en ? `${label} must be between ${min} and ${max}.` : `${label}需为 ${min}–${max} 之间的数值。`);
    return value;
  };
  for (const [low, high, zh, english, min, max] of ranges) {
    const label = en ? english : zh;
    parsed[low] = parse(low, label, min, max); parsed[high] = parse(high, label, min, max);
    if (parsed[low] !== null && parsed[high] !== null && parsed[low] > parsed[high]) throw new Error(en ? `${label}: minimum must not exceed maximum.` : `${label}下限不能大于上限。`);
  }
  parsed.overhead = parse('overhead', en ? 'Extra time per play' : '每局额外耗时', 0, 3600) ?? 0;
  if (options.metric != null && !Object.hasOwn(RANKING_OPTIONS, options.metric)) throw new Error(en ? 'Unknown ranking metric.' : '未知排名指标。');
  if (options.direction != null && !['asc', 'desc'].includes(options.direction)) throw new Error(en ? 'Unknown sort direction.' : '未知排序方向。');
  return parsed;
}

/** A merged row may have one edition still pending. Never lend it the other
 * edition's calculated score, skill windows, or replay source. */
export function scopeRankingRows(rows, edition = 'all') {
  if (!['global', 'jp'].includes(edition)) return rows;
  return rows.filter(row => [...(row.applicableEditions ?? []), ...(row.pendingEditions ?? [])].includes(edition))
    .map(row => {
      if (row.applicableEditions?.includes(edition)) return row;
      const reference = row.editionChartReferences?.[edition];
      const {trackId: _trackId, sourceReleaseId: _releaseId, ...display} = reference ?? {};
      const pending = { ...row, ...display, pending: true, replaySource: null, skillReference: null, scoreDistribution: null, skillReplay: null,
        meta: null, eventCount: null, convertedNoteCount: null, sections: null, sampleCount: null, standardError: null };
      for (const field of [...Object.keys(RANKING_METRICS), 'baseScore', 'skillScoreGain', 'power']) pending[field] = null;
      return pending;
    });
}

export function rankingRowState(row) {
  return row.pending ? 'pending' : Number.isFinite(row.expectedScore) ? 'calculated' : 'unavailable';
}

function derived(row) {
  const valid = (value, predicate = () => true) => Number.isFinite(value) && predicate(value) ? value : null;
  return { ...row, averageDensity: valid(row.meta?.averageDensity), peakDensity: valid(row.meta?.peakDensity), bpmMax: valid(row.meta?.bpmMax),
    skillShare: Number.isFinite(row.skillScoreGain) && Number.isFinite(row.baseScore) && row.baseScore + row.skillScoreGain > 0 ? row.skillScoreGain / (row.baseScore + row.skillScoreGain) : null,
    scoreSpread: Number.isFinite(row.minimumScore) && Number.isFinite(row.maximumScore) ? row.maximumScore - row.minimumScore : null,
    p10Efficiency: Number.isFinite(row.p10Score) && row.cycleSeconds > 0 ? row.p10Score / row.cycleSeconds : null };
}
const inRange = (value, min, max) => min == null && max == null || Number.isFinite(value) && (min == null || value >= min) && (max == null || value <= max);

/** Filter -> derive -> order -> choose one chart per song -> competition ranks.
 * Group only by proven song identity, otherwise conservatively by source ID. */
export function rankRefinedSongRows(rows, settings = {}) {
  const options = validateRankingOptions({ metric: 'expectedScore', ...settings });
  const { metric, direction = defaultRankingDirection(metric), edition = 'all', status = 'all', attribute = 'all', grouping = 'charts' } = options;
  let selected = rankSongRows(scopeRankingRows(rows, edition), { query: options.query ?? '', difficulty: options.difficulty ?? 'all', band: options.band ?? 'all',
    durationBasis: options.durationBasis ?? 'chart', overhead: options.overhead })
    .map(row => derived(metric === 'requiredPower' ? songGradeReference(row, { ...options, edition: options.gradeEdition ?? (edition === 'all' ? undefined : edition) }) : row))
    .filter(row => (status === 'all' || status === rankingRowState(row)) && (attribute === 'all' || row.attribute === attribute)
      && inRange(row.level, options.minLevel, options.maxLevel) && inRange(row.durationSeconds, options.minSeconds, options.maxSeconds)
      && inRange(row.meta?.bpmMin, options.minBpm, null) && inRange(row.meta?.bpmMax, null, options.maxBpm)
      && inRange(row.averageDensity, options.minDensity, options.maxDensity) && inRange(row[metric], options.minValue, options.maxValue));
  selected.sort((a, b) => {
    const av = a[metric], bv = b[metric], aValid = Number.isFinite(av), bValid = Number.isFinite(bv);
    if (aValid !== bValid) return aValid ? -1 : 1;
    return (aValid ? (av - bv) * (direction === 'asc' ? 1 : -1) : 0) || a.id.localeCompare(b.id);
  });
  if (grouping === 'songs') {
    const seen = new Set();
    selected = selected.filter(row => {
      const key = row.songIdentity || `${row.sourceEdition}:${row.trackId}`;
      if (seen.has(key)) return false;
      seen.add(key); return true;
    });
  }
  let rank = 0;
  return selected.map((row, index) => {
    if (!Number.isFinite(row[metric])) return { ...row, rank: null };
    if (!index || row[metric] !== selected[index - 1][metric]) rank = index + 1;
    return { ...row, rank };
  });
}

// Pure link construction is shared by all row actions and covered independently.
export function rankingSongLinks(row, { edition = row.sourceEdition, locale = 'zh-CN', server = null, mode = 'ordinary' } = {}) {
  const reference = row.editionChartReferences?.[edition] ?? row.gradeReferences?.[edition];
  if (edition !== row.sourceEdition && !reference?.trackId) edition = row.sourceEdition;
  const track = edition === row.sourceEdition ? row.trackId.replace(/^(global|jp)--/, '') : reference.trackId;
  const params = new URLSearchParams({ song: track, difficulty: row.difficulty });
  const compatible = edition === 'jp' ? server === 'jp' : ['global-hmt', 'global-kr', 'global-en'].includes(server);
  if (compatible) params.set('server', server);
  const prefix = `/${edition}/${locale === 'en' ? 'en' : 'zh-CN'}`;
  const chart = new URLSearchParams({ view: 'analysis', difficulty: row.difficulty });
  if (compatible) chart.set('server', server);
  return { calculator: `${prefix}/tools/song-calculator/?${params}&scoreMode=${mode === 'gekisou' ? 'gekisou' : 'ordinary'}`, chart: `${prefix}/music/${track}/?${chart}`,
    grade: `${prefix}/tools/ap-grade/?${params}`, event: `${prefix}/tools/event-efficiency/?${params}&eventMode=ordinary` };
}
