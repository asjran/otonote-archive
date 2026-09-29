class RecruitmentBrowser extends HTMLElement {
  connectedCallback() {
    if (this.dataset.ready) return;
    this.dataset.ready = "true";
    this.dialog = this.querySelector("[data-recruitment-dialog]");
    this.content = this.querySelector("[data-dialog-content]");
    this.addEventListener("click", event => {
      const opener = event.target.closest("[data-open-pool]");
      if (opener) this.open(opener.dataset.openPool, opener);
      if (event.target.closest("[data-close-dialog]")) this.dialog.close();
      if (event.target === this.dialog) {
        const rect = this.dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) this.dialog.close();
      }
    });
    this.dialog.addEventListener("close", () => {
      document.documentElement.style.overflow = this.previousOverflow || "";
      if (/^#pool-\d+$/.test(location.hash)) history.replaceState(null, "", `${location.pathname}${location.search}`);
      this.opener?.focus();
    });
    this.onHashChange = () => {
      const match = /^#pool-(\d+)$/.exec(location.hash);
      if (match) this.open(match[1]);
      else if (this.dialog.open) this.dialog.close();
    };
    window.addEventListener("hashchange", this.onHashChange);
    this.onHashChange();
  }
  disconnectedCallback() { window.removeEventListener("hashchange", this.onHashChange); }
  open(id, opener) {
    const template = this.querySelector(`[data-recruitment-template="${CSS.escape(id)}"]`);
    if (!template) return;
    this.opener = opener || document.activeElement;
    this.content.replaceChildren(template.content.cloneNode(true));
    this.dialog.setAttribute("aria-labelledby", `recruitment-title-${id}`);
    if (!this.dialog.open) {
      this.previousOverflow = document.documentElement.style.overflow;
      document.documentElement.style.overflow = "hidden";
      this.dialog.showModal();
    }
    this.dialog.scrollTop = 0;
    history.replaceState(null, "", `#pool-${id}`);
    this.querySelector("[data-close-dialog]").focus();
  }
}
if (!customElements.get("recruitment-browser")) customElements.define("recruitment-browser", RecruitmentBrowser);
