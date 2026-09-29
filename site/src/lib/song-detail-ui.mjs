import { songViewFromLocation, songDifficultyFromLocation } from './song-detail-state.mjs';
import { SCORE_DIFFICULTY_CHANGE_EVENT, SCORE_DIFFICULTY_REQUEST_EVENT } from './score-workbench-element.ts';

class SongDetailPage extends HTMLElement {
  connectedCallback() {
    this.events?.abort();
    this.events = new AbortController();
    const signal = this.events.signal;
    const listen = (target, event, callback) => target.addEventListener(event, callback, { signal });
    const buttons = [...this.querySelectorAll('[data-song-view]')];
    const panels = [...this.querySelectorAll('[data-song-panel]')];
    const dialog = this.querySelector('[data-song-dialog]');
    const title = this.querySelector('[data-song-dialog-title]');
    const difficultySelect = this.querySelector('[data-song-dialog-difficulty]');
    const available = [...this.querySelectorAll('[data-page-difficulty]')].map(button => button.dataset.pageDifficulty);
    let currentView = null, opener = null;

    const showDifficulty = difficulty => {
      this.querySelectorAll('[data-reward-difficulty]').forEach(panel => { panel.hidden = panel.dataset.rewardDifficulty !== difficulty; });
      difficultySelect.value = difficulty;
      const labLink = this.querySelector('[data-song-lab-link]');
      if (labLink) {
        const url = new URL(labLink.href);
        url.searchParams.set('difficulty', difficulty);
        labLink.href = url.href;
      }
    };
    const showView = (view, navigation = null) => {
      const button = buttons.find(item => item.dataset.songView === view);
      currentView = button ? view : null;
      buttons.forEach(item => item.setAttribute('aria-expanded', String(item === button)));
      panels.forEach(panel => { panel.hidden = panel.dataset.songPanel !== currentView; });
      if (currentView) {
        opener = button;
        dialog.dataset.view = currentView;
        title.textContent = button.querySelector('strong').textContent;
        if (!dialog.open) dialog.showModal();
      } else if (dialog.open) {
        dialog.close();
        opener?.focus({ preventScroll: true });
      }
      if (navigation) {
        const url = new URL(location.href);
        if (currentView) url.searchParams.set('view', currentView);
        else url.searchParams.delete('view');
        url.hash = '';
        history[navigation === 'push' ? 'pushState' : 'replaceState'](null, '', url);
      }
      window.dispatchEvent(new CustomEvent('song-detail-view-change', { detail: { view: currentView } }));
    };
    buttons.forEach(button => listen(button, 'click', () => showView(button.dataset.songView, 'push')));
    listen(this.querySelector('[data-song-dialog-close]'), 'click', () => showView(null, 'replace'));
    listen(dialog, 'cancel', event => { event.preventDefault(); showView(null, 'replace'); });
    listen(dialog, 'close', () => { if (!dialog.open && currentView) showView(null, 'replace'); });
    listen(dialog, 'click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) showView(null, 'replace');
    });
    listen(difficultySelect, 'change', () => window.dispatchEvent(new CustomEvent(SCORE_DIFFICULTY_REQUEST_EVENT, { detail: { difficulty: difficultySelect.value } })));
    listen(window, SCORE_DIFFICULTY_CHANGE_EVENT, event => showDifficulty(event.detail.difficulty));
    const restore = () => {
      showView(songViewFromLocation(location.search, location.hash));
      showDifficulty(songDifficultyFromLocation(location.search, available));
    };
    listen(window, 'popstate', restore);
    listen(window, 'hashchange', restore);
    restore();
    customElements.whenDefined('score-workbench').then(() => {
      if (!this.isConnected || signal.aborted) return;
      window.dispatchEvent(new CustomEvent(SCORE_DIFFICULTY_REQUEST_EVENT, { detail: { difficulty: songDifficultyFromLocation(location.search, available) } }));
    });
  }
  disconnectedCallback() {
    this.events?.abort();
    this.querySelector('[data-song-dialog]')?.close();
  }
}
if (!customElements.get('song-detail-page')) customElements.define('song-detail-page', SongDetailPage);
