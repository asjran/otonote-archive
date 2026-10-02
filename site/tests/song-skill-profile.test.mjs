import test from 'node:test';
import assert from 'node:assert/strict';
import { compareSongSkills, withSongSkillProfile } from '../src/lib/song-skill-profile.mjs';
import { songGradeReference } from '../src/lib/song-grade-ranking.mjs';
import { rankSongRows, rankingMetrics } from '../src/lib/song-ranking-view.mjs';

const row = { id: 'a', title: 'A', difficulty: 'expert', level: 20, baseScore: 100, chartSeconds: 100, benchmark: { power: 100000 },
  skillReference: { version: 'ournotes-skill-windows-v2', power: 100000, gainsByPosition: [1, 2, 3, 4, 5].map(weight => Array.from({ length: 41 }, (_, i) => i * weight)) },
  gradeReferences: { global: { verified: true, thresholds: [2, 3, 4, 5, 6, 7].map((rank, i) => ({ rank, score: i * 100 })) } } };
const blank = () => Array.from({ length: 5 }, () => ({ percent: 0, seconds: 0 }));

test('one active skill visits each position 24 times; independent duration affects only its window', () => {
  const skills = blank(); skills[0] = { percent: 100, seconds: .5 };
  const result = compareSongSkills(row, skills);
  assert.deepEqual(result.distribution.outcomes, [1, 2, 3, 4, 5].map(gain => ({ score: 100 + gain, count: 24 })));
  assert.equal(result.distribution.mean, 103); assert.equal(result.distribution.p10, 101);
  assert.deepEqual(result.positionContributions, [.2, .4, .6, .8, 1]);
  skills[0].seconds = 1;
  assert.equal(compareSongSkills(row, skills).distribution.mean, 106);
  skills.reverse(); assert.equal(compareSongSkills(row, skills).distribution.mean, 106);
});

test('five independent skills keep all permutations including equivalent outcomes', () => {
  const skills = Array.from({ length: 5 }, (_, i) => ({ percent: (i + 1) * 100, seconds: .5 }));
  const result = compareSongSkills(row, skills);
  // Rearrangement inequality: 1*5+2*4+3*3+4*2+5*1 = 35; squares sum to 55.
  assert.equal(result.distribution.minimum, 135); assert.equal(result.distribution.maximum, 155);
  assert.equal(result.distribution.count, 120); assert.ok(Math.abs(result.distribution.mean - 145) < 1e-10);
  const same = compareSongSkills(row, skills.map(() => ({ percent: 100, seconds: .5 })));
  assert.deepEqual(same.distribution.outcomes, [{ score: 115, count: 120 }]);
  assert.equal(same.distribution.kind, 'linear_reference');
});

test('missing or mismatched window data does not borrow a baseline result', () => {
  const skills = blank(); skills[0] = { percent: 50, seconds: 5 };
  assert.equal(compareSongSkills({ ...row, skillReference: null }, skills), null);
  assert.equal(compareSongSkills({ ...row, benchmark: { power: 1 } }, skills), null);
  assert.equal(withSongSkillProfile({ ...row, skillReference: null }, skills).expectedScore, null);
  assert.equal(compareSongSkills({ ...row, skillReference: null }, blank()).distribution.mean, 100);
  assert.throws(() => compareSongSkills(row, skills.slice(1)));
  for (const bad of [{ percent: NaN, seconds: 5 }, { percent: 1001, seconds: 5 }, { percent: 20, seconds: 5.1 }]) assert.throws(() => compareSongSkills(row, [bad, ...skills.slice(1)]));
});

test('score, efficiency and grade reference share the same five-skill input without mutating source', () => {
  const skills = blank(); skills[0] = { percent: 100, seconds: .5 };
  const original = structuredClone(row), r = withSongSkillProfile(row, skills);
  assert.equal(r.expectedScore, 103); assert.equal(r.p10Score, 101);
  assert.equal(rankingMetrics(r, { overhead: 3 }).efficiency, 1);
  const grade = songGradeReference(row, { profile: 'custom', skills, targetRank: 3 });
  assert.equal(grade.benchmarkScore, r.expectedScore); assert.equal(grade.requiredPower, 10000000 / 103);
  assert.deepEqual(row, original);
});

test('overhead can change efficiency order and never fills in unknown audio length', () => {
  const short = { ...row, id: 'short', expectedScore: 100, chartSeconds: 10 };
  const long = { ...row, id: 'long', expectedScore: 150, chartSeconds: 20 };
  assert.equal(rankSongRows([short, long], { metric: 'efficiency' })[0].id, 'short');
  assert.equal(rankSongRows([short, long], { metric: 'efficiency', overhead: 20 })[0].id, 'long');
  assert.equal(rankingMetrics(row, { durationBasis: 'audio', overhead: 20 }).efficiency, null);
  for (const overhead of [-1, NaN, Infinity, 3601]) assert.throws(() => rankingMetrics(row, { overhead }));
});
