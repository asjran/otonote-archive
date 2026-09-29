const missions = { 1: "combo", 2: "luck", 3: "just" };
const liveCategories = { 1: "simple", 2: "life", 3: "judgement" };
export const SKILL_FILTER_NAMES = ["skill-role", "live-type", "gekisou-type", "gekisou-effect"];

// Classify the effect, not words in the description: a LIFE threshold is not
// healing, and a PERFECT score bonus is not judgement assistance.
const normalEffects = new Map([
  [2000, "score"], [2001, "score"], [2004, "score"], [15000, "score"],
  [3001, "heal"], [12006, "judge"], [4004, "judge"]
]);
const effectLabels = {
  2000: ["得分提升", "Score boost"],
  2001: ["累计得分提升", "Cumulative score boost"],
  4004: ["判定范围扩大", "Wider judgement window"],
  11001: ["抽选条累积量提升", "LUCK gauge gain boost"],
  11002: ["点数增加", "Points gain"],
  11003: ["抽选条直接累积", "Immediate LUCK gauge gain"],
  11005: ["抽选结果保底", "Guaranteed LUCK result"],
  12000: ["获得量提升", "Gain boost"],
  12004: ["连击保护", "Combo protection"],
  12006: ["判定转化", "Judgement conversion"],
  13000: ["获得量提升", "Gain boost"],
  13002: ["累计获得量提升", "Cumulative gain boost"],
  13005: ["转化为 JUST", "Convert to JUST"]
};

/**
 * Build server-rendered facets from structured skill effects at every level.
 * Leader skills deliberately do not determine a card's live/support role.
 * @param {Array<{cardId: string, skillRefs: Array<{skillId: string}>}>} projections
 * @param {Array<import('./game-database').SkillDefinition>} skills
 * @param {string} locale
 * @param {"member" | "support" | "archive"} mode
 */
export function buildCardSkillFilters(projections, skills, locale = "zh-CN", mode = "support") {
  const en = locale === "en";
  const definitions = new Map(skills.map(skill => [skill.id, skill]));
  const effectOptions = new Map();
  const records = new Map();
  let hasOther = false;
  let hasOtherLive = false;
  for (const projection of projections) {
    const normal = new Set();
    const live = new Set();
    const mission = new Set();
    const gekisouEffects = new Set();
    for (const ref of projection.skillRefs) {
      const skill = definitions.get(ref.skillId);
      if (!skill) continue;
      const effects = skill.levels.flatMap(level => level.effects);
      if (skill.kind === "live") {
        // Master LiveSkill categories: Simple=1, Life=2, Judgement=3.
        const categories = skill.categoryCodes?.length ? skill.categoryCodes : [0];
        for (const code of categories) {
          const category = liveCategories[code] ?? "other";
          live.add(category);
          if (category === "other") hasOtherLive = true;
        }
      } else if (skill.kind === "support") {
        for (const effect of effects) {
          const role = normalEffects.get(effect.effectType) ?? "other";
          normal.add(role);
          if (role === "other") hasOther = true;
        }
      } else if (skill.kind === "gekisou" || skill.kind === "gekisou_support") {
        const type = missions[skill.missionTypeCode];
        if (!type) continue;
        mission.add(type);
        for (const effect of effects) {
          // Scope effects to their mission, including shared score effect codes.
          const value = `${type}:${effect.effectType}`;
          gekisouEffects.add(value);
          const label = effectLabels[effect.effectType]?.[en ? 1 : 0]
            ?? effect.effectName ?? String(effect.effectType);
          effectOptions.set(value, { value, label: `${type.toUpperCase()} · ${label}` });
        }
      }
    }
    records.set(projection.cardId, {
      "skill-role": [...normal],
      "live-type": [...live],
      "gekisou-type": [...mission],
      "gekisou-effect": [...gekisouEffects]
    });
  }
  const normalOptions = [
    { value: "heal", label: en ? "Healer (LIFE recovery)" : "奶卡（生命回复）" },
    { value: "judge", label: en ? "Judgement assist" : "判卡（判定辅助）" },
    { value: "score", label: en ? "Scorer / skill duration" : "分卡（得分／技能延长）" }
  ];
  if (hasOther) normalOptions.push({ value: "other", label: en ? "Other effects" : "其他效果" });
  const liveOptions = [
    { value: "simple", label: en ? "Pure score boost" : "纯加分" },
    { value: "judgement", label: en ? "Judgement-based score boost" : "判定条件加分" },
    { value: "life", label: en ? "LIFE-based score boost" : "血量条件加分" }
  ];
  if (hasOtherLive) liveOptions.push({ value: "other", label: en ? "Other categories" : "其他类型" });
  return {
    records,
    facets: [
      ...(mode !== "member" ? [{ name: "skill-role", label: en ? "Support skill" : "支援技能", options: normalOptions }] : []),
      ...(mode !== "support" ? [{ name: "live-type", label: en ? "Live skill" : "演出技能", options: liveOptions }] : []),
      { name: "gekisou-type", label: en ? "Gekisou type" : "激奏类型", options: ["just", "luck", "combo"].map(value => ({ value, label: value.toUpperCase() })) },
      { name: "gekisou-effect", label: en ? "Gekisou effect" : "激奏效果", options: [...effectOptions.values()].sort((a, b) => a.value.localeCompare(b.value, "en", { numeric: true })) }
    ]
  };
}

/** @param {Array<import('./game-database').SkillDefinition>} skills */
export function buildSkillArchiveFilters(skills, locale = "zh-CN") {
  return buildCardSkillFilters(
    skills.map(skill => ({ cardId: skill.id, skillRefs: [{ skillId: skill.id }] })),
    skills, locale, "archive"
  );
}
