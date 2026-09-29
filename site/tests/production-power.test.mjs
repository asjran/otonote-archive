import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createFormationCalculator } from "../src/lib/scoring-rules/formation-power.mjs";
import { optimizeProductionPairing } from "../src/lib/production-optimizer.mjs";
import { createTeamDraft, parseTeamDraftSearch, serializeTeamDraftSearch } from "../src/lib/team-draft.mjs";

const rules = JSON.parse(readFileSync(new URL("../src/data/formal-scoring-rules.json", import.meta.url)));
const calculator = createFormationCalculator(rules);
const draft = () => createTeamDraft({ slots: Array.from({ length: 5 }, (_, i) => ({
  memberCardId: `member-card-${i + 1}`, supportCardId: `support-card-${i + 1}`
})), selectedSongId: "music-100001", modifiers: { tgwCardRank: 2 } });

test("current catalog IDs resolve and all released cards have supported growth and power effects", () => {
  const instruments = Object.fromEntries(rules.tables.BandItem.map((r) => [r._id, 30]));
  for (const member of rules.tables.MemberCard) {
    const d = createTeamDraft({ slots: [null, null, { memberCardId: `member-card-${member._id}` }],
      modifiers: { bandItems: instruments, growth: { [`member-card-${member._id}`]: { rank: 5, awake: 5 } } } });
    assert.ok(calculator.calculate(d).total.total > 0);
  }
  for (const support of rules.tables.SupportCard) {
    assert.ok(calculator.resolveGrowth(support, "Support", { rank: 5 }).values.every(Number.isInteger));
  }
});

test("manual native-rule fixture: support is a rate; each source floors the SAME bonus base", () => {
  const r = structuredClone(rules), t = r.tables;
  Object.assign(t.MemberCard[0], { _performancePowerMax: 101, _technicPowerMax: 203, _visualPowerMax: 307 });
  Object.assign(t.SupportCard[0], { _performancePowerMax: 1000, _technicPowerMax: 2000, _visualPowerMax: 3000 });
  for (const name of ["MemberCardLevel", "SupportCardLevel"]) for (const row of t[name]) {
    row._performanceRate = row._technicRate = row._visualRate = 10000;
  }
  for (const name of ["MemberCardRank", "MemberCardAwake"]) for (const row of t[name]) {
    row._performanceRate = row._technicRate = row._visualRate = 0;
  }
  t.CharacterRank.find((r) => r._rank === 2)._bonus = 5;
  t.CharacterTotalRank = [{ _totalRank: 25, _bonus: 2 }];
  t.LeaderSkillEffect = [{ _id: 1, _leaderSkillID: t.MemberCard[0]._leaderSkillID, _level: 1,
    _skillTargetIDs: [], _skillEffectType: 1000, _effectValue: 1000 }];
  const d = createTeamDraft({ slots: [null, null, { memberCardId: "member-card-1", supportCardId: "support-card-1" }],
    modifiers: { characterRanks: { 1: 2 }, memoryPoints: { 1: 3 }, tgwCardRank: 2 } });
  const result = createFormationCalculator(r).calculate(d);
  assert.deepEqual(result.slots[2].bonusBase, { performance: 111, technic: 213, visual: 317, total: 641 });
  assert.deepEqual(result.breakdown.support, { performance: 11, technic: 42, visual: 95, total: 148 });
  assert.equal(result.breakdown.leader.total, 63); // 11 + 21 + 31
  assert.equal(result.breakdown.typeLink.total, 30); // 5 + 10 + 15
  assert.equal(result.breakdown.tgw.total, 6); // 1 + 2 + 3 (doesn't compound other bonuses)
  assert.equal(result.total.total, 888); // 641 + 148 + 63 + 30 + 6
});

test("music type follows member attribute, not the character band", () => {
  const result = calculator.calculate(draft());
  assert.deepEqual(result.slots.map((s) => s.ratesBP.musicType[0]), [0, 500, 0, 0, 0]);
  assert.ok(result.slots.every((s) => s.ratesBP.musicTag[0] === 500));
  assert.equal(result.leaderSlotIndex, 2);
});

test("invalid releases, levels, duplicates and unsupported effects fail closed", () => {
  assert.throws(() => calculator.calculate(draft(), { sourceReleaseId: "other" }), /release_mismatch/);
  const bad = draft(); bad.slots[1].memberCardId = bad.slots[0].memberCardId;
  assert.throws(() => calculator.calculate(bad), /Duplicate/);
  const level = draft(); level.modifiers.growth = { "member-card-1": { level: 999 } };
  assert.throws(() => calculator.calculate(level), /level/);
  const malformed = draft(); malformed.modifiers.bandItems = "bad";
  assert.throws(() => calculator.calculate(malformed), /settings/);
  assert.throws(() => calculator.effectRates(rules.tables.MemberCard[0], [{
    _id: 1, _skillConditionGroup: 999, _skillTargetIDs: [], _skillEffectType: 1000, _effectValue: 500
  }]), /conditional/);
});

test("growth, account ranks, memory and instruments survive share URL", () => {
  const d = draft(); Object.assign(d.modifiers, { growth: { "member-card-1": { rank: 3, awake: 2, level: 20 } },
    characterRanks: { 1: 10, 25: 20 }, memoryPoints: { 1: 30 }, bandItems: { 101: 10 } });
  const restored = parseTeamDraftSearch(serializeTeamDraftSearch(d)).draft;
  assert.deepEqual(restored, d);
  assert.deepEqual(calculator.calculate(restored), calculator.calculate(d));
  assert.ok(parseTeamDraftSearch("?modifiers=%5B%5D").issues.some((r) => r.code === "invalid_modifiers"));
});

test("pairing search exhausts 600 unique candidates, keeps growth and produces reproducible top N", async () => {
  const d = draft(); d.modifiers.growth = { "member-card-1": { rank: 5, awake: 5 }, "support-card-3": { rank: 5 } };
  const original = structuredClone(d);
  const all = await optimizeProductionPairing({ rules, draft: d, topN: 600, yieldControl: async () => {} });
  assert.equal(all.evaluated, 600);
  assert.equal(new Set(all.results.map((r) => r.id)).size, 600);
  assert.equal(all.objective, "formation_power");
  assert.deepEqual(d, original);
  assert.ok(all.results[0].power >= all.baseline);
  for (const result of all.results) assert.equal(calculator.calculate(result.draft).total.total, result.power);
  const top = await optimizeProductionPairing({ rules, draft: d, topN: 5, yieldControl: async () => {} });
  assert.deepEqual(top.results, all.results.slice(0, 5));
});

test("cancelled search exposes no partial ranking as a complete optimum", async () => {
  const controller = new AbortController();
  const result = await optimizeProductionPairing({ rules, draft: draft(), signal: controller.signal,
    onProgress: () => controller.abort(), yieldControl: async () => {} });
  assert.equal(result.status, "cancelled");
  assert.equal(result.evaluated, 20);
  assert.deepEqual(result.results, []);
});
