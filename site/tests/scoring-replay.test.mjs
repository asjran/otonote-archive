import assert from "node:assert/strict";
import test from "node:test";

import {
  reconcileGoldenReplay,
  validateGoldenReplay
} from "../src/lib/scoring-replay.mjs";

const fixtureReplay = {
  schemaVersion: 1,
  sampleId: "fixture-core-rounding",
  sourceReleaseId: "release-1",
  ruleSetVersion: "scoring-fixture-v1",
  verificationStatus: "fixture",
  sourceEvidence: ["worked-example"],
  formation: { totalPower: 12_345 },
  judgements: [],
  scoreCommands: [],
  chart: {
    events: [
      {
        id: "note-1",
        notePercent: 10,
        judgementPercent: 100,
        comboPercent: 100,
        scorePercent: 120,
        fixedScore: 7
      },
      {
        id: "note-2",
        notePercent: 10,
        judgementPercent: 90,
        comboPercent: 110,
        scorePercent: 100,
        fixedScore: 0
      }
    ]
  },
  expected: {
    finalScore: 2_708,
    noteScores: [1_487, 1_221]
  }
};

test("validates a versioned Golden Replay through the public replay interface", () => {
  assert.deepEqual(validateGoldenReplay(fixtureReplay), []);
});

test("rejects a client replay without attributable evidence", () => {
  const issues = validateGoldenReplay({
    ...fixtureReplay,
    verificationStatus: "reconciled",
    sourceEvidence: []
  });

  assert.deepEqual(
    issues.map((issue) => issue.code),
    ["client_evidence_required"]
  );
});

test("requires explicit judgement and score-command timelines", () => {
  const { judgements: _judgements, scoreCommands: _commands, ...incomplete } =
    fixtureReplay;
  const issues = validateGoldenReplay(incomplete);

  assert.deepEqual(
    issues.map((issue) => `${issue.code}:${issue.path}`),
    ["required_array:judgements", "required_array:scoreCommands"]
  );
});

test("reconciles a worked integer example with two explicit floor stages", () => {
  const result = reconcileGoldenReplay(fixtureReplay);

  assert.equal(result.status, "matched_fixture");
  assert.equal(result.formal, false);
  assert.equal(result.score, 2_708);
  assert.deepEqual(
    result.trace.map((entry) => ({
      id: entry.eventId,
      floorAfterBase: entry.floorAfterBase,
      floorAfterFactors: entry.floorAfterFactors,
      score: entry.score
    })),
    [
      { id: "note-1", floorAfterBase: 1_234, floorAfterFactors: 1_480, score: 1_487 },
      { id: "note-2", floorAfterBase: 1_234, floorAfterFactors: 1_221, score: 1_221 }
    ]
  );
});

test("reports the first integer mismatch without promoting the replay", () => {
  const result = reconcileGoldenReplay({
    ...fixtureReplay,
    expected: { ...fixtureReplay.expected, finalScore: 2_709 }
  });

  assert.equal(result.status, "mismatch");
  assert.equal(result.formal, false);
  assert.equal(result.difference.expected, 2_709);
  assert.equal(result.difference.actual, 2_708);
});
