/** Pick uniformly from available scenes, avoiding an immediate repeat. */
export function pickCatalogScene(scenes, previousId, random = Math.random) {
  const alternatives = scenes.filter(scene => scene.id !== previousId);
  const pool = alternatives.length ? alternatives : scenes;
  if (!pool.length) return undefined;
  const index = Math.min(pool.length - 1, Math.max(0, Math.floor(random() * pool.length)));
  return pool[index];
}

/** Keep the old paper on top while the already-decoded next page is revealed. */
export async function turnCatalogPage(page, commit, animate) {
  if (!animate || !page?.animate) {
    commit();
    return;
  }
  const sheet = page.cloneNode(true);
  sheet.removeAttribute('data-scene-page');
  sheet.className = 'gateway-turn-sheet';
  sheet.setAttribute('aria-hidden', 'true');
  sheet.inert = true;
  // Decorative copy must not duplicate live regions, IDs or application hooks.
  sheet.querySelectorAll('[id], [aria-live], [data-scene-image], [data-scene-title]').forEach(node => {
    for (const name of ['id', 'aria-live', 'data-scene-image', 'data-scene-title']) node.removeAttribute(name);
  });
  // A cloned <img> is not decoded just because its source image is visible.
  // Preparing it off-screen prevents a blank first frame over the next scene.
  try {
    await Promise.all(Array.from(sheet.querySelectorAll('img'), image => image.decode?.()));
  } catch {
    commit();
    return;
  }
  page.append(sheet);
  try {
    const view = page.ownerDocument?.defaultView;
    if (view?.requestAnimationFrame) {
      await new Promise(resolve => view.requestAnimationFrame(() => view.requestAnimationFrame(resolve)));
    }
    commit();
    const animation = sheet.animate([
      { transform: 'rotateY(0deg)', filter: 'brightness(1)', offset: 0 },
      { transform: 'rotateY(-12deg)', filter: 'brightness(.98)', offset: .16 },
      { transform: 'rotateY(-62deg)', filter: 'brightness(.85)', offset: .64 },
      { transform: 'rotateY(-103deg)', filter: 'brightness(.7)', offset: 1 }
    ], { duration: 900, easing: 'cubic-bezier(.3,.05,.2,1)', fill: 'forwards' });
    // Cancellation (for example when navigating away) must also release the lock.
    await animation.finished.catch(() => {});
  } finally {
    sheet.remove();
  }
}

export function initializeCatalogScene(element) {
  if (element.dataset.initialized) return;
  element.dataset.initialized = 'true';
  let image = element.querySelector('[data-scene-image]');
  const title = element.querySelector('[data-scene-title]');
  const button = element.querySelector('button');
  const page = element.querySelector('[data-scene-page]');
  const data = element.querySelector('script[type="application/json"]');
  if (!image || !title || !button || !data) return;
  const scenes = JSON.parse(data.textContent || '[]');
  if (!scenes.length) return;
  const storageKey = 'ournotes.catalog.last-scene';
  let previousId;
  try { previousId = sessionStorage.getItem(storageKey); } catch { /* Storage is optional. */ }
  const choose = async (userInitiated = false) => {
    if (button.disabled) return;
    button.disabled = true;
    element.setAttribute('aria-busy', 'true');
    let candidates = scenes;
    try {
      while (candidates.length) {
        const scene = pickCatalogScene(candidates, previousId);
        const preload = new Image();
        preload.src = scene.src;
        try {
          await preload.decode();
        } catch {
          candidates = candidates.filter(candidate => candidate.id !== scene.id);
          continue;
        }
        const animate = userInitiated
          && document.documentElement.dataset.motion !== 'off'
          && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        await turnCatalogPage(page, () => {
          // Reuse the decoded node instead of assigning src to another <img>.
          preload.setAttribute('data-scene-image', '');
          preload.alt = scene.title;
          preload.width = scene.width;
          preload.height = scene.height;
          preload.decoding = 'async';
          image.replaceWith(preload);
          image = preload;
          title.textContent = scene.title;
        }, animate);
        previousId = scene.id;
        try { sessionStorage.setItem(storageKey, previousId); } catch { /* Storage is optional. */ }
        break;
      }
    } finally {
      button.disabled = scenes.length < 2;
      element.removeAttribute('aria-busy');
    }
  };
  button.hidden = scenes.length < 2;
  button.addEventListener('click', () => { void choose(true); });
  void choose();
}
