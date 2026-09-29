const TOPIC_PANELS = new Set(["growth", "materials"]);

export function parseCardDialogState(search, availableSkillIds = []) {
  const params = new URLSearchParams(search);
  const panel = params.get("panel");

  if (TOPIC_PANELS.has(panel)) {
    return { panel, skillId: null };
  }

  if (panel === "skill") {
    const skillId = params.get("skill");
    if (skillId && availableSkillIds.includes(skillId)) {
      return { panel, skillId };
    }
  }

  return { panel: null, skillId: null };
}

/**
 * @param {string} path
 * @param {string | null} panel
 * @param {string | null} skillId
 */
export function cardDialogHref(path, panel, skillId = null) {
  const url = new URL(path, "https://archive.local");

  if (!panel) {
    return url.pathname;
  }

  const params = new URLSearchParams({ panel });
  if (panel === "skill" && skillId) {
    params.set("skill", skillId);
  }
  return `${url.pathname}?${params}`;
}
