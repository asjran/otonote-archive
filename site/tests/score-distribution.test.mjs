import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeScoreDistribution, scoreThresholdProbability, scoreGradeProbabilities } from '../src/lib/scoring-rules/score-distribution.mjs';

test('compression retains duplicate order mass and nearest-rank percentiles', () => {
  const scores = [...Array(12).fill(80), ...Array(96).fill(100), ...Array(12).fill(160)];
  const d = summarizeScoreDistribution(scores.reverse());
  assert.deepEqual(d.outcomes, [{ score: 80, count: 12 }, { score: 100, count: 96 }, { score: 160, count: 12 }]);
  assert.equal(d.count, 120); assert.equal(d.mean, 104);
  assert.equal(d.p10, 80); assert.equal(d.p50, 100); assert.equal(d.p90, 100);
  assert.equal(scoreThresholdProbability(d, 100), .9);
  assert.equal(scoreThresholdProbability(d, 161), 0);
  assert.deepEqual(scoreGradeProbabilities(d, [{ rank: 2, score: 0 }, { rank: 3, score: 100 }, { rank: 4, score: 160 }]).map(g => [g.count, g.probability, g.atLeastProbability]), [[12, .1, 1], [96, .8, .9], [12, .1, .1]]);
});

test('all-identical orders still count as 120 and finite seeds never claim completeness', () => {
  const d = summarizeScoreDistribution(Array(120).fill(42));
  assert.deepEqual(d.outcomes, [{ score: 42, count: 120 }]);
  assert.equal(d.p10, 42); assert.equal(d.mean, 42);
  const sample = summarizeScoreDistribution([10, 20], { kind: 'seed_samples', complete: false });
  assert.equal(sample.kind, 'seed_samples'); assert.equal(sample.complete, false);
  assert.equal(summarizeScoreDistribution([10,20],{kind:'seed_samples'}).complete,false);
});

test('rejects malformed or missing distributions rather than inventing probabilities', () => {
  for (const scores of [[], [-1], [NaN], [Infinity], [Number.MAX_SAFE_INTEGER + 1]]) assert.throws(() => summarizeScoreDistribution(scores));
  const d = summarizeScoreDistribution([0, 1]);
  assert.throws(() => scoreThresholdProbability({ ...d, count: 3 }, 1));
  assert.throws(() => scoreThresholdProbability(null, 1));
  assert.throws(() => scoreThresholdProbability(d, NaN));
  assert.throws(() => scoreGradeProbabilities(d, [{ rank: 2, score: 1 }]));
  assert.throws(() => scoreGradeProbabilities(d, [{ rank: 2, score: 0 }, { rank: 3, score: 0 }]));
});
