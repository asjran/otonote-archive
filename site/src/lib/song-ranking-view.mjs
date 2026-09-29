const ratio = (a, b) => Number.isFinite(a) && Number.isFinite(b) && b > 0 ? a / b : null;
export const RANKING_METRICS = Object.freeze({
  expectedScore: '基准得分', efficiency: '每秒得分', scoreMultiplier: '转分倍率',
  minimumScore: '最低出分', maximumScore: '最高出分', difficultyFactor: '难度倍率',
  comboFactor: '加权连击倍率', skillMultiplier: '普通技能增益倍率',
  gekisouMultiplier: '激奏 / 普通得分倍率', rankingBonusShare: '激奏名次奖励占比'
});

export function rankingMetrics(row, { durationBasis = 'chart', overhead = 0 } = {}) {
  const rawSeconds = durationBasis === 'audio' ? row.audioSeconds : row.chartSeconds;
  const durationSeconds = Number.isFinite(rawSeconds) && rawSeconds > 0 ? rawSeconds : null;
  const cycleSeconds = durationSeconds === null ? null : durationSeconds + overhead;
  return { ...row, durationSeconds, cycleSeconds, efficiency: ratio(row.expectedScore, cycleSeconds) };
}

export function rankSongRows(rows, { metric = 'expectedScore', query = '', difficulty = 'all', band = 'all', maxLevel = Infinity, ...timing } = {}) {
  if (!(metric in RANKING_METRICS)) throw new Error('未知排名指标');
  const normalize = value => String(value).normalize('NFKC').toLowerCase().replace(/\s/g, '');
  const terms = query.trim().split(/\s+/).filter(Boolean).map(normalize);
  const sorted = rows.filter(row => (difficulty === 'all' || row.difficulty === difficulty)
    && (band === 'all' || row.bands?.includes(band)) && row.level <= maxLevel
    && terms.every(term => normalize(`${row.title} ${row.bandLabels?.join(' ')} ${row.trackId}`).includes(term)))
    .map(row => rankingMetrics(row, timing))
    .sort((a, b) => (Number.isFinite(b[metric]) ? b[metric] : -Infinity) - (Number.isFinite(a[metric]) ? a[metric] : -Infinity) || a.id.localeCompare(b.id));
  let rank = 0;
  return sorted.map((row, index) => {
    if (!Number.isFinite(row[metric])) return { ...row, rank: null };
    if (!index || row[metric] !== sorted[index - 1][metric]) rank = index + 1;
    return { ...row, rank };
  });
}
