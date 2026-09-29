import { requestPageResource } from "./page-resource.mjs";
class DatabaseDetailDialog extends HTMLElement {
  connectedCallback() {
    if (this.controller) return;
    this.controller = new AbortController();
    const options = { signal: this.controller.signal };
    this.dialog = this.querySelector('dialog');
    this.content = this.querySelector('[data-db-content]');
    this.cache = new Map();
    document.addEventListener('click', event => {
      if (!(event.target instanceof Element)) return;
      const opener = event.target.closest('[data-db-open]');
      if (!opener || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      this.opener = opener;
      const url = new URL(location.href); url.hash = `detail=${opener.dataset.dbOpen}`;
      history.pushState({ ...history.state, databaseDialog: true }, '', url);
      this.sync();
    }, options);
    this.addEventListener('click', event => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest('[data-db-close]')) this.close();
      if (event.target.closest('[data-db-retry]')) this.sync();
      const level = event.target.closest('[data-skill-level]');
      if (level) this.selectLevel(level.dataset.skillLevel);
      if (event.target === this.dialog) {
        const r = this.dialog.getBoundingClientRect();
        if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) this.close();
      }
    }, options);
    this.dialog.addEventListener('cancel', event => { event.preventDefault(); this.close(); }, options);
    this.dialog.addEventListener('close', () => {
      this.request?.abort();
      document.documentElement.style.overflow = this.previousOverflow ?? '';
      if (this.opener?.isConnected) this.opener.focus({ preventScroll: true });
    }, options);
    window.addEventListener('popstate', () => this.sync(), options);
    window.addEventListener('hashchange', () => this.sync(), options);
    this.sync();
  }
  disconnectedCallback() {
    if (this.dialog?.open) { this.dialog.close(); document.documentElement.style.overflow = this.previousOverflow ?? ''; }
    this.controller?.abort(); this.request?.abort(); this.controller = null;
  }
  close() {
    if (history.state?.databaseDialog) history.back();
    else {
      history.replaceState(history.state, '', `${location.pathname}${location.search}`);
      this.sync();
    }
  }
  selectLevel(value) {
    this.content.querySelectorAll('[data-skill-level]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.skillLevel === value)));
    this.content.querySelectorAll('[data-skill-panel]').forEach(panel => { panel.hidden = panel.dataset.skillPanel !== value; });
  }
  async sync() {
    const match = /^#detail=([a-z0-9-]+)$/.exec(location.hash);
    if (!match) { this.request?.abort(); if (this.dialog.open) this.dialog.close(); return; }
    const id = match[1];
    this.request?.abort(); this.request = new AbortController();
    const request = this.request;
    this.content.replaceChildren();
    this.dialog.removeAttribute('aria-labelledby');
    this.querySelector('[data-db-error]').hidden = true;
    this.querySelector('[data-db-loading]').hidden = false;
    if (!this.dialog.open) {
      this.opener ||= document.activeElement;
      this.previousOverflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = 'hidden';
      this.dialog.showModal();
    }
    this.dialog.scrollTop = 0;
    try {
      let html = this.cache.get(id);
      if (!html) {
        const response = await requestPageResource(`${this.dataset.detailBase}${encodeURIComponent(id)}/`, { signal: request.signal });
        if (!response.ok) throw new Error('Detail unavailable');
        html = await response.text();
      }
      if (request.signal.aborted) return;
      const detail = new DOMParser().parseFromString(html, 'text/html').querySelector('[data-db-detail]');
      if (!detail) throw new Error('Detail unavailable');
      this.cache.set(id, html);
      this.content.replaceChildren(detail);
      this.dialog.setAttribute('aria-labelledby', 'db-detail-title');
    } catch (error) {
      if (!request.signal.aborted) this.querySelector('[data-db-error]').hidden = false;
    } finally {
      if (!request.signal.aborted) this.querySelector('[data-db-loading]').hidden = true;
    }
  }
}
if (!customElements.get('database-detail-dialog')) customElements.define('database-detail-dialog', DatabaseDetailDialog);
