import {RANKING_OPTIONS, GRADE_RANKING_METRICS, editionName} from './song-ranking-options.mjs';
import {SCORE_GRADES} from './song-grade-ranking.mjs';

const basic = ['title','difficulty','level','bandLabel','attribute','editionLabel','calculationState'];
const scores = ['expectedScore','efficiency','minimumScore','maximumScore','p10Score','p10Efficiency'];
const timing = ['durationSeconds','chartSeconds','audioSeconds','cycleSeconds'];
const skills = ['skillScoreGain','skillShare','scoreSpread','baseScore','scoreMultiplier','skillMultiplier','difficultyFactor','comboFactor'];
const structure = ['eventCount','convertedNoteCount','averageDensity','peakDensity','bpmMin','bpmMax'];
const gekisou = ['gekisouMultiplier','rankingBonusShare','rankingBonus','sampleCount','standardError'];
export function rankingTableColumns(mode = 'ordinary', metric = 'expectedScore') {
  const keys = ['title', ...(GRADE_RANKING_METRICS.includes(metric) ? GRADE_RANKING_METRICS : []), ...scores.slice(0,2), timing[0], ...basic.slice(1), ...scores.slice(2), ...timing.slice(1), ...skills, ...structure,
    ...(mode === 'gekisou' ? gekisou : [])];
  return keys.map(key => ({key, labels:RANKING_OPTIONS[key], width:key === 'title' ? 220 : key === 'difficulty' || key === 'level' ? 76
    : key === 'bandLabel' || key === 'editionLabel' || key === 'calculationState' ? 140 : key === 'requiredPower' ? 144 : 116}));
}
export function formatRankingCell(key, row, locale = 'zh-CN') {
  const en = locale.startsWith('en'), value = row[key];
  const number = (n, digits = 2) => Number.isFinite(n) ? n.toLocaleString(locale, {maximumFractionDigits:digits}) : '—';
  if (key === 'editionLabel') return [row.applicableEditions?.length ? row.applicableEditions.map(edition => editionName(edition,en)).join(' / ') : '',
    row.pendingEditions?.length ? `${en ? 'Pending: ' : '待算：'}${row.pendingEditions.map(edition => editionName(edition,en)).join(' / ')}` : ''].filter(Boolean).join(' · ') || '—';
  if (key === 'calculationState') return row.pending ? en ? 'Benchmark pending' : '基准待计算' : !Number.isFinite(row.expectedScore) ? en ? 'Unavailable' : '当前条件不可算'
    : row.calculation === 'replay' ? en ? 'Replay complete' : '已完成精算' : row.calculation === 'linear' && row.skillProfile?.some(skill => skill.percent && skill.seconds) ? en ? 'Quick estimate' : '快速估算' : en ? 'Benchmark ready' : '基准已计算';
  if (RANKING_OPTIONS[key]?.[2] === 'text') return key === 'difficulty' ? value?.toUpperCase() ?? '—' : value || '—';
  if (!Number.isFinite(value)) return '—';
  if (key === 'requiredPower') return `${en ? 'Approx. ' : '约 '}${number(row.displayPower,0)}`;
  if (key === 'enteredRank') return SCORE_GRADES[value - 2] ?? '—';
  const type = RANKING_OPTIONS[key]?.[2];
  return type === 'percent' ? `${number(value*100)}%` : type === 'ratio' ? `${number(value,4)}×` : type === 'seconds' ? `${number(value)} s` : type === 'density' ? `${number(value)} / s` : number(value);
}
