import {setupCalculatorCardPicker} from './calculator-card-picker.mjs';
import {skillPeek,destroySkillPopover} from './calculator-card-ui.mjs';
import {setupCalculatorSongPicker} from './calculator-song-picker.mjs';
import {setupCalculatorJourney} from './calculator-journey.mjs';
import {setupQuickOptions} from './tool-quick-options.mjs';
import {attributeBadge} from './calculator-attribute-ui.mjs';

  import { toolRoute } from "./tool-route.mjs";
  import { resolveTgwCardRankBonus } from "./scoring-rules/tgw-card.mjs";
  import { setupProductionPower } from "./production-power-ui.mjs";
  import {
    createTeamDraft,
    deriveTeamDraftSummary,
    parseTeamDraftSearch,
    serializeTeamDraftSearch,
    serializeTeamDraftJson,
    validateTeamDraft
  } from "./team-draft.mjs";

  class TeamDraftWorkbench extends HTMLElement {
    connectedCallback() {
      // Match reading/tab order to the task, keeping one set of form controls.
      const sections = this.dataset.mode === "optimizer"
        ? [".workbench-route-tabs", ".calculator-guide", ".calculator-strategy", ".team-draft-settings", ".optimizer-panel", ".optimizer-results-panel", ".team-workbench-grid", ".team-card-picker", ".workbench-breakdown", ".workbench-song-pool", ".workbench-rules"]
        : [".workbench-route-tabs", ".calculator-strategy", ".team-draft-settings", ".team-workbench-grid", ".team-card-picker", ".optimizer-panel", ".optimizer-results-panel", ".workbench-breakdown", ".workbench-song-pool", ".workbench-rules"];
      sections.forEach(selector => { const section = this.querySelector(selector); if (section) this.append(section); });
      const dataNode = this.querySelector("[data-team-draft-data]");
      if (!(dataNode instanceof HTMLScriptElement)) return;
      this.data = JSON.parse(dataNode.textContent || "{}");
      this.labels = this.data.labels;
      this.numberFormatter = new Intl.NumberFormat(this.data.locale);
      this.memberById = new Map(this.data.memberCards.map((card) => [card.id, card]));
      this.supportById = new Map(this.data.supportCards.map((card) => [card.id, card]));
      this.known = {
        memberCardIds: new Set(this.memberById.keys()),
        supportCardIds: new Set(this.supportById.keys()),
        musicTrackIds: new Set(this.data.tracks.map((track) => track.id))
      };
      if (this.data.vipRanks?.length) {
        this.known.tgwCardRanks = new Set(this.data.vipRanks.map((entry) => entry.rank));
      }
      const parsed = parseTeamDraftSearch(window.location.search, this.known);
      this.draft = parsed.draft;
      this.parseIssues = parsed.issues.filter((issue) => issue.code === "invalid_modifiers");
      this.activeSlot = 0;
      this.pickerKind = "member";
      this.productionPower = setupProductionPower(this);
      this.cardPicker=setupCalculatorCardPicker(this);
      this.bindEvents();
      this.songPicker=setupCalculatorSongPicker(this,{getSelection:()=>this.draft,onSelect:selection=>{Object.assign(this.draft,selection);this.commit();}});
      this.journey=setupCalculatorJourney(this);
      this.quickOptions=setupQuickOptions(this);
      this.render();
    }

    bindEvents() {
      this.querySelector("[data-song-select]")?.addEventListener("change", (event) => {
        this.draft.selectedSongId = event.target.value || null;
        this.commit();
      });
      this.querySelector("[data-difficulty-select]")?.addEventListener("change", (event) => {
        this.draft.selectedDifficulty = event.target.value || null;
        this.commit();
      });
      this.querySelector("[data-tgw-rank-select]")?.addEventListener("change", (event) => {
        if (event.target.value) {
          this.draft.modifiers.tgwCardRank = Number(event.target.value);
        } else {
          delete this.draft.modifiers.tgwCardRank;
        }
        this.commit();
      });
      this.querySelector("[data-copy-draft]")?.addEventListener("click", async () => {
        const text = serializeTeamDraftJson(this.draft);
        const status = this.querySelector("[data-copy-status]");
        try {
          await navigator.clipboard.writeText(text);
          if (status) status.textContent = this.labels.copied;
        } catch {
          if (status) status.textContent = this.labels.copyFailed;
        }
      });
    }

    cardFor(kind, id) {
      if (!id) return null;
      return kind === "member" ? this.memberById.get(id) : this.supportById.get(id);
    }

    cardFace(kind, id, slotIndex = this.activeSlot) {
      const card = this.cardFor(kind, id);
      const face = document.createElement("div");
      face.className = `team-slot-card team-slot-card--${kind}`;
      if (!card) {
        face.classList.add("is-empty");
        const label = id
          ? `${this.labels.unknownPrefix}${id}`
          : kind === "member"
            ? this.labels.selectMember
            : this.labels.selectSupport;
        face.textContent = label;
        return face;
      }
      if (card.imageUrl) {
        const image = document.createElement("img");
        image.src = card.imageUrl;
        image.alt = "";
        face.append(image);
      }
      const copy = document.createElement("span");
      const name = document.createElement("strong");
      name.textContent = card.shortLabel;
      name.dataset.uiEntity = "";
      const relation = document.createElement("small");
      relation.textContent = card.relationLabel || card.displayName;
      relation.dataset.uiEntity = "";
      copy.append(name, relation, attributeBadge(card.attributeCode, this.data.attributeVisuals));
      face.append(copy);
      face.append(skillPeek(this,card,{growth:this.draft.modifiers.growth?.[id],leader:slotIndex===2},face));
      return face;
    }

    renderSlots() {
      const container = this.querySelector("[data-team-slots]");
      if (!container) return;
      container.replaceChildren();
      this.draft.slots.forEach((slot, index) => {
        const button = document.createElement("article");
        button.className = "team-slot";
        button.classList.toggle("is-active", index === this.activeSlot);

        const number = document.createElement("button");
        number.type="button";number.setAttribute("aria-pressed",String(index===this.activeSlot));number.setAttribute("aria-label",`${this.labels.editSlot} ${index+1}${index===2?` ${this.labels.leader}`:""}`);
        number.className = "team-slot-number";
        number.textContent = index === 2 ? `03 · ${this.labels.leader}` : String(index + 1).padStart(2, "0");
        const cards = document.createElement("span");
        cards.className = "team-slot-pair";
        cards.append(
          this.cardFace("member", slot.memberCardId,index),
          this.cardFace("support", slot.supportCardId,index)
        );
        button.append(number, cards);
        number.addEventListener("click", () => {
          this.activeSlot = index;
          this.renderSlots();
          this.renderPickerState();
          this.productionPower?.settings();
        });
        container.append(button);
      });
    }

    renderPickerState() {
      const label = this.querySelector("[data-active-slot-label]");
      if (label) label.textContent = String(this.activeSlot + 1).padStart(2, "0");
      this.cardPicker?.sync();
    }

    filterCards() { this.cardPicker?.sync(); }

    renderSummary() {
      const summary = deriveTeamDraftSummary(this.draft, {
        memberCards: this.data.memberCards,
        supportCards: this.data.supportCards,
        projections: this.data.projections
      });
      const setNumber = (selector, value) => {
        const element = this.querySelector(selector);
        if (element) {
          element.textContent = this.numberFormatter.format(Number(value));
        }
      };
      const power = this.productionPower?.render();
      for (const [selector, field] of [["[data-total-power]", "total"], ["[data-power-performance]", "performance"],
        ["[data-power-technic]", "technic"], ["[data-power-visual]", "visual"]]) {
        if (power) setNumber(selector, power[field]);
        else { const node = this.querySelector(selector); if (node) node.textContent = "—"; }
      }
      setNumber("[data-member-count]", summary.selectedMemberCount);
      setNumber("[data-support-count]", summary.selectedSupportCount);
      const completion = this.querySelector("[data-team-completion]");
      if (completion) {
        completion.textContent = summary.isComplete
          ? this.labels.complete
          : `${this.labels.incomplete} · ${this.labels.member} ` +
            `${summary.selectedMemberCount}/5 · ${this.labels.support} ` +
            `${summary.selectedSupportCount}/5`;
        completion.classList.toggle("is-complete", summary.isComplete);
      }
      const skills = this.querySelector("[data-team-skills]");
      if (!skills) return;
      skills.replaceChildren();
      if (summary.skillSummaries.length === 0) {
        const empty = document.createElement("p");
        empty.textContent = this.labels.emptySkills;
        skills.append(empty);
        return;
      }
      summary.skillSummaries.forEach((skill) => {
        const item = document.createElement("article");
        const meta = document.createElement("span");
        const slotKind = this.memberById.has(skill.cardId)
          ? this.labels.memberSlot
          : this.labels.supportSlot;
        meta.textContent = `${this.labels.slot} ` +
          `${String(skill.slotIndex + 1).padStart(2, "0")} · ${slotKind} · Lv.${skill.level ?? "?"}`;
        const title = document.createElement("strong");
        title.textContent = skill.name;
        title.dataset.uiEntity = "";
        const description = document.createElement("p");
        description.textContent = skill.summary;
        description.dataset.uiEntity = "";
        item.append(meta, title, description);
        skills.append(item);
      });
    }

    renderDraft() {
      const song = this.querySelector("[data-song-select]");
      if (song) song.value = this.draft.selectedSongId || "";
      const difficulty = this.querySelector("[data-difficulty-select]");
      if (difficulty) difficulty.value = this.draft.selectedDifficulty || "";
      const tgwRank = this.querySelector("[data-tgw-rank-select]");
      if (tgwRank) tgwRank.value = String(this.draft.modifiers.tgwCardRank ?? "");
      const tgwNote = this.querySelector("[data-tgw-bonus-note]");
      if (tgwNote && this.draft.modifiers.tgwCardRank) {
        try {
          const bonus = resolveTgwCardRankBonus(
            this.data.vipRanks, this.draft.modifiers.tgwCardRank
          );
          tgwNote.textContent = this.labels.tgwBonus.replace("{rank}", bonus.rank)
            .replace("{percent}", bonus.rawValue / 100).replace("{bp}", bonus.rawValue);
        } catch {
          tgwNote.textContent = this.labels.issues.invalid_tgw_card_rank;
        }
      } else if (tgwNote) {
        tgwNote.textContent = this.labels.tgwDefault;
      }
      const json = this.querySelector("[data-draft-json]");
      if (json) json.textContent = serializeTeamDraftJson(this.draft);
      const apLink=this.querySelector('[data-ap-grade-link]');if(apLink)apLink.href=toolRoute('/tools/ap-grade/',location.pathname)+serializeTeamDraftSearch(this.draft);
      const researchLink = this.querySelector("[data-scoring-research-link]");
      if (researchLink instanceof HTMLAnchorElement) {
        researchLink.href = toolRoute(`/tools/song-calculator/${serializeTeamDraftSearch(this.draft)}`, window.location.pathname);
      }
      const validation = this.querySelector("[data-team-validation]");
      const rankingLink = this.querySelector('[data-song-ranking-link]');
      if (rankingLink) rankingLink.href = toolRoute('/tools/song-ranking/', window.location.pathname);
      if (!validation) return;
      const issues = [...this.parseIssues, ...validateTeamDraft(this.draft, this.known)];
      validation.replaceChildren();
      const title = document.createElement("strong");
      title.textContent = issues.length === 0
        ? this.labels.validDraft
        : `${issues.length} ${this.labels.draftIssues}`;
      validation.append(title);
      const note = document.createElement("p");
      note.textContent = issues.length === 0
        ? this.labels.validDraftNote
        : issues
            .map((entry) => this.labels.issues[entry.code] ?? entry.code)
            .join("; ");
      validation.append(note);
    }

    commit() {
      this.productionPower?.changed();
      this.draft = createTeamDraft(this.draft);
      const query = serializeTeamDraftSearch(this.draft);
      window.history.replaceState(null, "", `${window.location.pathname}${query}${window.location.hash}`);
      this.render();
    }

    render() {
      this.renderSlots();
      this.renderPickerState();
      this.renderSummary();
      this.renderDraft();
      this.productionPower?.settings();
      this.songPicker?.sync();
      this.journey?.refresh();
      this.quickOptions?.sync();
    }

    disconnectedCallback() { destroySkillPopover(this); this.productionPower?.disconnect(); this.journey?.disconnect(); this.quickOptions?.destroy(); }
  }

  if (!customElements.get("team-draft-workbench")) {
    customElements.define("team-draft-workbench", TeamDraftWorkbench);
  }
