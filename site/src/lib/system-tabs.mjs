class SystemTabs extends HTMLElement {
  connectedCallback() {
    if (this.dataset.ready) return;
    this.dataset.ready = "true";
    this.addEventListener("click", event => {
      const button = event.target.closest("[data-view]");
      if (button) this.select(button.dataset.view);
    });
    const fromHash = location.hash.slice(1);
    if (this.querySelector(`[data-view="${CSS.escape(fromHash)}"]`)) this.select(fromHash);
  }
  select(view) {
    this.querySelectorAll("[data-view]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.view === view)));
    this.querySelectorAll("[data-view-panel]").forEach(panel => { panel.hidden = panel.dataset.viewPanel !== view; });
  }
}
if (!customElements.get("system-tabs")) customElements.define("system-tabs", SystemTabs);
