import assert from "node:assert/strict";
import test from "node:test";

import {
  TEAM_DRAFT_SCHEMA_VERSION,
  TEAM_RULE_SET,
  createTeamDraft,
  deriveTeamDraftSummary,
  parseTeamDraftSearch,
  serializeTeamDraftSearch,
  validateTeamDraft
} from "../src/lib/team-draft.mjs";

const memberCards = [
  {
    id: "member-card-1",
    characterId: "character-1",
    performancePowerMax: 100,
    technicPowerMax: 200,
    visualPowerMax: 300
  },
  {
    id: "member-card-2",
    characterId: "character-2",
    performancePowerMax: 400,
    technicPowerMax: 500,
    visualPowerMax: 600
  }
];

const supportCards = [
  {
    id: "support-card-1",
    performancePowerMax: 10,
    technicPowerMax: 20,
    visualPowerMax: 30
  }
];

const projections = [
  {
    cardId: "member-card-1",
    skillSummaries: [{ skillId: "live-skill-1", name: "Score Up" }]
  },
  {
    cardId: "support-card-1",
    skillSummaries: [{ skillId: "support-skill-1", name: "Support Up" }]
  }
];

test("creates a versioned five-position formation draft", () => {
  const draft = createTeamDraft();

  assert.equal(draft.schemaVersion, TEAM_DRAFT_SCHEMA_VERSION);
  assert.equal(draft.ruleSetVersion, TEAM_RULE_SET.id);
  assert.equal(TEAM_RULE_SET.officialSlotCount, 5);
  assert.equal(draft.slots.length, 5);
  assert.deepEqual(
    draft.slots,
    Array.from({ length: 5 }, () => ({
      memberCardId: null,
      supportCardId: null
    }))
  );
});

test("prefills detail links and round trips a multi-slot URL draft", () => {
  const fromDetail = parseTeamDraftSearch("?member=member-card-1", {
    memberCardIds: new Set(memberCards.map((card) => card.id)),
    supportCardIds: new Set(supportCards.map((card) => card.id)),
    musicTrackIds: new Set(["music-1"])
  });

  assert.equal(fromDetail.draft.slots[0].memberCardId, "member-card-1");
  assert.deepEqual(fromDetail.issues, []);

  const draft = {
    ...fromDetail.draft,
    slots: [
      { memberCardId: "member-card-1", supportCardId: "support-card-1" },
      { memberCardId: "member-card-2", supportCardId: null }
    ],
    selectedSongId: "music-1",
    selectedDifficulty: "expert",
    modifiers: { tgwCardRank: 3 }
  };
  const encoded = serializeTeamDraftSearch(draft);
  const normalizedDraft = createTeamDraft(draft);
  const restored = parseTeamDraftSearch(encoded, {
    memberCardIds: new Set(memberCards.map((card) => card.id)),
    supportCardIds: new Set(supportCards.map((card) => card.id)),
    musicTrackIds: new Set(["music-1"])
  });

  assert.deepEqual(restored.draft, normalizedDraft);
  assert.deepEqual(restored.issues, []);
  assert.equal(restored.draft.modifiers.tgwCardRank, 3);
});

test("rejects a T.G.W rank missing from the current release", () => {
  const draft = createTeamDraft({ modifiers: { tgwCardRank: 22 } });
  const issues = validateTeamDraft(draft, {
    tgwCardRanks: new Set([1, 2, 3])
  });
  assert.equal(issues[0].code, "invalid_tgw_card_rank");
});

test("sharing an optimizer result excludes unused inventory without mutating its search input", () => {
  const growth = Object.fromEntries(Array.from({length: 1000}, (_, i) => [`member-card-${i + 1}`, {level: 1, rank: 1}]));
  const draft = createTeamDraft({slots: [{memberCardId: 'member-card-1'}], modifiers: {growth, tgwCardRank: 6}});
  const query = serializeTeamDraftSearch(draft), restored = parseTeamDraftSearch(query).draft;
  assert.deepEqual(restored.modifiers.growth, {'member-card-1': {level: 1, rank: 1}});
  assert.equal(restored.modifiers.tgwCardRank, 6);
  assert.equal(Object.keys(draft.modifiers.growth).length, 1000);
  assert.ok(query.length < 1000);
});

test("reports unknown ids and unsupported difficulty without silently dropping them", () => {
  const result = parseTeamDraftSearch(
    "?members=member-card-999&supports=support-card-999&song=music-999&difficulty=master",
    {
      memberCardIds: new Set(memberCards.map((card) => card.id)),
      supportCardIds: new Set(supportCards.map((card) => card.id)),
      musicTrackIds: new Set(["music-1"])
    }
  );

  assert.equal(result.draft.slots[0].memberCardId, "member-card-999");
  assert.equal(result.draft.slots[0].supportCardId, "support-card-999");
  assert.equal(result.draft.selectedSongId, "music-999");
  assert.equal(result.draft.selectedDifficulty, "master");
  assert.deepEqual(
    result.issues.map((issue) => issue.code),
    [
      "unknown_member_card",
      "unknown_support_card",
      "unknown_song",
      "unsupported_difficulty"
    ]
  );
});

test("derives only auditable base power totals and selected skill summaries", () => {
  const draft = createTeamDraft({
    slots: [
      { memberCardId: "member-card-1", supportCardId: "support-card-1" },
      { memberCardId: "member-card-2", supportCardId: null }
    ]
  });

  const summary = deriveTeamDraftSummary(draft, {
    memberCards,
    supportCards,
    projections
  });

  assert.deepEqual(summary.basePower, {
    performance: 500,
    technic: 700,
    visual: 900,
    total: 2100
  });
  assert.equal(summary.selectedMemberCount, 2);
  assert.equal(summary.selectedSupportCount, 1);
  assert.equal(summary.requiredSlotCount, 5);
  assert.equal(summary.isComplete, false);
  assert.deepEqual(
    summary.skillSummaries.map((skill) => skill.skillId),
    ["live-skill-1", "support-skill-1"]
  );
  assert.equal(summary.score, null);
});

test("validates the serializable TeamDraft structure separately from game rules", () => {
  const issues = validateTeamDraft(
    {
      schemaVersion: 99,
      ruleSetVersion: "unknown",
      slots: "not-an-array",
      selectedSongId: null,
      selectedDifficulty: null,
      modifiers: {}
    },
    {
      memberCardIds: new Set(),
      supportCardIds: new Set(),
      musicTrackIds: new Set()
    }
  );

  assert.deepEqual(
    issues.map((issue) => issue.code),
    ["unsupported_schema", "unknown_rule_set", "invalid_slots"]
  );
});
