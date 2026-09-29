import assert from "node:assert/strict";
import test from "node:test";
import { buildCardSkillFilters, buildSkillArchiveFilters } from "../src/lib/card-skill-filtering.mjs";
import { evaluateFacets, facetParams, selectedFacetsFromParams } from "../src/lib/faceted-filter.mjs";

const skill = (id, kind, types, missionTypeCode = 0) => ({
  id, kind, missionTypeCode,
  levels: [{ effects: types.map(effectType => ({ effectType, effectName: `Effect ${effectType}` })) }]
});
const projection = (cardId, ...ids) => ({ cardId, skillRefs: ids.map(skillId => ({ skillId })) });

test("roles use effects, exclude leaders, and retain multiple roles", () => {
  const { records } = buildCardSkillFilters([
    projection("life-score", "life-threshold"),
    projection("perfect-score", "perfect-score"),
    projection("duration", "extend"),
    projection("mixed", "heal", "judge", "leader"),
    projection("missing", "unavailable")
  ], [
    skill("life-threshold", "live", [2000]),
    skill("perfect-score", "live", [2004]),
    skill("extend", "support", [15000]),
    skill("heal", "support", [3001]),
    skill("judge", "support", [12006]),
    skill("leader", "leader", [2000])
  ]);
  for (const id of ["life-score", "perfect-score"]) assert.deepEqual(records.get(id)["skill-role"], []);
  assert.deepEqual(records.get("duration")["skill-role"], ["score"]);
  assert.deepEqual(records.get("mixed")["skill-role"], ["heal", "judge"]);
  assert.deepEqual(records.get("missing")["skill-role"], []);
});

test("mission codes match the client and effects are scoped to their mission", () => {
  const { records, facets } = buildCardSkillFilters([
    projection("combo", "c"), projection("luck", "l"), projection("just", "j")
  ], [skill("c", "gekisou", [12000], 1), skill("l", "gekisou_support", [2000], 2), skill("j", "gekisou_support", [2000, 13005], 3)]);
  assert.deepEqual(records.get("combo")["gekisou-type"], ["combo"]);
  assert.deepEqual(records.get("luck")["gekisou-type"], ["luck"]);
  assert.deepEqual(records.get("just")["gekisou-type"], ["just"]);
  assert.deepEqual(records.get("just")["skill-role"], []);
  assert.deepEqual(records.get("luck")["gekisou-effect"], ["luck:2000"]);
  assert.deepEqual(records.get("just")["gekisou-effect"], ["just:2000", "just:13005"]);
  assert.equal(facets[2].options.find(x => x.value === "just:13005").label, "JUST · 转化为 JUST");
});

test("all levels are considered, duplicates removed, and unknown effects stay explicit", () => {
  const mixed = skill("mixed", "support", [2000]);
  mixed.levels.push({ effects: [{ effectType: 2000 }, { effectType: 3001 }, { effectType: 99999 }] });
  const result = buildCardSkillFilters([projection("card", "mixed")], [mixed], "en");
  assert.deepEqual(result.records.get("card")["skill-role"], ["score", "heal", "other"]);
  assert.equal(result.facets[0].options.at(-1).label, "Other effects");
});

test("member live skills classify by category instead of collapsing every scorer", () => {
  const definitions = [
    { ...skill("pure", "live", [2000]), categoryCodes: [1] },
    { ...skill("life", "live", [2000]), categoryCodes: [2] },
    { ...skill("perfect", "live", [2004]), categoryCodes: [3] },
    { ...skill("mixed", "live", [2000, 2004]), categoryCodes: [2, 3] },
    { ...skill("unknown", "live", [2000]), categoryCodes: [99] }
  ];
  const result = buildCardSkillFilters(definitions.map(s => projection(s.id, s.id)), definitions, "zh-CN", "member");
  assert.deepEqual(result.records.get("pure")["live-type"], ["simple"]);
  assert.deepEqual(result.records.get("life")["live-type"], ["life"]);
  assert.deepEqual(result.records.get("perfect")["live-type"], ["judgement"]);
  assert.deepEqual(result.records.get("mixed")["live-type"], ["life", "judgement"]);
  assert.deepEqual(result.records.get("unknown")["live-type"], ["other"]);
  assert.deepEqual(result.facets.map(f => f.name), ["live-type", "gekisou-type", "gekisou-effect"]);
  assert.deepEqual(result.facets[0].options.slice(0, 3).map(o => o.label), ["纯加分", "判定条件加分", "血量条件加分"]);
});

test("archive and cards share support roles and mission types without mixing skill kinds", () => {
  const definitions = [skill("heal", "support", [3001]), skill("judge", "support", [12006]), skill("extend", "support", [15000]),
    { ...skill("perfect", "live", [2004]), categoryCodes: [3] },
    skill("just", "gekisou", [13000], 3), skill("luck", "gekisou_support", [2000], 2)];
  const archive = buildSkillArchiveFilters(definitions);
  const cards = buildCardSkillFilters(definitions.map(s => projection(s.id, s.id)), definitions);
  assert.deepEqual(archive.records, cards.records);
  assert.deepEqual(archive.records.get("heal")["skill-role"], ["heal"]);
  assert.deepEqual(archive.records.get("judge")["skill-role"], ["judge"]);
  assert.deepEqual(archive.records.get("extend")["skill-role"], ["score"]);
  assert.deepEqual(archive.records.get("perfect")["skill-role"], []);
  assert.deepEqual(archive.records.get("luck")["skill-role"], []);
  assert.deepEqual(archive.facets.map(f => f.name), ["skill-role", "live-type", "gekisou-type", "gekisou-effect"]);
});

test("skill facets combine with existing filters and survive URL restoration", () => {
  const result = buildCardSkillFilters([
    projection("a", "heal", "just"), projection("b", "judge", "just"), projection("c", "heal", "luck")
  ], [skill("heal", "support", [3001]), skill("judge", "support", [12006]), skill("just", "gekisou_support", [13005], 3), skill("luck", "gekisou_support", [2000], 2)]);
  const records = [...result.records].map(([id, facets]) => ({ id, search: id, facets: { ...facets, rarity: ["3"] } }));
  const selected = { "skill-role": ["heal"], "gekisou-type": ["just"], "gekisou-effect": ["just:13005"], rarity: ["3"] };
  const restored = selectedFacetsFromParams(facetParams({ selected }), Object.keys(selected));
  assert.deepEqual(restored, selected);
  assert.deepEqual(evaluateFacets(records, { selected: restored }).records.map(x => x.id), ["a"]);
  assert.equal(evaluateFacets(records, { selected: { "skill-role": ["heal", "judge"] } }).records.length, 3);
  assert.equal(evaluateFacets(records).records.length, 3);
});
