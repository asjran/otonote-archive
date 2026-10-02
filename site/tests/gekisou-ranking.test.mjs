import test from 'node:test';
import assert from 'node:assert/strict';
import { compareGekisouSection, rankGekisouSection, normalizeGekisouOpponents } from '../src/lib/scoring-rules/gekisou-ranking.mjs';
import { gekisouPreviousScoreFrameEnd, gekisouTimingCombo, gekisouInputFrame, gekisouScoreSection } from '../src/lib/scoring-rules/gekisou-timing.mjs';

const section = (overrides = {}) => ({ combo: 100, luckPoints: 200, just: 80, noteScore: 500000, perfectCount: 100, ...overrides });
test('native mission count outranks score, then score outranks Perfect count', () => {
  for (const [mission, key] of [[1, 'combo'], [2, 'luckPoints'], [3, 'just']]) {
    assert.equal(compareGekisouSection(section({[key]: 201, noteScore: 1}), section(), mission), -1);
    assert.equal(compareGekisouSection(section({noteScore: 500001, perfectCount: 1}), section(), mission), -1);
    assert.equal(compareGekisouSection(section({perfectCount: 101}), section(), mission), -1);
    assert.equal(compareGekisouSection(section(), section(), mission), 0);
  }
});
test('ranking section score subtracts whole 40 ms endpoint buckets, not note-ID membership', () => {
  const ranges=[{startMs:1001,endMs:2001}];
  // GetScoreAtTimeMs reads start first, then end, and subtracts the snapshots.
  assert.deepEqual([1000,1001,1040,1041,2000,2001,2040,2041].map(t=>gekisouScoreSection(ranges,t)),[-1,-1,-1,0,0,0,0,-1]);
});
test('native ties use dense groups, including exact ties with the player', () => {
  assert.equal(rankGekisouSection(section(), [section({combo: 101}), section({combo: 101}), section({combo: 99})], 1), 2);
  assert.equal(rankGekisouSection(section(), [section(), section({combo: 99})], 1), 1);
  assert.equal(rankGekisouSection(section(), [1,2,3,4].map(n=>section({combo:100+n})), 1), 5);
});
test('opponent input rejects incomplete, fractional, negative or oversized fields', () => {
  assert.deepEqual(normalizeGekisouOpponents(), []);
  const opponent = {sections:[section(),section(),section()]};
  assert.equal(normalizeGekisouOpponents([opponent])[0].sections[2].just, 80);
  for (const input of [[{}], Array(5).fill(opponent), [{sections:[section(),section()]}],
    [{sections:[section({noteScore:-1}),section(),section()]}],
    [{sections:[section({perfectCount:1.1}),section(),section()]}]]) assert.throws(()=>normalizeGekisouOpponents(input));
});
test('COMBO score interval boundary is previous ceil(float32(ms/40)) interval end', () => {
  assert.deepEqual([0,1,39,40,41,79,80,81].map(gekisouPreviousScoreFrameEnd), [-40,0,0,0,40,40,40,80]);
  const history = [{timeMs:39,combo:9},{timeMs:40,combo:10},{timeMs:40,combo:11},{timeMs:41,combo:12}];
  assert.equal(gekisouTimingCombo(history,40),0);
  assert.equal(gekisouTimingCombo(history,41),11);
  assert.equal(gekisouTimingCombo(history,80),11);
  assert.equal(gekisouTimingCombo(history,81),12);
  assert.equal(gekisouInputFrame(1000,0,60),60);
  assert.equal(gekisouInputFrame(1001,0,60),61);
  assert.equal(gekisouInputFrame(1001,30,60),62);
});
