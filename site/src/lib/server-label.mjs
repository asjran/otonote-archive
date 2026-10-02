import {GAME_SERVERS} from './game-servers.mjs';

// Self-contained so the same function can run inline before the first paint,
// and against a detached document before the client renderer installs it.
export function restoreServerLabels(doc, servers) {
  const region = location.pathname.match(/^\/(jp|global)\//)?.[1] ?? 'global';
  const params = new URLSearchParams(location.search);
  let id = params.get('server');
  if (!params.has('server')) {
    try { id = localStorage.getItem(`ournotes:server:${region}`); } catch {}
    if (region === 'jp') id = 'jp';
  }
  const server = servers.find(item => item.id === id && item.region === region);
  const english = doc.documentElement.lang === 'en';
  for (const switcher of doc.querySelectorAll('.context-switcher')) {
    const label = switcher.querySelector('summary > span');
    if (label) label.textContent = server ? (english ? server.englishLabel : server.label)
      : (english ? 'Global · Select server' : '国际服 · 未选区服');
    for (const link of switcher.querySelectorAll('[data-game-server]')) {
      if (server && link.dataset.gameServer === server.id) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    }
  }
}

export const serverLabelScript = `(${restoreServerLabels.toString()})(document,${JSON.stringify(GAME_SERVERS)});`;
