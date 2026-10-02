import {currentServerContext} from './game-servers.mjs';
import {createRankingRow, validateHighScoreDeck} from './player-ranking-decks.mjs';

export const rankingBoards = ['event-points', 'music', 'total-music'];
const copy = {
  unavailable: ['该区服的此项榜单暂无数据', 'This board has no data for this server yet.'],
  empty: ['暂无排名记录', 'No ranking records yet.'],
  stale: ['数据已过期，以下为最后一次采集结果', 'Data has expired. Showing the last captured results.'],
  available: ['已加载最近采集的榜单', 'Latest captured rankings loaded.'],
};
const labels = {'event-points':['活动积分榜','Event points'], music:['单曲榜','Song'], 'total-music':['总歌曲榜','Total music']};

export function validateRankingResponse(data, server, board, event, music) {
  if (data?.schemaVersion !== 1 || data.serverId !== server
    || (board === 'auto' ? ![...rankingBoards, 'auto'].includes(data.board) : data.board !== board)
    || event && data.eventId !== event || music && data.musicId !== music
    || !Object.hasOwn(copy, data.status) || !Array.isArray(data.entries)
    || !Array.isArray(data.events) || !Array.isArray(data.songs)
    || data.boards !== undefined && (!Array.isArray(data.boards) || data.boards.some(id => !rankingBoards.includes(id)))) {
    throw Error('Invalid ranking response');
  }
  const ids = new Set();
  for (const row of data.entries) {
    if (typeof row?.playerId !== 'string' || !row.playerId || ids.has(row.playerId)
      || typeof row.name !== 'string' || !Number.isSafeInteger(row.rank) || row.rank < 1
      || !Number.isSafeInteger(row.score) || row.score < 0) throw Error('Invalid ranking entry');
    ids.add(row.playerId);
    validateHighScoreDeck(row.highScoreDeck);
  }
  for (const item of [...data.events, ...data.songs]) {
    if (typeof item?.id !== 'string' || typeof item.name !== 'string') throw Error('Invalid ranking option');
  }
  for (const stamp of [data.observedAt, data.expiresAt]) {
    if (stamp != null && (typeof stamp !== 'string' || !Number.isFinite(Date.parse(stamp)))) throw Error('Invalid ranking timestamp');
  }
  if (data.nextCursor != null && typeof data.nextCursor !== 'string') throw Error('Invalid ranking cursor');
  return data;
}

export function rankingStatus(data, now = Date.now()) {
  return data.status !== 'unavailable' && data.expiresAt && Date.parse(data.expiresAt) <= now ? 'stale' : data.status;
}

export function installPlayerRankings(root) {
  if (root.dataset.rankInstalled) return;
  root.dataset.rankInstalled = 'true';
  const en = root.dataset.locale === 'en', language = en ? 'en-US' : 'zh-CN';
  const q = selector => root.querySelector(selector);
  const status = q('[data-rank-status]'), rows = q('[data-rank-rows]');
  const empty = q('[data-rank-empty]');
  let cardCatalog = {};
  try {
    const value = JSON.parse(q('[data-rank-cards]')?.textContent || '{}');
    const region = location.pathname.split('/')[1];
    if (value.region === region) cardCatalog = value;
  } catch { /* Rankings remain usable without card artwork. */ }
  let server;
  try { server = currentServerContext().serverId; }
  catch { status.textContent = en ? 'Invalid server link. Choose a server.' : '区服链接不匹配，请重新选择区服。'; return; }
  for (const link of root.querySelectorAll('[data-ranking-server]')) {
    if (link.dataset.rankingServer === server) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
    if (!server) {
      const target = new URL(link.href, location.href);
      if (target.pathname === location.pathname) {
        const source = new URLSearchParams(location.search);
        for (const key of ['event', 'board', 'music']) if (source.has(key)) target.searchParams.set(key, source.get(key));
        link.href = target.href;
      }
    }
  }
  const event = q('[data-rank-event]'), board = q('[data-rank-board]'), song = q('[data-rank-song]');
  const next = q('[data-rank-next]'), retry = q('[data-rank-retry]'), refresh = q('[data-rank-refresh]');
  const params = new URLSearchParams(location.search);
  board.value = rankingBoards.includes(params.get('board')) ? params.get('board') : 'auto';
  let requestedEvent = params.get('event') || '', requestedMusic = params.get('music') || '';
  let pending, generation = 0, cursor = null, lastData = null, failedAppend = false;
  const seen = new Set();
  const options = (select, items, selected, placeholder) => {
    select.replaceChildren(...(items.length ? items : [{id:'',name:placeholder}]).map(item => {
      const option = document.createElement('option'); option.value = item.id; option.textContent = item.name; return option;
    }));
    select.value = selected ?? ''; select.disabled = !items.length;
  };
  const showStatus = () => {
    if (lastData) { const state = rankingStatus(lastData); status.textContent = copy[state][Number(en)]; status.dataset.state = state; }
  };
  async function load(append = false) {
    if (!server) return;
    pending?.abort(); pending = new AbortController(); const controller = pending, request = ++generation;
    let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 20000);
    const type = board.value || 'auto', eventId = requestedEvent, musicId = type === 'music' ? requestedMusic : '';
    const query = new URLSearchParams({server, board:type});
    if (eventId) query.set('event', eventId); if (musicId) query.set('music', musicId);
    if (append && cursor) query.set('cursor', cursor);
    if (!append) { rows.replaceChildren(); seen.clear(); cursor = null; lastData = null; }
    next.hidden = true; retry.hidden = true; if (refresh) refresh.disabled = true;
    status.textContent = en ? 'Loading…' : '正在加载…';
    status.dataset.state = 'loading'; rows.setAttribute('aria-busy', 'true'); if (empty) empty.hidden = true;
    q('[data-rank-song-label]').hidden = type !== 'music';
    if (!append) { q('[data-rank-time]').textContent = ''; if (q('[data-rank-count]')) q('[data-rank-count]').textContent = ''; }
    try {
      const response = await fetch('/api/v1/player-rankings?' + query, {signal:pending.signal, cache:'no-store'});
      if (request !== generation) return;
      if (response.status === 404) { lastData = null; status.textContent = copy.unavailable[Number(en)]; status.dataset.state = 'unavailable'; if (empty) empty.hidden = seen.size > 0; return; }
      if (append && response.status === 400) {
        cursor = null; failedAppend = false; lastData = null; retry.hidden = false;
        status.textContent = en ? 'The snapshot changed. Reload to see the new rankings.' : '榜单快照已更新，请重新加载查看最新排名。'; return;
      }
      if (!response.ok) throw Error('Request failed');
      const data = validateRankingResponse(await response.json(), server, type, eventId, musicId);
      if (request !== generation) return;
      lastData = data; showStatus();
      options(event, data.events, data.eventId, en ? 'No event data' : '暂无活动数据');
      options(song, data.songs, data.musicId, en ? 'No song data' : '暂无歌曲数据');
      const available = [...new Set([...(data.boards ?? rankingBoards), ...(rankingBoards.includes(data.board) ? [data.board] : [])])];
      options(board, available.map(id => ({id, name:labels[id][Number(en)]})), data.board, en ? 'No board data' : '暂无榜单数据');
      requestedEvent = data.eventId || ''; requestedMusic = data.musicId || '';
      q('[data-rank-song-label]').hidden = data.board !== 'music';
      q('[data-rank-time]').textContent = data.observedAt ? `${en ? 'Captured' : '采集时间'} ${new Date(data.observedAt).toLocaleString(language)}` : '';
      if (data.observedAt) q('[data-rank-time]').setAttribute('datetime', data.observedAt);
      else q('[data-rank-time]').removeAttribute('datetime');
      const scoreLabel = data.board === 'event-points' ? (en ? 'Points' : '活动积分') : (en ? 'Score' : '成绩');
      if (q('[data-rank-score-label]')) q('[data-rank-score-label]').textContent = scoreLabel;
      if (q('[data-rank-event-name]')) q('[data-rank-event-name]').textContent = data.events.find(item => item.id === data.eventId)?.name || '';
      if (q('[data-rank-song-name]')) q('[data-rank-song-name]').textContent = (data.board === 'music' ? data.songs.find(item => item.id === data.musicId)?.name : labels[data.board]?.[Number(en)]) || (en ? 'No board data yet' : '榜单暂未收录');
      for (const entry of data.entries) {
        if (seen.has(entry.playerId)) continue;
        seen.add(entry.playerId);
        rows.append(createRankingRow(entry, {en, catalog:cardCatalog, server, scoreLabel}));
      }
      if (empty) empty.hidden = seen.size > 0;
      if (q('[data-rank-count]')) q('[data-rank-count]').textContent = seen.size ? (en ? `${seen.size} / ${data.totalEntries ?? seen.size} players` : `${seen.size} / ${data.totalEntries ?? seen.size} 名玩家`) : '';
      cursor = data.nextCursor; next.hidden = !cursor;
      const url = new URL(location.href); url.searchParams.set('server', server);
      if (data.board !== 'auto') url.searchParams.set('board', data.board);
      for (const [key, value] of [['event', requestedEvent], ['music', data.board === 'music' ? requestedMusic : '']]) {
        value ? url.searchParams.set(key, value) : url.searchParams.delete(key);
      }
      history.replaceState(history.state, '', url);
    } catch (error) {
      if (request === generation && (error.name !== 'AbortError' || timedOut)) {
        lastData = null; failedAppend = append; retry.hidden = false;
        status.dataset.state = 'error';
        status.textContent = en ? 'Could not load rankings. Please try again.' : '榜单加载失败，请稍后重试。';
      }
    } finally {
      clearTimeout(timeout);
      if (request === generation) { if (refresh) refresh.disabled = false; rows.setAttribute('aria-busy', 'false'); }
    }
  }
  event.addEventListener('change', () => { requestedEvent = event.value; requestedMusic = ''; board.append(new Option('', 'auto')); board.value = 'auto'; load(); });
  board.addEventListener('change', () => { requestedMusic = ''; load(); });
  song.addEventListener('change', () => { requestedMusic = song.value; load(); });
  next.addEventListener('click', () => load(true)); retry.addEventListener('click', () => load(failedAppend));
  refresh?.addEventListener('click', () => load());
  let timer = setInterval(() => { if (root.isConnected) showStatus(); else clearInterval(timer); }, 30000);
  window.addEventListener('pagehide', () => { pending?.abort(); clearInterval(timer); }, {once:true});
  window.addEventListener('pageshow', event => { if (event.persisted && root.isConnected) { clearInterval(timer); timer = setInterval(showStatus, 30000); showStatus(); } });
  if (!server && refresh) refresh.disabled = true;
  load();
}

if (typeof document !== 'undefined') document.querySelectorAll('[data-player-rankings]').forEach(installPlayerRankings);
