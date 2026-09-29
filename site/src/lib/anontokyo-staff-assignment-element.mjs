import {
  assignCharacter,
  assignmentContext,
  createDefaultAssignmentState,
  normalizeAssignmentState,
  STANDBY_ROLE
} from "./anontokyo-staff-assignment.mjs";


const ERROR_MESSAGES = {
  character_locked: "该角色尚未达到当前模拟等级。",
  role_full: "该岗位已经满员。",
  unknown_character: "角色资料不存在。",
  unknown_role: "岗位资料不存在。"
};


function imageUrl(payload, record) {
  return record.imageKey
    ? payload.imageByKey[String(record.imageKey).toLocaleLowerCase("en-US")]
    : null;
}


function tendencyText(record) {
  return (record.abilities ?? [])
    .map((ability) => ability.roleInclination)
    .filter(Boolean)
    .map((inclination) => `${inclination.name} ${inclination.value ?? "–"}`)
    .join(" · ");
}


class AnonTokyoStaffAssignmentElement extends HTMLElement {
  connectedCallback() {
    if (this.initialized) return;
    this.initialized = true;
    const source = this.querySelector("[data-assignment-data]")?.textContent;
    if (!source) return;
    this.payload = JSON.parse(source);
    this.datasetDocument = this.payload.staff;
    this.storageKey = this.dataset.storageKey;
    this.selectedCharacterId = null;
    this.bindDom();
    this.restore();
    this.bindControls();
    this.render();
  }

  bindDom() {
    this.roleList = this.querySelector("[data-role-list]");
    this.standbyList = this.querySelector("[data-standby-list]");
    this.lockedList = this.querySelector("[data-locked-list]");
    this.lockedSection = this.querySelector("[data-locked-section]");
    this.levelControl = this.querySelector("[data-level-control]");
    this.levelSelect = this.querySelector("[data-level]");
    this.feedback = this.querySelector("[data-feedback]");
    this.saveStatus = this.querySelector("[data-save-status]");
    this.recallButton = this.querySelector('[data-action="recall"]');
  }

  restore() {
    let stored = null;
    try {
      stored = JSON.parse(localStorage.getItem(this.storageKey) || "null");
    } catch {
      stored = null;
    }
    const normalized = stored
      ? normalizeAssignmentState(this.datasetDocument, stored)
      : { state: createDefaultAssignmentState(this.datasetDocument), corrections: [] };
    this.state = normalized.state;
    if (stored && normalized.corrections.length) {
      this.saveStatus.textContent = `已修正 ${normalized.corrections.length} 项旧配置`;
      this.save();
    } else {
      this.saveStatus.textContent = stored ? "已恢复本机岗位配置" : "新配置 · 尚未修改";
    }
  }

  bindControls() {
    this.addEventListener("click", (event) => {
      const character = event.target.closest("[data-character-id]");
      if (character && !character.disabled) {
        this.selectedCharacterId = character.dataset.characterId;
        this.setFeedback(`已选择 ${character.dataset.characterName}，请选择岗位槽位。`, "ready");
        this.render();
        return;
      }
      const slot = event.target.closest("[data-role-slot]");
      if (slot) {
        if (!this.selectedCharacterId) {
          this.setFeedback("请先选择一名角色。", "error");
          return;
        }
        this.moveSelected(slot.dataset.roleSlot);
        return;
      }
      const action = event.target.closest("[data-action]")?.dataset.action;
      if (action === "recall") this.moveSelected(STANDBY_ROLE);
      if (action === "standby-all") this.standbyAll(false);
      if (action === "restore") this.standbyAll(true);
    });
    this.querySelectorAll("[data-mode]").forEach((input) => {
      input.addEventListener("change", () => {
        if (!input.checked) return;
        const result = normalizeAssignmentState(this.datasetDocument, {
          ...this.state,
          mode: input.value
        });
        this.state = result.state;
        this.selectedCharacterId = null;
        this.save();
        this.render();
        this.setFeedback(
          result.corrections.length
            ? `模式已切换，${result.corrections.length} 名角色因新规则回到待机。`
            : input.value === "free"
              ? "已切换到自由预览：十名角色全部可用。"
              : `已切换到等级模拟 Lv.${this.state.level}。`,
          "success"
        );
      });
    });
    this.levelSelect?.addEventListener("change", () => {
      const result = normalizeAssignmentState(this.datasetDocument, {
        ...this.state,
        level: Number(this.levelSelect.value)
      });
      this.state = result.state;
      this.selectedCharacterId = null;
      this.save();
      this.render();
      this.setFeedback(
        result.corrections.length
          ? `等级已调整为 Lv.${this.state.level}，${result.corrections.length} 名角色回到待机。`
          : `等级已调整为 Lv.${this.state.level}。`,
        "success"
      );
    });
  }

  save() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.state));
      this.saveStatus.textContent = `已自动保存 · ${new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`;
    } catch {
      this.saveStatus.textContent = "本机保存不可用，本页仍可继续预览";
    }
  }

  moveSelected(role) {
    const selected = this.datasetDocument.records.find(
      (record) => record.id === this.selectedCharacterId
    );
    const result = assignCharacter(
      this.datasetDocument,
      this.state,
      this.selectedCharacterId,
      role
    );
    if (result.error) {
      this.setFeedback(ERROR_MESSAGES[result.error.code] ?? "当前操作不可用。", "error");
      return;
    }
    this.state = result.state;
    this.save();
    this.render();
    const roleName = role === STANDBY_ROLE
      ? "待机"
      : this.datasetDocument.assignmentStudio.roles.find((item) => item.id === role)?.name;
    this.setFeedback(`${selected?.name ?? "角色"} 已调整为${roleName}。`, "success");
  }

  standbyAll(reset) {
    const currentMode = this.state.mode;
    const currentLevel = this.state.level;
    this.state = createDefaultAssignmentState(this.datasetDocument, {
      mode: currentMode,
      level: currentLevel
    });
    this.selectedCharacterId = null;
    this.save();
    this.render();
    this.setFeedback(reset ? "已恢复当前模式的默认待机配置。" : "全部可用角色已回到待机。", "success");
  }

  characterButton(record, { locked = false } = {}) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "at-assignment-character";
    button.dataset.characterId = record.id;
    button.dataset.characterName = record.name;
    button.disabled = locked;
    button.classList.toggle("is-selected", record.id === this.selectedCharacterId);
    if (locked) button.classList.add("is-locked");
    const url = imageUrl(this.payload, record);
    if (url) {
      const image = document.createElement("img");
      image.src = url;
      image.alt = "";
      image.loading = "lazy";
      button.append(image);
    } else {
      const fallback = document.createElement("span");
      fallback.className = "at-assignment-character__fallback";
      fallback.textContent = record.name.slice(0, 1);
      button.append(fallback);
    }
    const body = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = record.name;
    const meta = document.createElement("small");
    meta.textContent = locked
      ? `Lv.${record.levelLimit} 解锁`
      : tendencyText(record) || "岗位倾向未记录";
    body.append(name, meta);
    button.append(body);
    return button;
  }

  render() {
    const context = assignmentContext(this.datasetDocument, this.state);
    this.querySelectorAll("[data-mode]").forEach((input) => {
      input.checked = input.value === this.state.mode;
    });
    this.levelControl.hidden = this.state.mode !== "level";
    this.levelSelect.value = String(this.state.level);
    this.recallButton.disabled = !this.selectedCharacterId;
    this.roleList.replaceChildren();

    for (const role of context.roles) {
      const row = document.createElement("article");
      row.className = `at-assignment-role at-assignment-role--${role.id}`;
      const header = document.createElement("header");
      const roleImage = role.imageKey
        ? this.payload.imageByKey[String(role.imageKey).toLocaleLowerCase("en-US")]
        : null;
      if (roleImage) {
        const image = document.createElement("img");
        image.src = roleImage;
        image.alt = "";
        header.append(image);
      }
      const title = document.createElement("div");
      const eyebrow = document.createElement("span");
      eyebrow.textContent = role.id.toUpperCase();
      const heading = document.createElement("h3");
      heading.textContent = role.name;
      title.append(eyebrow, heading);
      const occupants = this.datasetDocument.records.filter(
        (record) => this.state.assignments[record.id] === role.id
      );
      const count = document.createElement("strong");
      count.textContent = `${occupants.length}/${context.capacities[role.id]} 人`;
      header.append(title, count);
      const slots = document.createElement("div");
      slots.className = "at-assignment-slots";
      for (let index = 0; index < context.capacities[role.id]; index += 1) {
        const occupant = occupants[index];
        if (occupant) {
          slots.append(this.characterButton(occupant));
        } else {
          const empty = document.createElement("button");
          empty.type = "button";
          empty.className = "at-assignment-slot";
          empty.dataset.roleSlot = role.id;
          empty.innerHTML = "<span>＋</span><small>安排角色</small>";
          slots.append(empty);
        }
      }
      row.append(header, slots);
      this.roleList.append(row);
    }

    const unlocked = [];
    const locked = [];
    for (const record of this.datasetDocument.records) {
      const isLocked = this.state.mode === "level" && Number(record.levelLimit ?? 0) > this.state.level;
      if (isLocked) locked.push(record);
      else if (this.state.assignments[record.id] === STANDBY_ROLE) unlocked.push(record);
    }
    this.standbyList.replaceChildren(...unlocked.map((record) => this.characterButton(record)));
    this.lockedList.replaceChildren(...locked.map((record) => this.characterButton(record, { locked: true })));
    this.lockedSection.hidden = locked.length === 0;
  }

  setFeedback(message, tone) {
    this.feedback.textContent = message;
    this.feedback.dataset.tone = tone;
  }
}


export function defineAnonTokyoStaffAssignment() {
  if (!customElements.get("anon-tokyo-staff-assignment")) {
    customElements.define("anon-tokyo-staff-assignment", AnonTokyoStaffAssignmentElement);
  }
}
