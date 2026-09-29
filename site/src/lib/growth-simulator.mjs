const RATE_SCALE = 10_000;

const SUPPORT_SKILL_LEVEL_FIELDS = {
  support_1: ["supportSkill01Level", "supportSkillLevel"],
  support_2: ["supportSkill02Level", "supportSkillLevel"],
  gekisou_support_1: [
    "gekisouSupportSkill01Level",
    "gekisouSupportSkillLevel"
  ],
  gekisou_support_2: [
    "gekisouSupportSkill02Level",
    "gekisouSupportSkillLevel"
  ]
};

function clampInteger(value, minimum, maximum) {
  const integer = Number.isFinite(Number(value))
    ? Math.trunc(Number(value))
    : minimum;
  return Math.min(Math.max(integer, minimum), maximum);
}

function curvePointAt(profile, level) {
  const points = [...profile.levelCurve].sort(
    (left, right) => left.level - right.level
  );
  let result = points[0];
  for (const point of points) {
    if (point.level > level) break;
    result = point;
  }
  return result;
}

function ratePower(maximum, rate) {
  return Math.floor((maximum * rate) / RATE_SCALE);
}

function ratesFor(record) {
  return record?.rates ?? {
    performance: 0,
    technic: 0,
    visual: 0
  };
}

function limitForState(profile, rank, awake) {
  if (profile.cardKind === "support") {
    return profile.ranks[rank]?.limitLevel ?? 1;
  }
  const awakeCount = awake + 1;
  return (
    profile.levelLimits.find(
      (limit) => limit.awakeCount === awakeCount
    )?.limitLevel ?? profile.levelCurve.at(-1)?.level ?? 1
  );
}

function normalizeState(profile, requested) {
  const maximumRank = Math.max(profile.ranks.length - 1, 0);
  const maximumAwake =
    profile.cardKind === "member"
      ? Math.max(profile.awakes.length - 1, 0)
      : 0;
  const rank = clampInteger(requested.rank, 0, maximumRank);
  const awake = clampInteger(requested.awake, 0, maximumAwake);
  const maxLevel = limitForState(profile, rank, awake);
  return {
    state: {
      level: clampInteger(requested.level, 1, maxLevel),
      rank,
      awake,
      skillLevels: { ...(requested.skillLevels ?? {}) }
    },
    maxLevel
  };
}

function calculatePower(card, profile, state) {
  const levelRates = ratesFor(curvePointAt(profile, state.level));
  const rankRates =
    profile.cardKind === "member"
      ? ratesFor(profile.ranks[state.rank])
      : ratesFor(null);
  const awakeRates =
    profile.cardKind === "member"
      ? ratesFor(profile.awakes[state.awake])
      : ratesFor(null);
  const calculateAxis = (maximum, axis) =>
    ratePower(maximum, levelRates[axis]) +
    ratePower(maximum, rankRates[axis]) +
    ratePower(maximum, awakeRates[axis]);
  const performance = calculateAxis(
    card.performancePowerMax,
    "performance"
  );
  const technic = calculateAxis(card.technicPowerMax, "technic");
  const visual = calculateAxis(card.visualPowerMax, "visual");
  return {
    performance,
    technic,
    visual,
    total: performance + technic + visual,
    accuracy: "verified"
  };
}

function calculateBonuses(profile, state) {
  const rank = profile.ranks[state.rank] ?? {};
  return {
    leaderSkillLevel: rank.leaderSkillLevel ?? 0,
    musicTypeBonusRate: rank.musicTypeBonusRate ?? 0,
    musicTagBonusRate: rank.musicTagBonusRate ?? 0,
    cardTypeLinkBonusRate: rank.cardTypeLinkBonusRate ?? 0
  };
}

function calculateEffectiveSkills(profile, projection, state, skills) {
  const definitions = new Map(
    (skills ?? []).map((skill) => [skill.id, skill])
  );
  const rank = profile.ranks[state.rank] ?? {};
  return (projection.skillRefs ?? []).flatMap((reference) => {
    const skill = definitions.get(reference.skillId);
    if (!skill) return [];
    const levels = [...(skill.levels ?? [])].sort(
      (left, right) => left.level - right.level
    );
    let effectiveLevel = null;
    if (profile.cardKind === "support") {
      const fields = SUPPORT_SKILL_LEVEL_FIELDS[reference.slot] ?? [];
      effectiveLevel =
        fields
          .map((field) => Number(rank[field] ?? 0))
          .find((level) => level > 0) ?? null;
    } else if (reference.slot === "leader") {
      effectiveLevel = rank.leaderSkillLevel ?? levels[0]?.level ?? null;
    } else {
      const requested = Number(state.skillLevels[reference.skillId]);
      effectiveLevel = Number.isFinite(requested)
        ? requested
        : levels[0]?.level ?? null;
    }
    const level =
      effectiveLevel === null
        ? null
        : levels.find((entry) => entry.level === effectiveLevel);
    return [
      {
        skillId: reference.skillId,
        slot: reference.slot,
        level: effectiveLevel,
        name: skill.name,
        iconAssetId: skill.iconAssetId ?? null,
        renderedSummary: level?.renderedSummary ?? ""
      }
    ];
  });
}

function calculateExp(profile, state, maxLevel) {
  const current = curvePointAt(profile, state.level)?.rawExp ?? 0;
  const currentCap = curvePointAt(profile, maxLevel)?.rawExp ?? current;
  const finalCap = profile.levelCurve.at(-1)?.rawExp ?? currentCap;
  return {
    current,
    toCurrentCap: Math.max(currentCap - current, 0),
    toFinalCap: Math.max(finalCap - current, 0)
  };
}

function aggregateMaterials(requirements) {
  const totals = new Map();
  for (const requirement of requirements) {
    totals.set(
      requirement.itemId,
      (totals.get(requirement.itemId) ?? 0) + requirement.amount
    );
  }
  return [...totals].map(([itemId, amount]) => ({ itemId, amount }));
}

function materialAxis({
  key,
  usageKind,
  requirements,
  currentStage,
  nativeStageOffset = 0
}) {
  if (requirements.length === 0) return null;
  const maxNativeStage = Math.max(
    ...requirements.map((requirement) => requirement.stage)
  );
  const maxStage = maxNativeStage - nativeStageOffset;
  const normalizedStage = clampInteger(currentStage, 0, maxStage);
  const currentNativeStage = normalizedStage + nativeStageOffset;
  return {
    key,
    usageKind,
    currentStage: normalizedStage,
    maxStage,
    nextStage:
      normalizedStage < maxStage ? normalizedStage + 1 : null,
    next: aggregateMaterials(
      requirements.filter(
        (requirement) => requirement.stage === currentNativeStage + 1
      )
    ),
    remaining: aggregateMaterials(
      requirements.filter(
        (requirement) => requirement.stage > currentNativeStage
      )
    )
  };
}

function calculateMaterialAxes(profile, projection, state) {
  const rankUsage =
    profile.cardKind === "support" ? "support_rank" : "member_rank";
  const axes = [
    materialAxis({
      key: "rank",
      usageKind: rankUsage,
      requirements: profile.materialRequirements.filter(
        (requirement) => requirement.usageKind === rankUsage
      ),
      currentStage: state.rank,
      nativeStageOffset: 1
    })
  ];
  if (profile.cardKind === "member") {
    axes.push(
      materialAxis({
        key: "awake",
        usageKind: "member_awake",
        requirements: profile.materialRequirements.filter(
          (requirement) => requirement.usageKind === "member_awake"
        ),
        currentStage: state.awake,
        nativeStageOffset: 1
      })
    );
  }
  for (const skill of projection.skillRefs ?? []) {
    axes.push(
      materialAxis({
        key: `skill:${skill.skillId}`,
        usageKind: "skill_level",
        requirements: skill.materialRequirements ?? [],
        currentStage: state.skillLevels[skill.skillId] ?? 1
      })
    );
  }
  return axes.filter(Boolean);
}

export function createGrowthSnapshot({
  card,
  profile,
  projection,
  skills = [],
  state
}) {
  const normalized = normalizeState(profile, state);
  return {
    state: normalized.state,
    maxLevel: normalized.maxLevel,
    power: calculatePower(card, profile, normalized.state),
    bonuses: calculateBonuses(profile, normalized.state),
    exp: calculateExp(profile, normalized.state, normalized.maxLevel),
    effectiveSkills: calculateEffectiveSkills(
      profile,
      projection,
      normalized.state,
      skills
    ),
    materialAxes: calculateMaterialAxes(
      profile,
      projection,
      normalized.state
    ),
    projection
  };
}

export function maximumGrowthState(profile, skills = []) {
  return {
    level: profile.levelCurve.at(-1)?.level ?? 1,
    rank: Math.max(0, profile.ranks.length - 1),
    awake: profile.cardKind === "member" ? Math.max(0, profile.awakes.length - 1) : 0,
    skillLevels: Object.fromEntries(skills.map(skill => [skill.id, Math.max(1, ...skill.levels.map(level => level.level))]))
  };
}
