import assert from "node:assert/strict";
import test from "node:test";

import {
  GEKISOU_RULE_SET,
  createGekisouScenario,
  compileGekisouEvents,
  runGekisouResearchSimulation,
  validateGekisouScenario
} from "../src/lib/gekisou-simulation.mjs";

const track = {
  id: "music-100008",
  title: "Test Track",
  gekisouMissions: [
    { index: 1, typeCode: 1, type: "combo", label: "COMBO" },
    { index: 2, typeCode: 2, type: "luck", label: "LUCK" },
    { index: 3, typeCode: 3, type: "just", label: "JUST" }
  ]
};

const chart = {
  id: "music-chart-10000803",
  trackId: track.id,
  difficulty: "expert",
  duration: 90,
  skillTimings: [10, 45],
  feverRanges: [
    { start: 10, end: 20 },
    { start: 30, end: 40 },
    { start: 50, end: 60 }
  ]
};

test("creates a deterministic release-bound scenario with one to five equal participants", () => {
  const first = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 5
  });
  const second = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 5
  });

  assert.equal(first.ruleSetVersion, GEKISOU_RULE_SET.id);
  assert.equal(first.participants.length, 5);
  assert.deepEqual(first.participants.map((entry) => entry.id), [
    "participant-1",
    "participant-2",
    "participant-3",
    "participant-4",
    "participant-5"
  ]);
  assert.equal(first.focusedParticipantId, "participant-1");
  assert.equal(first.scenarioHash, second.scenarioHash);
  assert.deepEqual(validateGekisouScenario(first), []);
});

test("rejects participant counts outside the client room boundary", () => {
  const empty = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 0
  });
  const tooMany = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 6
  });

  assert.equal(validateGekisouScenario(empty)[0].code, "invalid_participant_count");
  assert.equal(validateGekisouScenario(tooMany)[0].code, "invalid_participant_count");
});

test("compiles three fixed ranges and chart skill markers in stable time order", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 2
  });
  const events = compileGekisouEvents(scenario);

  assert.deepEqual(
    events.map((event) => [event.time, event.kind, event.segmentIndex ?? null]),
    [
      [10, "gekisou-range-start", 1],
      [10, "skill-marker", null],
      [20, "gekisou-range-end", 1],
      [30, "gekisou-range-start", 2],
      [40, "gekisou-range-end", 2],
      [45, "skill-marker", null],
      [50, "gekisou-range-start", 3],
      [60, "gekisou-range-end", 3]
    ]
  );
  assert.equal(events[0].mission.type, "combo");
  assert.equal(events[6].mission.type, "just");
});

test("rules mode exposes structural ledger while keeping unverified scores blocked", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 2
  });
  const first = runGekisouResearchSimulation(scenario);
  const second = runGekisouResearchSimulation(scenario);

  assert.equal(first.status, "blocked");
  assert.equal(first.scoreStatus, "unavailable");
  assert.equal(first.participants[0].score, null);
  assert.equal(first.optimizerEligible, false);
  assert.deepEqual(first.blockers, ["score_formula_unverified"]);
  assert.equal(first.ledger.length, 8);
  assert.equal(first.ledgerHash, second.ledgerHash);
});

test("experiment mode applies explicit score deltas with contribution conservation", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 2,
    mode: "experiment",
    counterfactualOverrides: [
      {
        id: "override-1",
        kind: "score-delta",
        time: 12,
        participantId: "participant-1",
        amount: 100,
        owner: { kind: "card", id: "member-card-1" }
      },
      {
        id: "override-2",
        kind: "score-delta",
        time: 13,
        participantId: "participant-2",
        amount: 150,
        owner: { kind: "skill", id: "gekisou-skill-2" }
      },
      {
        id: "override-3",
        kind: "score-delta",
        time: 35,
        participantId: "participant-1",
        amount: 80,
        owner: { kind: "card", id: "member-card-1" }
      }
    ]
  });
  const result = runGekisouResearchSimulation(scenario);

  assert.equal(result.status, "experimental");
  assert.equal(result.scoreStatus, "counterfactual-only");
  assert.deepEqual(
    result.participants.map((entry) => [entry.id, entry.score, entry.finalRank]),
    [
      ["participant-1", 180, 1],
      ["participant-2", 150, 2]
    ]
  );
  assert.equal(result.segments[0].ranking[0].participantId, "participant-2");
  assert.equal(result.segments[1].ranking[0].participantId, "participant-1");
  assert.equal(result.participants[0].contributions[0].amount, 180);
  assert.equal(
    result.participants[0].contributions.reduce((sum, entry) => sum + entry.amount, 0),
    result.participants[0].score
  );
  assert.equal(result.evidence.overall, "counterfactual");
});

test("rules mode rejects counterfactual overrides instead of silently applying them", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 1,
    counterfactualOverrides: [
      {
        id: "override-1",
        kind: "score-delta",
        time: 12,
        participantId: "participant-1",
        amount: 100
      }
    ]
  });
  const result = runGekisouResearchSimulation(scenario);

  assert.equal(result.status, "invalid_input");
  assert.equal(result.issues[0].code, "illegal_override");
  assert.equal(result.scoreStatus, "unavailable");
});
