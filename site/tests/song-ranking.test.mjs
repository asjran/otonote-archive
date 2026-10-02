import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mkdtemp, writeFile, rm, mkdir, cp, copyFile, appendFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { calculateRankingRow, SONG_RANKING_BENCHMARK, rankingMetrics, rankSongRows } from '../src/lib/song-ranking.mjs';
import { loadSongRankingData } from '../src/lib/song-ranking-data.mjs';
import { createGekisouSongCalculator } from '../src/lib/scoring-rules/gekisou-song-score.mjs';
import { gekisouRankingBonus } from '../src/lib/scoring-rules/gekisou-rules.mjs';
import {prepareFormalChart} from '../src/lib/scoring-rules/formal-song-score.mjs';
import {buildSkillWindowReference} from '../src/lib/song-skill-windows.mjs';
const rules = JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json', import.meta.url)));
const loadChart = id => ({ ...JSON.parse(readFileSync(new URL(`../public/data/music-charts/music-chart-${id}.json`, import.meta.url))), sourceReleaseId: rules.sourceReleaseId });
const chart = loadChart('10000103');
const track = { id: chart.trackId, title: '迷星叫', bandIds: ['band-1'], bandLabels: ['MyGO!!!!!'], audioDuration: 100 };
function simpleChart() {
  const r = structuredClone(rules);
  r.tables.LiveMusicScore.find(s => s._id === 10000103)._musicScoreLevel = 5;
  r.tables.LiveComboScoreBonus = [];
  return { r, c: { ...chart, feverRanges: [], gekisouRanges: [], bpmEvents: [{ tick: 0, bpm: 125 }], duration: 45,
    skillTimings: [0, 10, 20, 30, 40], notes: [0, 4999, 5000].map((tick, id) => ({ id: `tap-${id}`, type: 'tap', tick })) } };
}
test('fixed neutral baseline has independently calculable score; no visitor configuration', () => {
  const { r, c } = simpleChart();
  const result = calculateRankingRow({ rules: r, chart: c, track });
  assert.equal(result.baseScore, 300000); assert.equal(result.expectedScore, 500000);
  assert.equal(result.minimumScore, 500000); assert.equal(result.maximumScore, 500000);
  assert.equal(result.skillMultiplier, 5 / 3); assert.equal(result.scoreMultiplier, 5);
  assert.equal(result.comboFactor, 1); assert.equal(result.power, 100000);
  assert.equal(calculateRankingRow({ rules: r, chart: c, track, settings: { power: 1 }, draft: { slots: [] } }).expectedScore, 500000);
  assert.throws(() => { SONG_RANKING_BENCHMARK.power = 1; }, TypeError);
});
test('precomputed skill windows include starts, exclude ends and add overlapping activations',()=>{
 const {r,c}=simpleChart();
 const reference=buildSkillWindowReference(r,prepareFormalChart(r,c));
 assert.equal(reference.gains[0],0);
 assert.equal(reference.gains[10],200000);
 assert.equal(reference.gains[11],300000);
 assert.deepEqual(reference.gainsByPosition.map(values=>values[10]),[200000,0,0,0,0]);
 assert.deepEqual(reference.gainsByPosition.map(values=>values[11]),[300000,0,0,0,0]);
 assert.deepEqual(reference.startsSeconds,[0,10,20,30,40]);
 c.skillTimings=[0,1,2,3,4];
 assert.equal(buildSkillWindowReference(r,prepareFormalChart(r,c)).gains[10],1000000);
});
test('overlapping fixed skills add; reference results ignore song band and attribute affinity', () => {
  const { r, c } = simpleChart(); c.skillTimings = [0, 1, 2, 3, 4];
  assert.equal(calculateRankingRow({ rules: r, chart: c, track }).expectedScore, 1300000);
  const a = calculateRankingRow({ rules, chart, track });
  const changed = structuredClone(rules); const music = changed.tables.LiveMusic.find(m => `music-${m._id}` === track.id);
  music._musicType = 99; music._bestMusicTagIDs = [];
  const b = calculateRankingRow({ rules: changed, chart, track });
  assert.equal(a.expectedScore, b.expectedScore); assert.equal(a.power, b.power);
});
test('different difficulties retain their own factors and score denominator', () => {
  const easy = calculateRankingRow({ rules, chart: loadChart('10000100'), track });
  const expert = calculateRankingRow({ rules, chart, track });
  assert.equal(expert.difficultyFactor, Math.fround(1.1)); assert.ok(easy.difficultyFactor < expert.difficultyFactor);
  assert.notEqual(easy.convertedNoteCount, expert.convertedNoteCount);
});
test('higher total score can rank below a shorter chart on efficiency; filtering is independent', () => {
  const rows = [{ id: 'a', title: 'Ａ', difficulty: 'expert', level: 25, bands: ['b'], expectedScore: 1200000, chartSeconds: 120 },
    { id: 'b', title: 'B', difficulty: 'hard', level: 20, bands: ['b'], expectedScore: 1100000, chartSeconds: 90 }];
  assert.deepEqual(rankSongRows(rows).map(r => r.id), ['a', 'b']);
  assert.deepEqual(rankSongRows(rows, { metric: 'efficiency' }).map(r => r.id), ['b', 'a']);
  assert.equal(rankSongRows(rows, { query: 'a' })[0].id, 'a');
  assert.equal(rankSongRows(rows, { difficulty: 'hard', band: 'b' })[0].id, 'b');
});
test('missing audio is unranked; ties use unrounded values and stable ids', () => {
  const rows = ['b', 'a', 'c', 'd'].map((id, i) => ({ id, title: id, level: 20, expectedScore: i < 2 ? 100.001 : 100,
    chartSeconds: 100, audioSeconds: id === 'd' ? null : 10 }));
  assert.deepEqual(rankSongRows(rows).map(r => [r.id, r.rank]), [['a', 1], ['b', 1], ['c', 3], ['d', 3]]);
  assert.deepEqual(rankSongRows(rows, { metric: 'efficiency', durationBasis: 'audio' }).map(r => r.rank), [1, 1, 3, null]);
  assert.equal(rankingMetrics(rows[3], { durationBasis: 'audio' }).efficiency, null);
});
test('LUCK baseline is repeatable, has no card effects, and does not claim optimizer eligibility', () => {
  const c = loadChart('10003803');
  const options = { rules, chart: c, track: { ...track, id: c.trackId }, mode: 'gekisou' };
  assert.deepEqual(calculateRankingRow(options), calculateRankingRow(options));
  const result = createGekisouSongCalculator(rules, c, { referenceProfile: SONG_RANKING_BENCHMARK, scenario: SONG_RANKING_BENCHMARK.scenario })
    .calculate({ selectedSongId: c.trackId, selectedDifficulty: c.difficulty });
  assert.equal(result.power, 100000); assert.deepEqual(result.effects, []); assert.equal(result.optimizerEligible, false);
  assert.equal(result.sampleCount, 240); assert.ok(Number.isFinite(result.standardError));
});
test('Gekisou uses the same power/ordinary skills and separately calculates section reward rates', () => {
  const row = calculateRankingRow({ rules, chart, track, mode: 'gekisou' });
  const ordinary = calculateRankingRow({ rules, chart, track });
  assert.equal(row.gekisouMultiplier, row.expectedScore / ordinary.expectedScore); assert.equal(row.power, ordinary.power);
  for (const s of row.sections) assert.equal(s.rankingPercent, gekisouRankingBonus(rules, {
    missions: row.sections.map(x => x.missionType), sectionIndex: s.index, rank: 1, sectionScore: 0
  }).percent);
});
test('cache invalidates on bound chart bytes; release mismatch is blocked', async () => {
  const root = await mkdtemp(join(tmpdir(), 'song-rankings-'));
  try {
    await writeFile(join(root, 'chart.json'), JSON.stringify(chart));
    const input = { rules, releaseId: rules.sourceReleaseId, tracks: [track], charts: [{ id: chart.id, trackId: track.id, difficulty: chart.difficulty, analysisDataUrl: '/chart.json' }], publicRoot: root, cacheRoot: join(root, 'cache') };
    const a = await loadSongRankingData(input), b = await loadSongRankingData(input);
    assert.equal(a.fingerprint, b.fingerprint); assert.equal(a.ordinary.length, 1); assert.equal(a.gekisou.length, 1);
    await writeFile(join(root, 'chart.json'), JSON.stringify({ ...chart, duration: chart.duration + 2 }));
    const changed = await loadSongRankingData(input);
    assert.notEqual(changed.fingerprint, a.fingerprint); assert.equal(changed.ordinary[0].chartSeconds, chart.duration + 2);
    await assert.rejects(loadSongRankingData({ ...input, releaseId: 'other' }), /版本/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('ranking cache invalidates when a transitive scoring helper changes', async () => {
  const root = await mkdtemp(join(tmpdir(), 'song-ranking-source-'));
  try {
    const sourceRoot = join(root, 'source');
    await mkdir(sourceRoot);
    await cp(new URL('../../packages/scoring/scoring-rules/', import.meta.url), join(sourceRoot, 'scoring-rules'), {recursive:true});
    for (const name of ['song-ranking.mjs','song-ranking-meta.mjs','song-skill-windows.mjs',
      'song-ranking-view.mjs','scoring-engine.mjs','scoring-release-gate.mjs']) {
      await copyFile(new URL(`../../packages/scoring/${name}`, import.meta.url), join(sourceRoot, name));
    }
    await writeFile(join(root, 'chart.json'), JSON.stringify(chart));
    const input = {rules,releaseId:rules.sourceReleaseId,tracks:[track],charts:[{id:chart.id,
      trackId:track.id,difficulty:chart.difficulty,analysisDataUrl:'/chart.json'}],sourceRoot,
      publicRoot:root,cacheRoot:join(root,'cache')};
    const before = await loadSongRankingData(input);
    await appendFile(join(sourceRoot, 'scoring-engine.mjs'), '\n// Different bound helper revision.\n');
    const after = await loadSongRankingData(input);
    assert.notEqual(before.fingerprint, after.fingerprint);
    assert.equal((await loadSongRankingData(input)).fingerprint, after.fingerprint);
  } finally { await rm(root, {recursive:true,force:true}); }
});
