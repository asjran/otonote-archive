import { skillOrdersFor } from './scoring-rules/skill-order-sampling.mjs';
import { summarizeScoreDistribution } from './scoring-rules/score-distribution.mjs';

const orders = skillOrdersFor('full');
export function validateSongSkillProfile(skills) {
  if (!Array.isArray(skills) || skills.length !== 5 || skills.some(s => !s || !Number.isFinite(s.percent) || s.percent < 0 || s.percent > 1000
    || !Number.isInteger(s.seconds * 2) || s.seconds < 0 || s.seconds > 20)) throw new Error('五个技能的加分需为 0–1000%，时长需为 0–20 秒（每档 0.5 秒）');
  return skills;
}

export function songSkillProfileKey(skills, frameRate = 60) {
  validateSongSkillProfile(skills);
  if (![60, 120].includes(frameRate)) throw new Error('模拟帧率须为 60 或 120');
  return JSON.stringify([frameRate, skills.map(({ percent, seconds }) => [percent, seconds])]);
}

/** Independent position response, built from OurNotes' chart and note core.
 * Linear comparison only: real skill conditions and float32 history require
 * the team calculator. No exact-search bound may depend on this estimate. */
export function compareSongSkills(row, skills) {
  validateSongSkillProfile(skills);
  if (!Number.isFinite(row.baseScore) || row.baseScore < 0) return null;
  const active = skills.some(s => s.percent > 0 && s.seconds > 0);
  const reference = row.skillReference;
  if (active && (reference?.version !== 'ournotes-skill-windows-v2' || reference.power !== row.benchmark?.power
    || !Array.isArray(reference.gainsByPosition) || reference.gainsByPosition.length !== 5 || reference.gainsByPosition.some(values => !Array.isArray(values) || values.length !== 41 || values.some(n => !Number.isFinite(n) || n < 0)))) return null;
  const contribution = Array.from({ length: 5 }, (_, position) => skills.map(s => s.percent && s.seconds ? reference.gainsByPosition[position][s.seconds * 2] * s.percent / 100 : 0));
  const scores = orders.map(order => row.baseScore + order.reduce((sum, slot, position) => sum + contribution[position][slot], 0));
  const distribution = summarizeScoreDistribution(scores, { kind: 'linear_reference' });
  return { distribution, positionContributions: contribution.map(values => values.reduce((a, b) => a + b, 0) / 5) };
}

export function withSongSkillProfile(row, skills) {
  const result = compareSongSkills(row, skills);
  const mean = result?.distribution.mean ?? null;
  return { ...row, calculation: 'linear', skillProfile: skills.map(s => ({ ...s })), scoreDistribution: result?.distribution ?? null,
    positionContributions: result?.positionContributions ?? null,
    expectedScore: mean, minimumScore: result?.distribution.minimum ?? null, maximumScore: result?.distribution.maximum ?? null,
    p10Score: result?.distribution.p10 ?? null, skillScoreGain: mean == null ? null : mean - row.baseScore,
    scoreMultiplier: mean == null || !row.benchmark?.power ? null : mean / row.benchmark.power,
    skillMultiplier: mean == null || !row.baseScore ? null : mean / row.baseScore };
}
