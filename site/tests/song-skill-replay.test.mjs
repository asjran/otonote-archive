import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { calculateSongSkillReplay } from '../src/lib/song-skill-replay.mjs';
import { withSongSkillReplay } from '../src/lib/song-ranking-replay-result.mjs';
import { songRankingReplaySource } from '../src/lib/song-ranking-replay-input.mjs';
import { compareSongSkills, songSkillProfileKey } from '../src/lib/song-skill-profile.mjs';
import { calculateRankingRow } from '../src/lib/song-ranking.mjs';
import { songGradeReference } from '../src/lib/song-grade-ranking.mjs';
import { rankSongRows } from '../src/lib/song-ranking-view.mjs';
import { songRankingMeta } from '../src/lib/song-ranking-meta.mjs';

const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const chart = { ...JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10000103.json', import.meta.url))), sourceReleaseId: rules.sourceReleaseId };
const skills = Array.from({ length: 5 }, () => ({ percent: 100, seconds: 5 }));
const track = { id: chart.trackId, title: 'test', bandIds: [], bandLabels: [] };
function fixture(ticks) {
  const r = structuredClone(rules);
  Object.assign(r.tables.LiveMusicScore.find(score => score._id === 10000103), { _musicScoreLevel: 5, _fullComboCount: ticks.length });
  r.tables.LiveComboScoreBonus = [];
  const c = { ...chart, bpmEvents: [{ tick: 0, bpm: 125 }], feverRanges: [], gekisouRanges: [],
    skillTimings: [0, 10, 20, 30, 40], duration: 45,
    notes: ticks.map((tick, index) => ({ id: `tap-${index}`, type: 'tap', tick })) };
  return { r, c };
}

test('candidate replay equals published ordinary benchmark for the same five fixed skills', () => {
  const replay = calculateSongSkillReplay({ rules, chart, skills });
  const baseline = calculateRankingRow({ rules, chart, track });
  assert.equal(replay.distribution.mean, baseline.expectedScore);
  assert.equal(replay.baseScore, baseline.baseScore);
  assert.deepEqual(replay.distribution.outcomes, [{ score: baseline.expectedScore, count: 120 }]);
  assert.equal(replay.distribution.kind, 'skill_orders');
});

test('asymmetric windows keep all 120 probabilities and independently known extreme orders', () => {
  const { r, c } = fixture(Array.from({ length: 5 }, (_, i) => Array.from({ length: i + 1 }, (_, j) => i * 10000 + (j + 1) * 100)).flat());
  const profile = skills.map((skill, i) => ({ ...skill, percent: (i + 1) * 100 }));
  const result = calculateSongSkillReplay({ rules: r, chart: c, skills: profile });
  // Fifteen taps each give 20,000 points; the five windows contain 1..5 taps.
  // Rearrangement inequality gives weighted gains 35 and 55, average 45.
  assert.equal(result.baseScore, 300000);
  assert.equal(result.distribution.mean, 1200000);
  assert.equal(result.distribution.minimum, 1000000);
  assert.equal(result.distribution.maximum, 1400000);
  assert.deepEqual(result.bestOrder, [0, 1, 2, 3, 4]);
  assert.deepEqual(result.worstOrder, [4, 3, 2, 1, 0]);
  assert.equal(result.distribution.count, 120);
});

test('130 percent replay retains native quantization and differs from the linear window estimate', () => {
  const { r, c } = fixture([0, 4999, 5000]);
  const profile = skills.map(skill => ({ ...skill, percent: 130 }));
  const baseline = { ...calculateRankingRow({ rules: r, chart: c, track }), benchmark: { power: 100000 } };
  const result = calculateSongSkillReplay({ rules: r, chart: c, skills: profile });
  assert.equal(compareSongSkills(baseline, profile).distribution.mean, 560000);
  // Native commands floor float32(1.3) at 1/100000; each boosted tap is 229,999.
  assert.equal(result.distribution.mean, 559998);
  assert.equal(result.distribution.minimum, result.distribution.maximum);
  const none = calculateSongSkillReplay({ rules: r, chart: c, skills: skills.map(() => ({ percent: 0, seconds: 0 })) });
  assert.equal(none.distribution.mean, 300000);
});

test('replay results bind to chart, release, power and frame/skill input; grade view uses the same mean', () => {
  const { r, c } = fixture([0, 4999, 5000]);
  const profile = skills.map(skill => ({ ...skill, percent: 130 }));
  const result = calculateSongSkillReplay({ rules: r, chart: c, skills: profile, frameRate: 120 });
  const row = { ...calculateRankingRow({ rules: r, chart: c, track }), benchmark: { power: 100000 },
    replaySource: { releaseId: r.sourceReleaseId }, gradeReferences: { global: { verified: true,
      thresholds: Array.from({ length: 6 }, (_, i) => ({ rank: i + 2, score: i * 100000 })) } } };
  const replayed = withSongSkillReplay(row, result);
  assert.equal(replayed.expectedScore, result.distribution.mean);
  assert.equal(songGradeReference(replayed, { profile: 'custom', skills: profile }).benchmarkScore, result.distribution.mean);
  assert.notEqual(songSkillProfileKey(profile, 60), result.profileKey);
  for (const wrong of [{ ...result, mode: 'gekisou' }, { ...result, chartId: 'another' },
    { ...result, sourceReleaseId: 'another' }, { ...result, power: 1 }, { ...result, modelVersion: 'old' }]) {
    assert.throws(() => withSongSkillReplay(row, wrong), /不一致/);
  }
  assert.throws(() => calculateSongSkillReplay({ rules: r, chart: { ...c, sourceReleaseId: 'another' }, skills }), /不一致/);
  assert.throws(() => calculateSongSkillReplay({ rules: r, chart: c, skills, frameRate: 30 }), /帧率/);
});

test('worker inputs use checked records from a single immutable edition snapshot', () => {
  const releaseId = 'global-release', row = { sourceEdition: 'global', sourceId: 'chart-1' };
  const record = path => ({ path, sha256: 'a'.repeat(64) });
  const manifest = { contentReleaseId: releaseId, region: 'global', root: `/content/releases/${'a'.repeat(24)}/`,
    locales: { 'zh-CN': { files: { 'projection/music-charts/chart-1.json': record('chart.json'), 'supplemental/formal-scoring-rules.json': record('rules.json') } } } };
  const source = songRankingReplaySource(manifest, row, 'zh-CN', releaseId);
  assert.equal(source.chart.url, manifest.root + 'chart.json');
  assert.equal(source.rules.sha256, 'a'.repeat(64));
  assert.equal(songRankingReplaySource(manifest, row, 'zh-CN', 'new-release'), null);
  assert.equal(songRankingReplaySource(manifest, { ...row, sourceEdition: 'jp' }, 'zh-CN', releaseId), null);
  for (const path of ['../chart.json', '/chart.json', 'a/../chart.json', 'chart.json?x=1', 'https://other/chart.json']) {
    manifest.locales['zh-CN'].files['projection/music-charts/chart-1.json'].path = path;
    assert.equal(songRankingReplaySource(manifest, row, 'zh-CN', releaseId), null);
  }
});

test('song metadata counts reconstructed scoring events and filters use the selected duration basis', () => {
  const events = [{ timeMs: 0, kind: 'authored' }, { timeMs: 0, kind: 'slide-combo' }, { timeMs: 1000, kind: 'authored' }];
  const meta = songRankingMeta({ duration: 2, bpmEvents: [{ bpm: 120 }, { bpm: 180 }] }, { events, skillTimes: [0, 1, 2, 3, 4] });
  assert.equal(meta.averageDensity, 1.5); assert.equal(meta.peakDensity, 2); assert.equal(meta.peakStart, 0);
  assert.equal(meta.simultaneousEvents, 2); assert.equal(meta.generatedEvents, 1);
  const rows = [{ id: 'a', title: 'A', level: 20, expectedScore: 10, chartSeconds: 90, audioSeconds: 110 },
    { id: 'b', title: 'B', level: 25, expectedScore: 20, chartSeconds: 100, audioSeconds: null }];
  assert.deepEqual(rankSongRows(rows, { maxLevel: '20', maxSeconds: '100' }).map(row => row.id), ['a']);
  assert.deepEqual(rankSongRows(rows, { maxLevel: 'all', maxSeconds: '100', durationBasis: 'audio' }), []);
  assert.deepEqual(rankSongRows(rows, { maxLevel: 'all', maxSeconds: 'all' }).map(row => row.id), ['b', 'a']);
});
