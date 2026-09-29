/** Both tasks start immediately. A failed task never leaves an unhandled rejection. */
export async function loadPageInputs(loadContent, loadRoute) {
  const [content, route] = await Promise.all([loadContent(), loadRoute()]);
  return {content, route};
}

export function loadStylesheet(href, document, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    const finish = error => {
      clearTimeout(timer);
      link.onload = link.onerror = null;
      if (error) { link.remove(); reject(error); } else resolve(link);
    };
    const timer = setTimeout(() => finish(new Error('样式加载超时 / Stylesheet timed out')), timeoutMs);
    link.onload = () => finish();
    link.onerror = () => finish(new Error('样式暂时无法加载 / Stylesheet unavailable'));
    document.head.append(link);
  });
}
