/** Presentation only: no game data or current-version request is needed. */
export function loadingKind(pathname) {
  const path = pathname.replace(/^\/global\/(zh-CN|en)(?=\/|$)/, '').replace(/\/+$/, '') || '/';
  if (path === '/') return 'home';
  if (/^\/stories\/episodes\//.test(path)) return 'story';
  if (/^\/(cards\/(members|supports)|characters|music)\/[^/]+$/.test(path) && path !== '/music/bgm') return 'detail';
  if (/^\/cards\/(members|supports)$/.test(path) || /^\/(characters|catalog|comics|stamps|profile-decorations)$/.test(path)) return 'cards';
  if (/^\/music(?:\/bgm)?$/.test(path)) return 'music';
  if (/^\/(immersive|tools\/live2d)(\/|$)/.test(path)) return 'scene';
  if (path.startsWith('/tools/')) return 'tool';
  return 'list';
}
