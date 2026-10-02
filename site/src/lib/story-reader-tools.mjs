import { findStoryLines, stepStoryMatch } from './story-reader-search.mjs';

class StoryReaderTools extends HTMLElement {
  connectedCallback() {
    this.events?.abort();
    this.events = new AbortController();
    const { signal } = this.events;
    const reader = this.closest('[data-text-reader]');
    const en = this.dataset.locale === 'en';
    const form = this.querySelector('form');
    const query = form.elements.namedItem('find');
    const speaker = form.elements.namedItem('speaker');
    const lines = [...reader.querySelectorAll('[data-story-line]')];
    const records = lines.map(line => ({
      speaker: line.dataset.storySpeaker || '',
      text: line.querySelector('.st-message > p, .st-system-message > p, h2')?.textContent ?? '',
    }));
    const status = this.querySelector('[data-story-find-status]');
    const previous = this.querySelector('[data-story-find-prev]');
    const next = this.querySelector('[data-story-find-next]');
    const link = this.querySelector('[data-story-find-link]');
    let matches = [], selected = -1;
    const save = () => {
      const url = new URL(location.href);
      for (const [key, value] of [['find', query.value.trim()], ['speaker', speaker.value]]) {
        if (value) url.searchParams.set(key, value); else url.searchParams.delete(key);
      }
      history.replaceState(history.state, '', url);
    };
    const show = (scroll = false) => {
      const active = lines[matches[selected]];
      lines.forEach((line, index) => {
        line.classList.toggle('st-find-match', matches.includes(index));
        line.classList.toggle('st-find-current', line === active);
      });
      previous.disabled = next.disabled = !matches.length;
      link.hidden = !active;
      const filtering = query.value.trim() || speaker.value;
      status.textContent = !filtering ? (en ? 'Find dialogue without hiding its context.' : '查找对白，保留前后文。')
        : matches.length ? `${selected + 1} / ${matches.length}` : (en ? 'No matching dialogue.' : '没有找到符合条件的对白。');
      if (active) {
        const url = new URL(location.href); url.hash = active.id;
        link.href = url.href;
        if (scroll) {
          history.replaceState(history.state, '', url);
          active.scrollIntoView({ block: 'center', behavior: 'instant' });
        }
      }
    };
    const search = () => {
      matches = findStoryLines(records, query.value, speaker.value);
      selected = matches.length ? 0 : -1;
      save(); show();
    };
    const restore = () => {
      const params = new URLSearchParams(location.search);
      query.value = params.get('find') || '';
      speaker.value = [...speaker.options].some(option => option.value === params.get('speaker')) ? params.get('speaker') : '';
      matches = findStoryLines(records, query.value, speaker.value);
      const hashIndex = matches.findIndex(index => `#${encodeURIComponent(lines[index].id)}` === location.hash || `#${lines[index].id}` === location.hash);
      selected = matches.length ? Math.max(0, hashIndex) : -1;
      show();
    };
    form.addEventListener('input', search, { signal });
    form.addEventListener('submit', event => { event.preventDefault(); search(); show(true); }, { signal });
    form.addEventListener('reset', event => {
      event.preventDefault(); query.value = ''; speaker.value = ''; search(); query.focus();
    }, { signal });
    for (const [button, direction] of [[previous, -1], [next, 1]]) button.addEventListener('click', () => {
      selected = stepStoryMatch(selected, direction, matches.length); show(true);
    }, { signal });
    window.addEventListener('popstate', restore, { signal });
    window.addEventListener('hashchange', restore, { signal });
    this.hidden = false;
    restore();
  }
  disconnectedCallback() { this.events?.abort(); }
}
if (!customElements.get('story-reader-tools')) customElements.define('story-reader-tools', StoryReaderTools);
