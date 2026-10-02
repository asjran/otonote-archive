import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import { loadSongRankingData } from '../packages/scoring/server/song-ranking-data.mjs';
const rules = JSON.parse(await readFile(new URL('../packages/scoring/data/formal-scoring-rules.json', import.meta.url)));
const catalog = JSON.parse(await readFile(new URL('../site/src/data/generated/catalog.json', import.meta.url)));
const tracks = catalog.musicTracks.map(t => ({ id: t.id, title: t.title, bandIds: t.bandIds,
  bandLabels: t.bandLabels, musicTypeLabel: t.musicTypeLabel, audioDuration: t.audioDuration }));
const charts = catalog.musicCharts.map(c => ({ id: c.id, trackId: c.trackId, difficulty: c.difficulty,
  duration: c.duration, analysisDataUrl: c.analysisDataUrl }));
const data = await loadSongRankingData({ rules, releaseId: catalog.release.id, tracks, charts,
  publicRoot:fileURLToPath(new URL('../site/public/',import.meta.url)),
  cacheRoot:fileURLToPath(new URL('../site/node_modules/.cache/song-rankings/',import.meta.url)) });
console.log(JSON.stringify({ ordinary: data.ordinary.length, gekisou: data.gekisou.length, fingerprint: data.fingerprint }));
