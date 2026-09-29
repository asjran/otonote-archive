export function studioUnlocks(unit, bandRank) {
  const levels = [...(unit?.levels || [])].sort((a, b) => a.level - b.level);
  const available = levels.filter(row => (row.unlockBandRank || 0) <= Number(bandRank));
  const gates = [];
  for (const row of levels) {
    const rank = row.unlockBandRank || 0;
    const gate = gates.find(item => item.bandRank === rank);
    if (gate) gate.maxLevel = row.level;
    else gates.push({ bandRank: rank, minLevel: row.level, maxLevel: row.level });
  }
  return { available, gates, cap: available.at(-1)?.level ?? 0,
    next: gates.find(gate => gate.bandRank > Number(bandRank)) ?? null };
}

export function selectStudioLevel(units, bandId, levelNumber, bandRank = Infinity) {
  const unit = units.find(item => item.id === Number(bandId)) || units[0];
  if (!unit) return null;
  const { available } = studioUnlocks(unit, bandRank);
  const level = available.find(item => item.level === Number(levelNumber))
    || available.filter(item => item.level <= Number(levelNumber)).at(-1) || available[0];
  return level ? { unit, level } : null;
}

class StudioPractice extends (globalThis.HTMLElement || class {}) {
  connectedCallback() {
    if (this.dataset.ready) return;
    this.dataset.ready = "true";
    this.units = JSON.parse(this.dataset.units || "[]");
    this.ranks = JSON.parse(this.dataset.ranks || "[]");
    this.en = this.dataset.en === "true";
    this.bandId = this.units[0]?.id;
    this.saved = new Map();
    this.rank = this.querySelector("[data-studio-rank]");
    this.level = this.querySelector("[data-studio-level]");
    if (!this.units.length || !this.rank || !this.level) return;
    this.addEventListener("click", event => {
      const band = event.target.closest("[data-studio-band]");
      if (band) {
        this.bandId = Number(band.dataset.studioBand);
        const saved = this.saved.get(this.bandId);
        this.rank.value = saved?.rank || this.ranks[0]?.rank || "1";
        this.updateLevels(saved?.level || 1);
        this.render();
      }
      const step = event.target.closest("[data-level-step]");
      if (step) {
        const unit = this.units.find(unit => unit.id === this.bandId);
        const { available } = studioUnlocks(unit, this.rank.value);
        const index = available.findIndex(row => row.level === Number(this.level.value));
        const next = available[index + Number(step.dataset.levelStep)];
        if (next) { this.level.value = String(next.level); this.render(); }
      }
    });
    this.rank.addEventListener("change", () => { this.updateLevels(); this.render(); });
    this.level.addEventListener("change", () => this.render());
    this.updateLevels(1);
    this.render();
  }
  rankLabel(rank) {
    if (Number(rank) === 0) return this.en ? "No requirement" : "无门槛";
    return this.ranks.find(item => item.rank === Number(rank))?.label || (this.en ? "Unknown rank" : "段位未收录");
  }
  updateLevels(levelNumber = this.level.value) {
    const selected = selectStudioLevel(this.units, this.bandId, levelNumber, this.rank.value);
    if (!selected) return;
    this.level.replaceChildren(...selected.unit.levels.map(level => {
      const option = document.createElement("option");
      option.value = String(level.level);
      option.disabled = level.unlockBandRank > Number(this.rank.value);
      option.textContent = `Lv. ${level.level}${option.disabled ? ` · ${this.en ? "Requires" : "需"} ${this.rankLabel(level.unlockBandRank)}` : ""}`;
      return option;
    }));
    this.level.value = String(selected.level.level);
  }
  render() {
    const selected = selectStudioLevel(this.units, this.bandId, this.level.value, this.rank.value);
    if (!selected) return;
    const { unit, level } = selected;
    const { available, gates, cap, next } = studioUnlocks(unit, this.rank.value);
    this.saved.set(unit.id, { rank: this.rank.value, level: this.level.value });
    this.querySelectorAll("[data-studio-band]").forEach(button => button.setAttribute("aria-pressed", String(Number(button.dataset.studioBand) === unit.id)));
    this.querySelector("[data-level-step='-1']").disabled = level.level === available[0]?.level;
    this.querySelector("[data-level-step='1']").disabled = level.level === cap;
    this.querySelector("[data-studio-cap]").textContent = `Lv. ${cap}`;
    this.querySelector("[data-studio-next]").textContent = next
      ? (this.en ? `Reach ${this.rankLabel(next.bandRank)} to unlock up to Lv. ${next.maxLevel}.` : `乐队达到 ${this.rankLabel(next.bandRank)}，练习上限提升至 Lv. ${next.maxLevel}。`)
      : (this.en ? "All practice levels are unlocked." : "已解锁全部练习等级。");
    const rankImage = this.querySelector("[data-studio-rank-image]");
    const rank = this.ranks.find(row => row.rank === Number(this.rank.value));
    if (rank) { rankImage.src = `${this.dataset.artBase}${rank.image}`; rankImage.alt = rank.label; }
    this.querySelector("[data-studio-title]").textContent = unit.name;
    this.querySelector("[data-studio-level-label]").textContent = `Lv. ${level.level}`;
    const values = { ...level, unlockBandRank: this.rankLabel(level.unlockBandRank), efficiencyHours: `${level.efficiencySeconds / 3600} h`, limitHours: `${level.limitSeconds / 3600} h` };
    this.querySelectorAll("[data-stat]").forEach(node => { const value = values[node.dataset.stat]; node.textContent = typeof value === "number" ? value.toLocaleString() : value; });
    const itemNodes = (unit.itemRewards[String(level.itemLotGroupId)] || []).map(item => {
      const li = document.createElement("li");
      if (item.image) { const img = document.createElement("img"); img.src = item.image; img.alt = ""; img.loading = "lazy"; li.append(img); }
      const name = document.createElement("span"); name.textContent = item.name;
      const count = document.createElement("strong"); count.textContent = `×${item.count}`;
      const rate = document.createElement("small"); rate.textContent = item.percent == null ? "—" : `${Number(item.percent.toFixed(2))}%`;
      li.append(name, count, rate); return li;
    });
    this.querySelector("[data-studio-items]").replaceChildren(...itemNodes);
    this.querySelector("[data-studio-table]").replaceChildren(...unit.levels.map(row => {
      const tr = document.createElement("tr");
      if (row.level === level.level) tr.setAttribute("aria-current", "true");
      const locked = row.unlockBandRank > Number(this.rank.value);
      tr.dataset.locked = String(locked);
      for (const value of [row.level, row.requiredExp.toLocaleString(), this.rankLabel(row.unlockBandRank), locked ? (this.en ? "Locked" : "未解锁") : (this.en ? "Available" : "可练习"), row.rawEarnCoin.toLocaleString(), `${row.rawEarnMemberExp} / ${row.rawEarnSupportExp}`, row.rawEarnOfflineBonusExp.toLocaleString()]) {
        const td = document.createElement("td"); td.textContent = String(value); tr.append(td);
      }
      return tr;
    }));
    this.querySelector("[data-studio-gates]").replaceChildren(...gates.map(gate => {
      const li = document.createElement("li");
      li.dataset.unlocked = String(gate.bandRank <= Number(this.rank.value));
      const label = document.createElement("strong"); label.textContent = this.rankLabel(gate.bandRank);
      const range = document.createElement("span"); range.textContent = `Lv. ${gate.minLevel}–${gate.maxLevel}`;
      li.append(label, range); return li;
    }));
  }
}
if (typeof customElements !== "undefined" && !customElements.get("studio-practice")) customElements.define("studio-practice", StudioPractice);
