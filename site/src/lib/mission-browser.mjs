class MissionBrowser extends HTMLElement {
  connectedCallback() {
    if (this.dataset.ready) return;
    this.dataset.ready = "true";
    const dialog = this.querySelector("[data-mission-dialog]");
    const content = this.querySelector("[data-mission-content]");
    content.addEventListener("change", event => {
      if (!event.target.matches("[data-mission-section-select]")) return;
      let characterTemplate = false;
      for (const row of content.querySelectorAll("[data-mission-section]")) {
        row.hidden = row.dataset.missionSection !== event.target.value;
        if (!row.hidden) characterTemplate = row.dataset.characterTemplate === "true";
      }
      content.querySelector("[data-character-note]").hidden = !characterTemplate;
    });
    this.addEventListener("click", event => {
      const opener = event.target.closest("[data-open-mission]");
      if (opener) {
        const template = this.querySelector(`[data-mission-template="${CSS.escape(opener.dataset.openMission)}"]`);
        if (!template) return;
        this.opener = opener;
        content.replaceChildren(template.content.cloneNode(true));
        dialog.setAttribute("aria-labelledby", `mission-title-${opener.dataset.openMission}`);
        this.previousOverflow = document.documentElement.style.overflow;
        document.documentElement.style.overflow = "hidden";
        dialog.showModal();
        dialog.scrollTop = 0;
        this.querySelector("[data-close-mission]").focus();
      }
      if (event.target.closest("[data-close-mission]")) dialog.close();
    });
    const outside = event => {
      const box = dialog.getBoundingClientRect();
      return event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom);
    };
    let backdropPress = false;
    dialog.addEventListener("pointerdown", event => { backdropPress = outside(event); });
    dialog.addEventListener("click", event => {
      if (backdropPress && outside(event)) dialog.close();
      backdropPress = false;
    });
    dialog.addEventListener("close", () => {
      document.documentElement.style.overflow = this.previousOverflow || "";
      this.opener?.focus({ preventScroll: true });
    });
  }
}
if (!customElements.get("mission-browser")) customElements.define("mission-browser", MissionBrowser);
