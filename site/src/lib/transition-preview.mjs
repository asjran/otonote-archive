export const transitionModes = [
  { id: 'fade', label: '原版淡入', description: '180ms · 新旧画面轻轻交叠' },
  { id: 'stage', label: '舞台换幕', description: '420ms · 酒红色斜切幕线，揭开下一场' },
  { id: 'book', label: '资料册翻页', description: '620ms · 沿装订边翻起旧页，露出下一页' },
  { id: 'beat', label: '节拍切片', description: '480ms · 三段错拍，从上到下依次切入' }
];

/** Preserve page filters, hashes and native navigation; only decorate document links. */
export function transitionPreviewHref(href, { mode, slow = false }, base) {
  if (!transitionModes.some(item => item.id === mode) || !href || href.startsWith('#')) return href;
  const url = new URL(href, base);
  if (url.origin !== new URL(base).origin || !['http:', 'https:'].includes(url.protocol)) return href;
  // Media/download links are not page navigation.
  if (/\.[a-z0-9]+$/i.test(url.pathname) && !/\.html?$/i.test(url.pathname)) return href;
  url.searchParams.set('transition', mode);
  if (slow) url.searchParams.set('transition-speed', 'slow');
  else url.searchParams.delete('transition-speed');
  return `${url.pathname}${url.search}${url.hash}`;
}
