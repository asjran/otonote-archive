import {gameServer} from './game-servers.mjs';
export function pageEditionHref(pathname, search, targetRegion, locale, counterpart) {
  const route = pathname.replace(/^\/(jp|global)\/(?:zh-CN|en)/, '');
  const params = new URLSearchParams(search);
  for (const key of ['server','page','cursor','detail','unavailable']) params.delete(key);
  params.set('view', 'page');
  let target = route;
  const detail = route.match(/^\/(events|recruitment)\/[^/]+\/?$/);
  if (detail && !pathname.startsWith(`/${targetRegion}/`)) {
    target = counterpart ?? `/${detail[1]}/`;
    if (!counterpart) params.set('unavailable', route);
  }
  return `/${targetRegion}/${locale}${target}?${params}`;
}
export function rankingServerHref(pathname, search, serverId) {
  const server = gameServer(serverId);
  if (!server) throw new Error('未知区服');
  const params = new URLSearchParams(search);
  for (const name of ['cursor','page','event','season','music']) params.delete(name);
  params.set('server',serverId); params.set('view','page');
  return pathname.replace(/^\/(jp|global)\//,`/${server.region}/`) + '?' + params;
}
