import assert from "node:assert/strict";
import test from "node:test";

import { createGrowthSnapshot, maximumGrowthState } from "../src/lib/growth-simulator.mjs";

const memberCard = {
  id: "member-card-fixture",
  performancePowerMax: 1000,
  technicPowerMax: 2000,
  visualPowerMax: 3000
};

const memberProfile = {
  cardKind: "member",
  levelCurve: [
    {
      level: 1,
      rawExp: 0,
      rates: { performance: 4000, technic: 4000, visual: 4000 }
    },
    {
      level: 10,
      rawExp: 900,
      rates: { performance: 6000, technic: 6000, visual: 6000 }
    },
    {
      level: 20,
      rawExp: 2500,
      rates: { performance: 10000, technic: 10000, visual: 10000 }
    }
  ],
  levelLimits: [
    { awakeCount: 1, limitLevel: 10 },
    { awakeCount: 2, limitLevel: 20 }
  ],
  ranks: [
    {
      rank: 1,
      rates: { performance: 0, technic: 0, visual: 0 },
      leaderSkillLevel: 1,
      musicTypeBonusRate: 0,
      musicTagBonusRate: 0
    },
    {
      rank: 2,
      rates: { performance: 500, technic: 500, visual: 500 },
      leaderSkillLevel: 2,
      musicTypeBonusRate: 1000,
      musicTagBonusRate: 1500
    }
  ],
  awakes: [
    {
      awakeCount: 1,
      rates: { performance: 0, technic: 0, visual: 0 }
    },
    {
      awakeCount: 2,
      rates: { performance: 250, technic: 250, visual: 250 }
    }
  ],
  materialRequirements: []
};

test("leader skill follows Rank even when an independent skill level is supplied", () => {
  const snapshot = createGrowthSnapshot({
    card: memberCard, profile: memberProfile,
    projection: { skillRefs: [{ slot: "leader", skillId: "leader-1" }] },
    skills: [{ id: "leader-1", name: "Leader", levels: [
      { level: 1, renderedSummary: "10%" }, { level: 2, renderedSummary: "20%" }
    ] }],
    state: { level: 10, rank: 1, awake: 0, skillLevels: { "leader-1": 1 } }
  });
  assert.equal(snapshot.effectiveSkills[0].level, 2);
  assert.equal(snapshot.effectiveSkills[0].renderedSummary, "20%");
});

test("maximum preview uses the last growth stages and actual skill level limits", () => {
  assert.deepEqual(maximumGrowthState(memberProfile, [
    { id: "live-1", levels: [{ level: 1 }, { level: 5 }] }
  ]), { level: 20, rank: 1, awake: 1, skillLevels: { "live-1": 5 } });
  assert.equal(maximumGrowthState({ ...memberProfile, cardKind: "support" }).awake, 0);
});

test("clamps level to the current awakening cap and applies native floor order", () => {
  const snapshot = createGrowthSnapshot({
    card: memberCard,
    profile: memberProfile,
    projection: { skillRefs: [] },
    state: { level: 20, rank: 1, awake: 0, skillLevels: {} }
  });

  assert.deepEqual(snapshot.state, {
    level: 10,
    rank: 1,
    awake: 0,
    skillLevels: {}
  });
  assert.equal(snapshot.maxLevel, 10);
  assert.deepEqual(snapshot.power, {
    performance: 650,
    technic: 1300,
    visual: 1950,
    total: 3900,
    accuracy: "verified"
  });
  assert.deepEqual(snapshot.bonuses, {
    leaderSkillLevel: 2,
    musicTypeBonusRate: 1000,
    musicTagBonusRate: 1500,
    cardTypeLinkBonusRate: 0
  });
  assert.deepEqual(snapshot.exp, {
    current: 900,
    toCurrentCap: 0,
    toFinalCap: 1600
  });
});

test("keeps next-step and remaining material ledgers separate by growth axis", () => {
  const profile = {
    ...memberProfile,
    materialRequirements: [
      {
        usageKind: "member_rank",
        stage: 2,
        itemId: "item-shard",
        amount: 50
      },
      {
        usageKind: "member_rank",
        stage: 3,
        itemId: "item-shard",
        amount: 150
      },
      {
        usageKind: "member_awake",
        stage: 2,
        itemId: "item-coin",
        amount: 10
      },
      {
        usageKind: "member_awake",
        stage: 3,
        itemId: "item-coin",
        amount: 20
      }
    ]
  };
  const projection = {
    skillRefs: [
      {
        skillId: "live-skill-1",
        levelResourceGroup: 5,
        materialRequirements: [
          {
            usageKind: "skill_level",
            stage: 2,
            itemId: "item-coin",
            amount: 100
          },
          {
            usageKind: "skill_level",
            stage: 2,
            itemId: "item-ticket",
            amount: 10
          },
          {
            usageKind: "skill_level",
            stage: 3,
            itemId: "item-coin",
            amount: 200
          },
          {
            usageKind: "skill_level",
            stage: 3,
            itemId: "item-ticket",
            amount: 20
          }
        ]
      }
    ]
  };

  const snapshot = createGrowthSnapshot({
    card: memberCard,
    profile,
    projection,
    state: {
      level: 1,
      rank: 0,
      awake: 0,
      skillLevels: { "live-skill-1": 1 }
    }
  });

  assert.deepEqual(snapshot.materialAxes, [
    {
      key: "rank",
      usageKind: "member_rank",
      currentStage: 0,
      maxStage: 2,
      nextStage: 1,
      next: [{ itemId: "item-shard", amount: 50 }],
      remaining: [{ itemId: "item-shard", amount: 200 }]
    },
    {
      key: "awake",
      usageKind: "member_awake",
      currentStage: 0,
      maxStage: 2,
      nextStage: 1,
      next: [{ itemId: "item-coin", amount: 10 }],
      remaining: [{ itemId: "item-coin", amount: 30 }]
    },
    {
      key: "skill:live-skill-1",
      usageKind: "skill_level",
      currentStage: 1,
      maxStage: 3,
      nextStage: 2,
      next: [
        { itemId: "item-coin", amount: 100 },
        { itemId: "item-ticket", amount: 10 }
      ],
      remaining: [
        { itemId: "item-coin", amount: 300 },
        { itemId: "item-ticket", amount: 30 }
      ]
    }
  ]);
});

test("uses support rank as the level cap without adding rank power", () => {
  const supportProfile = {
    cardKind: "support",
    levelCurve: memberProfile.levelCurve,
    levelLimits: [],
    ranks: [
      {
        rank: 1,
        limitLevel: 10,
        cardTypeLinkBonusRate: 0,
        supportSkillLevel: 1,
        supportSkill01Level: 1,
        gekisouSupportSkillLevel: 1,
        gekisouSupportSkill01Level: 1
      },
      {
        rank: 2,
        limitLevel: 20,
        cardTypeLinkBonusRate: 1750,
        supportSkillLevel: 2,
        supportSkill01Level: 2,
        gekisouSupportSkillLevel: 2,
        gekisouSupportSkill01Level: 2
      }
    ],
    awakes: [],
    materialRequirements: [
      {
        usageKind: "support_rank",
        stage: 2,
        itemId: "item-support",
        amount: 4
      }
    ]
  };

  const snapshot = createGrowthSnapshot({
    card: memberCard,
    profile: supportProfile,
    projection: {
      skillRefs: [
        { slot: "support_1", skillId: "support-skill-1" },
        {
          slot: "gekisou_support_1",
          skillId: "gekisou-support-skill-1"
        }
      ]
    },
    skills: [
      {
        id: "support-skill-1",
        name: "Support One",
        iconAssetId: "asset-support-skill",
        levels: [
          { level: 1, renderedSummary: "Limit 5" },
          { level: 2, renderedSummary: "Limit 6" }
        ]
      },
      {
        id: "gekisou-support-skill-1",
        name: "Gekisou Support One",
        iconAssetId: "asset-gekisou-support-skill",
        levels: [
          { level: 1, renderedSummary: "3 seconds" },
          { level: 2, renderedSummary: "4 seconds" }
        ]
      }
    ],
    state: { level: 20, rank: 1, awake: 4, skillLevels: {} }
  });

  assert.equal(snapshot.maxLevel, 20);
  assert.deepEqual(snapshot.state, {
    level: 20,
    rank: 1,
    awake: 0,
    skillLevels: {}
  });
  assert.deepEqual(snapshot.power, {
    performance: 1000,
    technic: 2000,
    visual: 3000,
    total: 6000,
    accuracy: "verified"
  });
  assert.equal(snapshot.bonuses.cardTypeLinkBonusRate, 1750);
  assert.deepEqual(snapshot.effectiveSkills, [
    {
      skillId: "support-skill-1",
      slot: "support_1",
      level: 2,
      name: "Support One",
      iconAssetId: "asset-support-skill",
      renderedSummary: "Limit 6"
    },
    {
      skillId: "gekisou-support-skill-1",
      slot: "gekisou_support_1",
      level: 2,
      name: "Gekisou Support One",
      iconAssetId: "asset-gekisou-support-skill",
      renderedSummary: "4 seconds"
    }
  ]);
  assert.deepEqual(snapshot.materialAxes, [
    {
      key: "rank",
      usageKind: "support_rank",
      currentStage: 1,
      maxStage: 1,
      nextStage: null,
      next: [],
      remaining: []
    }
  ]);
});

test("falls back to generic support skill rank fields", () => {
  const supportProfile = {
    cardKind: "support",
    levelCurve: memberProfile.levelCurve,
    levelLimits: [],
    ranks: [
      {
        rank: 1,
        limitLevel: 10,
        supportSkillLevel: 3,
        gekisouSupportSkillLevel: 4
      }
    ],
    awakes: [],
    materialRequirements: []
  };
  const skills = [
    {
      id: "support-skill-2",
      name: "Support Two",
      iconAssetId: null,
      levels: [{ level: 3, renderedSummary: "Support Lv3" }]
    },
    {
      id: "gekisou-support-skill-2",
      name: "Gekisou Support Two",
      iconAssetId: null,
      levels: [{ level: 4, renderedSummary: "Gekisou Lv4" }]
    }
  ];

  const snapshot = createGrowthSnapshot({
    card: memberCard,
    profile: supportProfile,
    projection: {
      skillRefs: [
        { slot: "support_2", skillId: "support-skill-2" },
        {
          slot: "gekisou_support_2",
          skillId: "gekisou-support-skill-2"
        }
      ]
    },
    skills,
    state: { level: 1, rank: 0, awake: 0, skillLevels: {} }
  });

  assert.deepEqual(
    snapshot.effectiveSkills.map(({ skillId, level, renderedSummary }) => ({
      skillId,
      level,
      renderedSummary
    })),
    [
      {
        skillId: "support-skill-2",
        level: 3,
        renderedSummary: "Support Lv3"
      },
      {
        skillId: "gekisou-support-skill-2",
        level: 4,
        renderedSummary: "Gekisou Lv4"
      }
    ]
  );
});
