import {currentServerContext, withServer} from './game-servers.mjs';

const flags = {'event-points':'eventPoints', music:'music', 'total-music':'totalMusic'};
export function eventRankingPath(event, board, musicId) {
  if (!flags[board] || event.ranking?.configured?.[flags[board]] !== true) return null;
  const params = new URLSearchParams({event:String(event.id), board});
  if (musicId != null) {
    if (board !== 'music' || !event.challengeSongs?.some(song => String(song.musicId) === String(musicId))) return null;
    params.set('music', String(musicId));
  }
  return '/rankings/?' + params;
}

export function installEventRankingLinks() {
  let server;
  try { server = currentServerContext().serverId; } catch { return; }
  for (const link of document.querySelectorAll('[data-player-ranking-link]')) {
    link.href = withServer(link.getAttribute('href'), server);
  }
}
