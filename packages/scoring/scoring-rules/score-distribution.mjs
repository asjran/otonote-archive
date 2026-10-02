export const SCORE_DISTRIBUTION_VERSION = 'ournotes-distribution-v1';

/** Equal-weight outcomes. Compression preserves every order/sample, including
 * identical traces. Complete describes enumeration, not real-play certainty. */
export function summarizeScoreDistribution(scores, { kind = 'skill_orders', complete = true } = {}) {
  if (!Array.isArray(scores) || !scores.length || scores.some(score => !Number.isFinite(score) || score < 0 || score > Number.MAX_SAFE_INTEGER)) {
    throw new Error('Score distribution requires finite non-negative outcomes');
  }
  if (!['skill_orders', 'seed_samples', 'linear_reference'].includes(kind) || typeof complete !== 'boolean') throw new Error('Invalid distribution provenance');
  const counts = new Map();
  for (const score of scores) counts.set(score, (counts.get(score) ?? 0) + 1);
  const outcomes = [...counts].sort(([a], [b]) => a - b).map(([score, count]) => ({ score, count }));
  const count = scores.length;
  const percentile = p => {
    const rank = Math.max(1, Math.ceil(p * count));
    let seen = 0;
    return outcomes.find(outcome => (seen += outcome.count) >= rank).score;
  };
  return { version: SCORE_DISTRIBUTION_VERSION, kind, complete: kind === 'seed_samples' ? false : complete, count, outcomes,
    mean: outcomes.reduce((sum, outcome) => sum + outcome.score * outcome.count, 0) / count,
    minimum: outcomes[0].score, maximum: outcomes.at(-1).score,
    p10: percentile(0.1), p50: percentile(0.5), p90: percentile(0.9) };
}

function validateDistribution(distribution) {
  if (!distribution || !Number.isSafeInteger(distribution.count) || distribution.count < 1 || !Array.isArray(distribution.outcomes)
    || !distribution.outcomes.length || distribution.outcomes.some(o => !Number.isFinite(o.score) || o.score < 0 || o.score > Number.MAX_SAFE_INTEGER || !Number.isSafeInteger(o.count) || o.count < 1)
    || distribution.outcomes.reduce((sum, o) => sum + o.count, 0) !== distribution.count) throw new Error('Invalid score distribution');
}

export function scoreThresholdProbability(distribution, threshold) {
  validateDistribution(distribution);
  if (!Number.isFinite(threshold) || threshold < 0) throw new Error('Invalid score threshold');
  return distribution.outcomes.reduce((count, o) => count + (o.score >= threshold ? o.count : 0), 0) / distribution.count;
}

export function scoreGradeProbabilities(distribution, thresholds) {
  validateDistribution(distribution);
  if (!Array.isArray(thresholds) || !thresholds.length || thresholds.some((r, i) => !Number.isSafeInteger(r.rank)
    || !Number.isSafeInteger(r.score) || (i ? r.rank <= thresholds[i - 1].rank || r.score <= thresholds[i - 1].score : r.score !== 0))) throw new Error('Invalid grade thresholds');
  return thresholds.map((row, i) => {
    const next = thresholds[i + 1]?.score ?? Infinity;
    const count = distribution.outcomes.reduce((sum, o) => sum + (o.score >= row.score && o.score < next ? o.count : 0), 0);
    return { ...row, count, probability: count / distribution.count, atLeastProbability: scoreThresholdProbability(distribution, row.score) };
  });
}
