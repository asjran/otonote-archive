import { restoreFilterControl, selectedControlValues, matchesFilter } from './filter-controls.mjs';
import { createPaginationAdapter } from './pagination-browser.mjs';
import { serverSearchParams } from './game-servers.mjs';
const root = document.querySelector<HTMLElement>('[data-gallery]');
const form = root?.querySelector<HTMLFormElement>('[data-gallery-form]');
if (root && form) {
  const cards = [...root.querySelectorAll<HTMLElement>('[data-gallery-card]')];
  const controls = [...form.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input[name], select[name]')];
  const restore = () => {
    form.reset(); const params = new URLSearchParams(location.search);
    controls.forEach(c => { const value = params.get(c.name); if (value) restoreFilterControl(c, value); });
  };
  restore();
  let filtered = cards;
  let viewable = cards;
  let pagination: ReturnType<typeof createPaginationAdapter> = null;
  const update = (reset = false, mode: 'replace' | 'push' | 'none' = 'replace') => {
    if (reset) pagination?.reset();
    const params = new URLSearchParams();
    controls.forEach(c => { const value = c instanceof HTMLSelectElement ? selectedControlValues(c).join(',') : c.value; if (value && value !== 'all') params.set(c.name, value); });
    const query = (params.get('q') || '').trim().toLocaleLowerCase();
    filtered = cards.filter(card => (!query || (card.dataset.search || '').toLocaleLowerCase().includes(query)) && ['category', 'band', 'character'].every(key => matchesFilter((card.dataset[key] || '').split(','), params.get(key))));
    viewable = filtered.filter(card => card.querySelector('[data-gallery-open]'));
    root.dataset.category = params.get('category') ?? '';
    root.querySelectorAll<HTMLElement>('[data-gallery-category]').forEach(link => {
      if (link.dataset.galleryCategory === params.get('category')) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    const page = pagination?.paginate(filtered);
    const shown = new Set(page?.records ?? filtered);
    cards.forEach(card => { card.hidden = !shown.has(card); });
    root.querySelector('[data-gallery-count]')!.textContent = String(filtered.length);
    root.querySelector<HTMLElement>('[data-gallery-empty]')!.hidden = filtered.length > 0;
    if (page) pagination?.render(page);
    const next = serverSearchParams(pagination?.params(params) ?? params);
    if (mode !== 'none') history[mode === 'push' ? 'pushState' : 'replaceState'](null, '', `${location.pathname}${next.size ? `?${next}` : ''}`);
  };
  pagination = createPaginationAdapter(root, { onChange: (mode: 'replace' | 'push') => update(false, mode) });
  form.addEventListener('submit', event => event.preventDefault());
  form.addEventListener('input', () => update(true));
  form.addEventListener('change', () => update(true));
  root.querySelectorAll<HTMLAnchorElement>('[data-gallery-category]').forEach(link => link.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const category = form.elements.namedItem('category') as HTMLSelectElement;
    form.reset(); category.value = link.dataset.galleryCategory!;
    update(true, 'push');
  }));
  root.querySelectorAll('[data-gallery-clear]').forEach(button => button.addEventListener('click', () => { const category = root.dataset.kind === 'decorations' ? (form.elements.namedItem('category') as HTMLSelectElement).value : null; form.reset(); if (category) (form.elements.namedItem('category') as HTMLSelectElement).value = category; update(true); }));
  window.addEventListener('popstate', () => { restore(); pagination?.restore(new URLSearchParams(location.search)); update(false, 'none'); });
  update();

  const dialog = root.querySelector<HTMLDialogElement>('[data-gallery-viewer]')!;
  const image = dialog.querySelector<HTMLImageElement>('[data-viewer-image]')!;
  const download = dialog.querySelector<HTMLAnchorElement>('[data-viewer-download]')!;
  const previous = dialog.querySelector<HTMLButtonElement>('[data-viewer-prev]')!;
  const next = dialog.querySelector<HTMLButtonElement>('[data-viewer-next]')!;
  const zoom = dialog.querySelector<HTMLButtonElement>('[data-viewer-zoom]')!;
  const stage = dialog.querySelector<HTMLElement>('.gallery-viewer-stage')!;
  let active = 0;
  let opener: HTMLAnchorElement | null = null;
  let savedOverflow = '';
  const render = () => {
    const link = viewable[active].querySelector<HTMLAnchorElement>('[data-gallery-open]')!;
    image.src = link.href; image.alt = link.dataset.title ?? '';
    download.href = link.href; download.download = link.href.split('/').pop() ?? 'image.png';
    dialog.querySelector('[data-viewer-title]')!.textContent = image.alt;
    dialog.querySelector('[data-viewer-meta]')!.textContent = link.dataset.meta ?? '';
    dialog.dataset.zoomed = 'false'; zoom.setAttribute('aria-pressed', 'false');
    previous.disabled = active === 0; next.disabled = active === viewable.length - 1;
    stage.scrollTop = 0; stage.scrollLeft = 0;
  };
  cards.forEach(card => card.querySelector<HTMLAnchorElement>('[data-gallery-open]')?.addEventListener('click', event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); opener = event.currentTarget as HTMLAnchorElement;
    active = viewable.indexOf(card); render(); savedOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden'; dialog.showModal();
  }));
  dialog.querySelector('[data-viewer-close]')!.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) { const box = dialog.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close(); } });
  dialog.addEventListener('close', () => { document.body.style.overflow = savedOverflow; image.removeAttribute('src'); opener?.focus(); });
  const move = (delta: number) => { const index = active + delta; if (index >= 0 && index < viewable.length) { active = index; render(); } };
  previous.addEventListener('click', () => move(-1)); next.addEventListener('click', () => move(1));
  dialog.addEventListener('keydown', event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); } });
  zoom.addEventListener('click', () => { const value = dialog.dataset.zoomed !== 'true'; dialog.dataset.zoomed = String(value); zoom.setAttribute('aria-pressed', String(value)); });
}
