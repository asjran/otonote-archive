import assert from "node:assert/strict";
import test from "node:test";

import {
  compileGekisouEvents,
  createGekisouScenario,
  runGekisouResearchSimulation,
  validateGekisouScenario
} from "../src/lib/gekisou-simulation.mjs";

const track = {
  id: "music-1",
  title: "Input Test",
  gekisouMissions: [
    { index: 1, typeCode: 1, type: "combo", label: "COMBO" },
    { index: 2, typeCode: 2, type: "luck", label: "LUCK" },
    { index: 3, typeCode: 3, type: "just", label: "JUST" }
  ]
};

const chart = {
  id: "chart-1",
  trackId: track.id,
  difficulty: "expert",
  duration: 40,
  skillTimings: [5, 20],
  feverRanges: [
    { start: 4, end: 10 },
    { start: 14, end: 20 },
    { start: 24, end: 30 }
  ],
  comboEvents: [
    { markerId: "note-1", noteId: "note-1", time: 5, combo: 1 },
    { markerId: "note-2", noteId: "note-2", time: 8, combo: 2 },
    { markerId: "note-3", noteId: "note-3", time: 16, combo: 3 },
    { markerId: "note-4", noteId: "note-4", time: 26, combo: 4 }
  ]
};

test("expands AP, segment overrides, and note exceptions into deterministic input events", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participants: [{
      id: "p1",
      performancePlan: {
        preset: "custom",
        segmentOverrides: [
          { segmentIndex: 1, judgement: "great", comboBreak: false }
        ],
        noteOverrides: [
          { markerId: "note-2", judgement: "miss", comboBreak: true }
        ]
      }
    }]
  });

  assert.deepEqual(validateGekisouScenario(scenario), []);
  const events = compileGekisouEvents(scenario)
    .filter((event) => event.kind === "performance-judgement");
  assert.deepEqual(events.map((event) => [
    event.markerId,
    event.judgement,
    event.comboBreak,
    event.segmentIndex
  ]), [
    ["note-1", "great", false, 1],
    ["note-2", "miss", true, 1],
    ["note-3", "hit", false, 2],
    ["note-4", "hit", false, 3]
  ]);
  assert.equal(events[1].evidenceStatus, "user-input");
});

test("summarizes input performance without turning it into an official score", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participants: [{
      id: "p1",
      performancePlan: {
        preset: "ap",
        noteOverrides: [
          { markerId: "note-2", judgement: "miss", comboBreak: true }
        ]
      }
    }]
  });
  const result = runGekisouResearchSimulation(scenario);

  assert.equal(result.status, "blocked");
  assert.equal(result.participants[0].score, null);
  assert.deepEqual(result.participants[0].performance, {
    totalJudgements: 4,
    comboBreakCount: 1,
    maxCombo: 2,
    judgementCounts: { perfect: 3, miss: 1 }
  });
  assert.equal(result.segments[0].performance[0].comboBreakCount, 1);
});

test("records fixed LUCK input only on a LUCK segment", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participantCount: 2,
    randomnessPlan: {
      mode: "fixed",
      seed: 17,
      outcomes: [
        { id: "luck-1", participantId: "participant-2", segmentIndex: 2, value: 73 }
      ]
    }
  });
  assert.deepEqual(validateGekisouScenario(scenario), []);
  const result = runGekisouResearchSimulation(scenario);
  assert.deepEqual(result.segments[1].luckInputs, [
    { participantId: "participant-2", value: 73, evidenceStatus: "user-input" }
  ]);

  const invalid = structuredClone(scenario);
  invalid.randomnessPlan.outcomes[0].segmentIndex = 1;
  assert.equal(validateGekisouScenario(invalid)[0].code, "invalid_luck_segment");
});

test("compiles an explicit experimental skill activation with attributed score", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    mode: "experiment",
    participants: [{
      id: "p1",
      teamDraft: {
        slots: [{ memberCardId: "member-card-1" }]
      },
      skillBranches: [{
        id: "branch-1",
        skillId: "gekisou-skill-21",
        sourceCardId: "member-card-1",
        markerIndex: 1,
        durationSeconds: 4,
        experimentalScoreDelta: 250
      }]
    }]
  });
  assert.deepEqual(validateGekisouScenario(scenario), []);
  const result = runGekisouResearchSimulation(scenario);

  assert.equal(result.participants[0].score, 250);
  assert.deepEqual(result.participants[0].contributions, [{
    owner: { kind: "skill", id: "gekisou-skill-21", sourceCardId: "member-card-1" },
    amount: 250
  }]);
  assert.deepEqual(
    result.ledger
      .filter((event) => event.eventId.startsWith("branch-1"))
      .map((event) => [event.kind, event.time, event.scoreDelta]),
    [
      ["experimental-skill-start", 5, 0],
      ["experimental-skill-score", 5, 250],
      ["experimental-skill-end", 9, 0]
    ]
  );
});

test("rejects experimental skill score input in rules mode", () => {
  const scenario = createGekisouScenario({
    sourceReleaseId: "release-1",
    track,
    chart,
    participants: [{
      id: "p1",
      skillBranches: [{
        skillId: "gekisou-skill-21",
        markerIndex: 1,
        experimentalScoreDelta: 100
      }]
    }]
  });
  assert.ok(validateGekisouScenario(scenario).some((entry) =>
    entry.code === "illegal_experimental_skill"
  ));
});
