// Server/build-only. Visitors receive the finished ranking, never a calculator.
import { readFile, writeFile, mkdir, rename, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { calculateRankingRow, SONG_RANKING_BENCHMARK } from './song-ranking.mjs';
import { scoringRulesAvailable } from './scoring-release-gate.mjs';

const defaultSource = fileURLToPath(new URL('./', import.meta.url));
const pending = new Map();

export async function loadSongRankingData({ rules, releaseId, tracks, charts, sourceRoot = defaultSource,
  publicRoot = resolve(sourceRoot, '../../public'), cacheRoot = resolve(sourceRoot, '../../node_modules/.cache/song-rankings') }) {
  if (!scoringRulesAvailable(rules, releaseId)) throw new Error('排行榜规则尚未通过当前版本核验');
  const hash = createHash('sha256');
  hash.update(JSON.stringify({ rules, tracks, charts, benchmark: SONG_RANKING_BENCHMARK }));
  const scoringRoot = join(sourceRoot, 'scoring-rules');
  for (const filename of (await readdir(scoringRoot)).filter(name => name.endsWith('.mjs')).sort()) hash.update(await readFile(join(scoringRoot, filename)));
  hash.update(await readFile(join(sourceRoot, 'song-ranking.mjs')));
  const prepared = [];
  // Retain only identities and digests. Hundreds of parsed charts plus their
  // source strings exceed the production updater's memory allowance.
  for (const summary of charts) {
    const relative = String(summary.analysisDataUrl ?? '').replace(/^\/+/, '');
    const path = resolve(publicRoot, relative);
    if (!relative || !path.startsWith(resolve(publicRoot) + '/')) throw new Error('无效的排行榜谱面路径');
    const raw = await readFile(path, 'utf8');
    const chart = JSON.parse(raw);
    if (chart.id !== summary.id || chart.trackId !== summary.trackId || chart.difficulty !== summary.difficulty ||
      chart.sourceReleaseId && chart.sourceReleaseId !== releaseId) throw new Error(`谱面版本不一致：${summary.id}`);
    hash.update(raw);
    prepared.push({path, summary, sha256:createHash('sha256').update(raw).digest('hex')});
  }
  const fingerprint = hash.digest('hex');
  if (pending.has(fingerprint)) return pending.get(fingerprint);
  const job = (async () => {
    const cacheFile = join(cacheRoot, `${fingerprint}.json`);
    try {
      const cached = JSON.parse(await readFile(cacheFile, 'utf8'));
      if (cached.fingerprint === fingerprint && ['ordinary', 'gekisou'].every(mode => cached[mode]?.length === charts.length)) return cached;
    } catch { /* Missing or damaged cache is regenerated from the bound inputs. */ }
    const byId = new Map(tracks.map(track => [track.id, track]));
    const data = { sourceReleaseId: releaseId, ruleSetVersion: rules.ruleSetVersion, fingerprint,
      benchmark: SONG_RANKING_BENCHMARK, ordinary: [], gekisou: [] };
    for (const {path,summary,sha256} of prepared) {
      const raw = await readFile(path,'utf8');
      if (createHash('sha256').update(raw).digest('hex') !== sha256) throw new Error(`谱面在计算期间发生变化：${summary.id}`);
      const chart = {...summary,...JSON.parse(raw),sourceReleaseId:releaseId};
      for (const mode of ['ordinary', 'gekisou']) {
        data[mode].push(calculateRankingRow({ rules, chart, track: byId.get(chart.trackId), mode }));
      }
    }
    await mkdir(cacheRoot, { recursive: true });
    const temp = `${cacheFile}.${process.pid}.tmp`;
    await writeFile(temp, JSON.stringify(data)); await rename(temp, cacheFile);
    return data;
  })();
  pending.set(fingerprint, job);
  try { return await job; } catch (error) { pending.delete(fingerprint); throw error; }
}
