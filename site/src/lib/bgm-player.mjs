import { matchesBgm } from './bgm-filtering.mjs';

class BgmLibrary extends HTMLElement {
  connectedCallback() {
    if (this.abort) return;
    this.abort = new AbortController();
    const { signal } = this.abort;
    const copy = JSON.parse(this.dataset.copy);
    const audio = this.querySelector('audio');
    this.audio = audio;
    const form = this.querySelector('form');
    const search = form.elements.namedItem('q');
    const available = form.elements.namedItem('available');
    const status = this.querySelector('[data-bgm-status]');
    const rows = [...this.querySelectorAll('[data-bgm-track]')];
    const tabs = [...this.querySelectorAll('[data-bgm-category]')];
    let category = 'all';
    let current = null;
    let attempt = 0;
    const syncButtons = () => rows.forEach(row => {
      const button = row.querySelector('[data-bgm-play]');
      if (!button) return;
      const selected = row === current;
      const playing = selected && !audio.paused && !audio.ended;
      row.classList.toggle('is-current', selected);
      button.setAttribute('aria-pressed', String(playing));
      button.setAttribute('aria-label', `${playing ? copy.pause : copy.play} ${row.dataset.title}`);
      button.title = `${playing ? copy.pause : copy.play} ${row.dataset.title}`;
      button.querySelector('[data-play-text]').textContent = playing ? copy.pause : copy.play;
      button.querySelector('[data-play-icon]').textContent = playing ? 'Ⅱ' : '▶';
    });
    const filter = (save = true) => {
      let count = 0;
      rows.forEach(row => {
        row.hidden = !matchesBgm({ title: row.dataset.title, cueName: row.dataset.cue,
          categoryIds: row.dataset.categories.split(' '), status: row.dataset.status }, search.value, category, available.checked);
        if (!row.hidden) count++;
      });
      this.querySelectorAll('[data-bgm-group]').forEach(group => {
        const visible = [...group.querySelectorAll('[data-bgm-track]')].filter(row => !row.hidden).length;
        group.hidden = visible === 0;
        group.querySelector('[data-bgm-group-count]').textContent = String(visible);
      });
      tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.bgmCategory === category)));
      this.querySelector('[data-bgm-count]').textContent = String(count);
      this.querySelector('[data-bgm-empty]').hidden = count !== 0;
      if (save) {
        const url = new URL(location.href);
        [['category', category === 'all' ? '' : category], ['q', search.value.trim()], ['available', available.checked ? '1' : '']].forEach(([key, value]) => {
          if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
        });
        history.replaceState(history.state, '', url);
      }
    };
    const restore = () => {
      const params = new URL(location.href).searchParams;
      category = tabs.some(tab => tab.dataset.bgmCategory === params.get('category')) ? params.get('category') : 'all';
      search.value = params.get('q') || '';
      available.checked = params.get('available') === '1';
      filter(false);
    };
    tabs.forEach(tab => tab.addEventListener('click', () => { category = tab.dataset.bgmCategory; filter(); }, { signal }));
    form.addEventListener('submit', event => { event.preventDefault(); filter(); }, { signal });
    form.addEventListener('input', () => filter(), { signal });
    form.addEventListener('reset', event => {
      event.preventDefault(); search.value = ''; available.checked = false; category = 'all'; filter();
    }, { signal });
    window.addEventListener('popstate', restore, { signal });
    this.querySelector('[data-bgm-loop]').addEventListener('change', event => { audio.loop = event.target.checked; }, { signal });
    this.addEventListener('click', async event => {
      const button = event.target.closest('[data-bgm-play]');
      if (!button) return;
      const row = button.closest('[data-bgm-track]');
      const token = ++attempt;
      if (current === row && !audio.paused) { audio.pause(); syncButtons(); return; }
      if (current !== row || audio.error) {
        audio.pause(); current = row;
        audio.src = button.dataset.url;
        this.querySelector('[data-bgm-now]').textContent = row.dataset.title;
      }
      status.textContent = copy.loading;
      syncButtons();
      try { await audio.play(); }
      catch { if (token === attempt && this.isConnected) status.textContent = copy.failed; }
      if (this.isConnected) syncButtons();
    }, { signal });
    ['playing', 'pause', 'ended', 'error', 'waiting'].forEach(type => audio.addEventListener(type, () => {
      status.textContent = type === 'error' ? copy.failed : type === 'waiting' ? copy.loading
        : type === 'playing' ? copy.playing : copy.paused;
      syncButtons();
    }, { signal }));
    restore();
  }

  disconnectedCallback() {
    this.abort?.abort();
    this.abort = null;
    this.audio?.pause();
    this.audio?.removeAttribute('src');
    this.audio?.load();
  }
}
if (!customElements.get('bgm-library')) customElements.define('bgm-library', BgmLibrary);
