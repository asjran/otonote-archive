import assert from "node:assert/strict";
import test from "node:test";

import { optimizeFormations } from "../src/lib/formation-optimizer.mjs";

const members = [
  { id: "m1", cheapScore: 100 },
  { id: "m2", cheapScore: 80 },
  { id: "m3", cheapScore: 60 }
];
const supports = [
  { id: "s1", cheapScore: 30 },
  { id: "s2", cheapScore: 20 },
  { id: "s3", cheapScore: 10 }
];

test("refuses to optimize against an unverified formation rule profile", async () => {
  const result = await optimizeFormations({
    members,
    supports,
    ruleProfile: { verificationStatus: "research", slotCount: 2 },
    exactScore: async () => 0
  });

  assert.deepEqual(result, {
    status: "blocked",
    reason: "formation_rules_not_reconciled",
    results: []
  });
});

test("uses deterministic beam prefiltering before exact Top N scoring", async () => {
  const exactInputs = [];
  const result = await optimizeFormations({
    members,
    supports,
    ruleProfile: {
      id: "fixture-formation-v1",
      verificationStatus: "reconciled",
      slotCount: 2,
      allowMemberDuplicates: false,
      allowSupportDuplicates: false
    },
    prefilterLimit: 3,
    topN: 2,
    exactScore: async (formation) => {
      exactInputs.push(formation.id);
      return formation.slots.reduce(
        (total, slot) => total + slot.member.cheapScore + slot.support.cheapScore,
        0
      );
    }
  });

  assert.equal(result.status, "budget_exhausted");
  assert.equal(result.generatedCount > result.exactCount, true);
  assert.equal(result.exactCount, 3);
  assert.equal(result.results.length, 2);
  assert.equal(result.results[0].score, 230);
  assert.deepEqual(
    result.results[0].slots.map((slot) => [slot.member.id, slot.support.id]),
    [["m1", "s1"], ["m2", "s2"]]
  );
  assert.deepEqual(exactInputs, [...exactInputs].sort());
});

test("honors cancellation before exact scoring", async () => {
  const controller = new AbortController();
  controller.abort();
  const result = await optimizeFormations({
    members,
    supports,
    ruleProfile: {
      id: "fixture-formation-v1",
      verificationStatus: "reconciled",
      slotCount: 2,
      allowMemberDuplicates: false,
      allowSupportDuplicates: false
    },
    signal: controller.signal,
    exactScore: async () => 0
  });

  assert.equal(result.status, "cancelled");
  assert.deepEqual(result.results, []);
});

test("exhaustive search finds a cross-pairing and leader order that sorted pairing misses", async () => {
  const result = await optimizeFormations({
    members: [{ id: "m1" }, { id: "m2" }],
    supports: [{ id: "s1" }, { id: "s2" }],
    ruleProfile: {
      id: "fixture-formation-v1",
      verificationStatus: "reconciled",
      slotCount: 2,
      allowMemberDuplicates: false,
      allowSupportDuplicates: false
    },
    prefilterLimit: 8,
    exactScore: (formation) => formation.id === "m2+s1|m1+s2" ? 999 : 1
  });

  assert.equal(result.status, "completed");
  assert.equal(result.totalCandidateCount, "4");
  assert.equal(result.generatedCount, 4);
  assert.equal(result.exactCount, 4);
  assert.equal(result.results[0].id, "m2+s1|m1+s2");
  assert.equal(result.results[0].score, 999);
});

test("candidate cap reports an incomplete search instead of claiming a maximum", async () => {
  const result = await optimizeFormations({
    members: [{ id: "m1" }, { id: "m2" }],
    supports: [{ id: "s1" }, { id: "s2" }],
    ruleProfile: {
      id: "fixture-formation-v1",
      verificationStatus: "reconciled",
      slotCount: 2,
      allowMemberDuplicates: false,
      allowSupportDuplicates: false
    },
    maxGeneratedCandidates: 2,
    prefilterLimit: 2,
    exactScore: () => 1
  });

  assert.equal(result.status, "budget_exhausted");
  assert.equal(result.generatedCount, 2);
  assert.equal(result.totalCandidateCount, "4");
});
