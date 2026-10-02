import { requestPageResource } from "./page-resource.mjs";
import { SEARCH_TYPES, searchUnified, highlightParts } from "./unified-search.mjs";

const PAGE_SIZE = 24;
const TYPE_SYMBOLS = { music: "♫", character: "◉", member_card: "◇", support_card: "▧", story: "≡", item: "◈", skill: "✦" };
const format = (template, values) => Object.entries(values).reduce((text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), template ?? "");

function appendHighlighted(element, text, query) {
  for (const part of highlightParts(text, query)) {
    const node = part.match ? document.createElement("mark") : document.createTextNode(part.text);
    if (part.match) node.textContent = part.text;
    element.append(node);
  }
}

class GlobalSearch extends HTMLElement {
  entries = [];
  selectedType = "all";
  loaded = false;
  loading = null;
  failed = false;
  composing = false;
  limit = PAGE_SIZE;
  suggestions = [];

  connectedCallback() {
    if (this.events) return;
    this.events = new AbortController();
    const listen = (target, type, handler) => target?.addEventListener(type, handler, { signal: this.events.signal });
    this.dialog = this.querySelector("[data-search-dialog]");
    this.input = this.querySelector("[data-search-input]");
    this.results = this.querySelector("[data-search-results]");
    this.summary = this.querySelector("[data-search-summary]");
    this.content = this.querySelector("[data-search-content]");
    this.openButton = this.querySelector("[data-search-open]");
    this.labels = JSON.parse(this.querySelector("[data-search-labels]")?.textContent ?? "{}");
    this.typeButtons = [...this.querySelectorAll("[data-search-type]")];
    const shortcut = this.querySelector("[data-search-shortcut]");
    if (shortcut) shortcut.textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘ K" : "Ctrl K";
    listen(this.openButton, "click", () => this.open());
    listen(this.querySelector("[data-search-close]"), "click", () => this.close());
    listen(this.querySelector("[data-search-clear]"), "click", () => {
      this.input.value = "";
      this.refresh();
      this.input.focus();
    });
    listen(this.querySelector("[data-search-retry]"), "click", () => this.load());
    listen(this.querySelector("[data-search-all]"), "click", () => this.selectType("all"));
    listen(this.input, "compositionstart", () => { this.composing = true; });
    listen(this.input, "compositionend", () => { this.composing = false; this.refresh(); });
    listen(this.input, "input", () => { if (!this.composing) this.refresh(); });
    this.typeButtons.forEach(button => listen(button, "click", () => this.selectType(button.dataset.searchType)));
    listen(this.querySelector("[data-search-more]"), "click", () => {
      const previous = this.results.children.length;
      this.limit += PAGE_SIZE;
      this.render();
      const next = this.results.children[previous];
      next?.focus({ preventScroll: true });
      next?.scrollIntoView({ block: "nearest" });
    });
    listen(this.results, "click", event => {
      if (event.target.closest("a") && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) this.close();
    });
    listen(this.dialog, "keydown", event => this.navigateResults(event));
    listen(this.dialog, "close", () => this.finishClose());
    listen(this.dialog, "click", event => {
      if (event.target !== this.dialog) return;
      const rect = this.dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) this.close();
    });
    this.handleShortcut = event => {
      if (event.defaultPrevented || event.isComposing || this.composing) return;
      const otherDialog = document.querySelector("dialog[open]");
      if (otherDialog && otherDialog !== this.dialog) return;
      const target = event.target;
      const editing = target instanceof HTMLElement && (target.isContentEditable || target.closest("input, textarea, select") !== null);
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        this.dialog?.open ? this.close() : this.open();
      } else if (!editing && !event.metaKey && !event.ctrlKey && !event.altKey && event.key === "/") {
        event.preventDefault();
        this.open();
      }
    };
    listen(document, "keydown", this.handleShortcut);
  }

  disconnectedCallback() {
    this.events?.abort();
    this.events = null;
    this.finishClose();
  }

  async load() {
    if (this.loaded) return;
    if (this.loading) return this.loading;
    this.failed = false;
    this.loading = Promise.resolve().then(() => requestPageResource(this.dataset.indexUrl))
      .then(response => {
        if (!response.ok) throw new Error("Search unavailable");
        return response.json();
      })
      .then(payload => {
        if (payload.schemaVersion !== 1 || payload.sourceReleaseId !== this.dataset.releaseId || !Array.isArray(payload.entries)) throw new Error("Invalid search index");
        this.entries = payload.entries.filter(entry => SEARCH_TYPES.includes(entry.type)
          && typeof entry.id === "string" && typeof entry.title === "string"
          && typeof entry.href === "string" && /^\/(?!\/)/.test(entry.href) && !entry.href.includes("\\"));
        this.suggestions = Array.isArray(payload.suggestions) ? payload.suggestions.filter(value => typeof value === "string").slice(0, 4) : [];
        this.loaded = true;
      })
      .catch(() => { this.failed = true; })
      .finally(() => {
        this.loading = null;
        if (this.dialog?.open) this.render();
      });
    this.render();
    return this.loading;
  }

  async open() {
    if (!(this.dialog instanceof HTMLDialogElement)) return;
    if (!this.dialog.open) {
      this.returnFocus = this.ownerDocument?.activeElement ?? this.openButton;
      this.sessionOpen = true;
      this.dialog.showModal();
      this.ownerDocument?.documentElement.classList.add("global-search-is-open");
    }
    this.input?.focus();
    await this.load();
    // Loading must not steal focus back after closing or moving to a filter.
    if (this.dialog.open) this.render();
  }

  finishClose() {
    if (!this.sessionOpen) return;
    this.sessionOpen = false;
    this.composing = false;
    this.ownerDocument?.documentElement.classList.remove("global-search-is-open");
    const target = this.returnFocus?.isConnected === false ? this.openButton : this.returnFocus;
    target?.focus({ preventScroll: true });
  }

  close() {
    if (this.dialog instanceof HTMLDialogElement && this.dialog.open) this.dialog.close();
    this.finishClose();
  }

  selectType(type) {
    this.selectedType = type;
    this.refresh();
  }

  refresh() {
    this.limit = PAGE_SIZE;
    if (this.content) this.content.scrollTop = 0;
    this.render();
  }

  navigateResults(event) {
    if (event.isComposing || this.composing || event.keyCode === 229 || event.altKey || event.ctrlKey || event.metaKey) return;
    const links = [...this.results.querySelectorAll("a")];
    if (!links.length) return;
    const target = event.target;
    const index = links.indexOf(target.closest?.("a"));
    if (target === this.input && event.key === "Enter") {
      event.preventDefault();
      links[0].click();
      return;
    }
    if (target !== this.input && index === -1) return;
    let next;
    if (event.key === "ArrowDown") next = links[Math.min(index + 1, links.length - 1)];
    else if (event.key === "ArrowUp") next = index <= 0 ? this.input : links[index - 1];
    else if (index >= 0 && event.key === "Home") next = links[0];
    else if (index >= 0 && event.key === "End") next = links.at(-1);
    if (next) {
      event.preventDefault();
      next.focus({ preventScroll: true });
      next.scrollIntoView({ block: "nearest" });
    }
  }

  render() {
    if (!this.results || !this.summary) return;
    const query = this.input?.value ?? "";
    const hasQuery = Boolean(query.trim());
    const state = this.querySelector("[data-search-state]");
    const title = this.querySelector("[data-search-state-title]");
    const hint = this.querySelector("[data-search-state-hint]");
    const retry = this.querySelector("[data-search-retry]");
    const all = this.querySelector("[data-search-all]");
    const more = this.querySelector("[data-search-more]");
    const suggestions = this.querySelector("[data-search-suggestions]");
    const clear = this.querySelector("[data-search-clear]");
    if (clear) clear.hidden = !query;
    this.results.replaceChildren();
    this.results.hidden = true;
    this.results.setAttribute("aria-busy", String(Boolean(this.loading)));
    for (const element of [retry, all, more, suggestions]) if (element) element.hidden = true;
    if (state) state.hidden = false;
    for (const button of this.typeButtons ?? []) button.setAttribute("aria-pressed", String(button.dataset.searchType === this.selectedType));
    if (!this.loaded) {
      this.summary.textContent = this.failed ? this.labels.error : this.labels.loading;
      if (title) title.textContent = this.failed ? this.labels.error : this.labels.loading;
      if (hint) hint.textContent = this.failed ? this.labels.errorHint : "";
      if (retry) retry.hidden = !this.failed;
      return;
    }
    const result = searchUnified(this.entries, { query, type: this.selectedType, limit: this.limit });
    const inventory = {};
    if (!hasQuery) for (const entry of this.entries) inventory[entry.type] = (inventory[entry.type] || 0) + 1;
    for (const button of this.typeButtons ?? []) {
      const kind = button.dataset.searchType;
      const count = hasQuery ? (kind === "all" ? result.totalAll : result.counts[kind]) : (kind === "all" ? this.entries.length : inventory[kind]);
      const label = button.querySelector("[data-type-count]");
      if (label) label.textContent = String(count ?? 0);
    }
    if (!hasQuery) {
      this.summary.textContent = this.labels.ready;
      if (title) title.textContent = this.labels.empty;
      if (hint) hint.textContent = this.labels.emptyHint;
      const buttons = this.querySelector("[data-search-suggestion-buttons]");
      if (buttons) {
        buttons.replaceChildren();
        for (const query of this.suggestions) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = query;
          button.addEventListener("click", () => { this.input.value = query; this.refresh(); this.input.focus(); });
          buttons.append(button);
        }
      }
      if (suggestions) suggestions.hidden = this.suggestions.length === 0;
      return;
    }
    this.summary.textContent = format(result.matches.length < result.total ? this.labels.partial : this.labels.summary, { shown: result.matches.length, total: result.total });
    if (!result.total) {
      if (title) title.textContent = this.labels.noResults;
      if (hint) hint.textContent = result.totalAll ? format(this.labels.otherTypes, { count: result.totalAll }) : this.labels.noResultsHint;
      if (all) all.hidden = !result.totalAll;
      return;
    }
    if (state) state.hidden = true;
    this.results.hidden = false;
    const fragment = document.createDocumentFragment();
    for (const entry of result.matches) {
      const link = document.createElement("a");
      link.href = /^\/(jp|global)\//.test(entry.href) ? entry.href : `${this.dataset.routePrefix ?? ""}${entry.href}`;
      link.className = "global-search-result";
      link.dataset.resultType = entry.type;
      const icon = document.createElement("span");
      icon.className = "global-search-result-icon";
      icon.textContent = TYPE_SYMBOLS[entry.type];
      icon.setAttribute("aria-hidden", "true");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      appendHighlighted(title, entry.title, query);
      const subtitle = document.createElement("small");
      appendHighlighted(subtitle, entry.subtitle, query);
      copy.append(title, subtitle);
      const type = document.createElement("span");
      type.className = "global-search-result-type";
      type.textContent = this.labels.types?.[entry.type] ?? entry.type;
      const arrow = document.createElement("b");
      arrow.setAttribute("aria-hidden", "true");
      arrow.textContent = "↗";
      link.append(icon, copy, type, arrow);
      fragment.append(link);
    }
    this.results.append(fragment);
    if (more) more.hidden = result.matches.length >= result.total;
  }
}

if (!customElements.get("global-search")) customElements.define("global-search", GlobalSearch);
export { SEARCH_TYPES as TYPE_ORDER };
