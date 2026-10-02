/** Website identities, deliberately independent of SDK server numbers and UI language. */
export const GAME_SERVERS = Object.freeze([
  {id:'jp', region:'jp', label:'日服', englishLabel:'Japan'},
  {id:'global-hmt', region:'global', label:'港澳台', englishLabel:'Hong Kong / Macao / Taiwan'},
  {id:'global-kr', region:'global', label:'韩服', englishLabel:'Korea'},
  {id:'global-en', region:'global', label:'EN', englishLabel:'EN'}
]);
export function gameServer(id) { return GAME_SERVERS.find(server => server.id === id); }
export function resolveServer(region, search = '', storage) {
  if (!['jp','global'].includes(region)) throw new Error('未知游戏版本');
  const params = new URLSearchParams(search);
  if (params.has('server')) {
    const server = gameServer(params.get('server'));
    if (!server || server.region !== region) throw new Error('链接的区服与游戏版本不匹配');
    return server.id;
  }
  if (region === 'jp') return 'jp';
  try { const saved = gameServer(storage?.getItem(`ournotes:server:${region}`)); if (saved?.region === region) return saved.id; } catch {}
  return null;
}
export function currentServerContext() {
  const region = globalThis.location?.pathname?.match(/^\/(jp|global)\//)?.[1] ?? 'global';
  let storage; try { storage = globalThis.localStorage; } catch {}
  return {region, serverId:resolveServer(region, globalThis.location?.search ?? '', storage)};
}
export function scopedStorageKey(kind, releaseId = '') {
  const {region, serverId} = currentServerContext();
  return `ournotes:${kind}:${region}:${serverId ?? 'unselected'}${releaseId ? ':' + releaseId : ''}`;
}
export function serverSearchParams(params, context = currentServerContext()) {
  const result = new URLSearchParams(params);
  if (context.serverId) result.set('server', context.serverId);
  return result;
}
export function withServer(path, serverId) {
  if (!serverId) return path;
  const url = new URL(path, 'https://ournotes.invalid');
  const region = url.pathname.match(/^\/(jp|global)\//)?.[1];
  if (gameServer(serverId)?.region === region) url.searchParams.set('server', serverId);
  return url.pathname + url.search + url.hash;
}
export function assertAccountServer(serverId, context = currentServerContext()) {
  if (!context.serverId) throw new Error('请先选择账号所属区服');
  if (!gameServer(serverId) || serverId !== context.serverId) throw new Error('资料区服与当前区服不匹配');
}
