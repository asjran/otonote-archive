// Website build adapter; production content tools call the shared server module directly.
import {fileURLToPath} from 'node:url';
import {loadSongRankingData as loadSharedRankingData} from '../../../packages/scoring/server/song-ranking-data.mjs';
export function loadSongRankingData(options) {
  return loadSharedRankingData({
    publicRoot: fileURLToPath(new URL('../../public/', import.meta.url)),
    cacheRoot: fileURLToPath(new URL('../../node_modules/.cache/song-rankings/', import.meta.url)),
    ...options,
  });
}
