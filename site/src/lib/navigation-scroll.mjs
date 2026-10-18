/** Scroll only the navigation container; never move the page or keyboard focus. */
export function revealCurrentNavigation(navigation) {
  if (!navigation?.clientHeight) return; // The mobile drawer may still be closed.
  const current = navigation.querySelector('a[aria-current="page"]');
  if (!current) return;
  const viewport = navigation.getBoundingClientRect();
  const link = current.getBoundingClientRect();
  if (link.top < viewport.top) navigation.scrollTop += link.top - viewport.top - 12;
  else if (link.bottom > viewport.bottom) navigation.scrollTop += link.bottom - viewport.bottom + 12;
}

export function restoreNavigationScroll(navigation, storage, options = {}) {
  if (!navigation) return;
  const key = 'ournotes-nav-scroll';
  try {
    const saved = Number(storage?.getItem(key));
    if (Number.isFinite(saved) && saved >= 0) navigation.scrollTop = saved;
  } catch { /* Storage is optional. */ }
  revealCurrentNavigation(navigation);
  navigation.addEventListener('scroll', () => {
    // Hiding the mobile drawer must not replace its saved position with zero.
    if (!navigation.clientHeight) return;
    try { storage?.setItem(key, String(navigation.scrollTop)); } catch { /* Storage is optional. */ }
  }, {passive:true, ...options});
}
