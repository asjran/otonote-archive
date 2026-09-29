import { stableSnapshotHash } from "./scoring-engine.mjs";
import { createTeamDraft, TEAM_RULE_SET } from "./team-draft.mjs";

export const GEKISOU_SCENARIO_SCHEMA_VERSION = 1;

export const GEKISOU_RULE_SET = Object.freeze({
  id: "gekisou-reconstruction-v1",
  label: "激奏规则重建 v1",
  status: "research-reconstruction",
  producesFormalScore: false,
  participantMinimum: 1,
  participantMaximum: 5,
  evidenceStatus: "reconstructed-rule"
});

const DIFFICULTIES = new Set(["easy", "normal", "hard", "expert"]);
const MODES = new Set(["rules", "experiment"]);
const PERFORMANCE_PRESETS = new Set(["ap", "fc", "custom"]);
const PERFORMANCE_JUDGEMENTS = new Set(["perfect", "great", "good", "hit", "miss"]);
const EVENT_PRIORITIES = Object.freeze({
  "gekisou-range-start": 10,
  "skill-marker": 20,
  "experimental-skill-start": 25,
  "performance-judgement": 40,
  "luck-outcome": 45,
  "counterfactual-score-delta": 50,
  "experimental-skill-score": 50,
  "experimental-skill-end": 80,
  "gekisou-range-end": 90
});

const isObject = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const finiteNumber = (value, fallback = 0) => {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};

const nullableString = (value) =>
  typeof value === "string" && value.length > 0 ? value : null;

const issue = (code, message, path = null, details = {}) => ({
  code,
  message,
  path,
  severity: "error",
  ...details
});

const missionSnapshot = (mission, index) => ({
  index: Number(mission?.index ?? index + 1),
  typeCode: Number(mission?.typeCode ?? 0),
  type: String(mission?.type ?? "unknown"),
  label: String(mission?.label ?? "UNKNOWN"),
  evidenceStatus: String(mission?.evidenceStatus ?? "confirmed-data")
});

const rangeSnapshot = (range, index, missions) => ({
  index: index + 1,
  start: finiteNumber(range?.start, Number.NaN),
  end: finiteNumber(range?.end, Number.NaN),
  mission: missions[index] ?? null,
  evidenceStatus: "confirmed-data"
});

const normalizePerformanceOverride = (value = {}, kind, index) => ({
  id: nullableString(value?.id) ?? `${kind}-override-${index + 1}`,
  ...(kind === "segment"
    ? { segmentIndex: Number(value?.segmentIndex) }
    : { markerId: nullableString(value?.markerId) }),
  judgement: PERFORMANCE_JUDGEMENTS.has(value?.judgement)
    ? value.judgement
    : "hit",
  comboBreak: value?.comboBreak === true
});

const normalizePerformancePlan = (value = {}) => ({
  preset: PERFORMANCE_PRESETS.has(value?.preset) ? value.preset : "ap",
  segmentOverrides: Array.isArray(value?.segmentOverrides)
    ? value.segmentOverrides.map((entry, index) =>
        normalizePerformanceOverride(entry, "segment", index)
      )
    : [],
  noteOverrides: Array.isArray(value?.noteOverrides)
    ? value.noteOverrides.map((entry, index) =>
        normalizePerformanceOverride(entry, "note", index)
      )
    : []
});

const normalizeSkillBranch = (value = {}, index) => ({
  id: nullableString(value?.id) ?? `skill-branch-${index + 1}`,
  skillId: nullableString(value?.skillId),
  sourceCardId: nullableString(value?.sourceCardId),
  markerIndex: Number(value?.markerIndex),
  durationSeconds: finiteNumber(value?.durationSeconds, 0),
  experimentalScoreDelta: finiteNumber(value?.experimentalScoreDelta, 0),
  note: nullableString(value?.note)
});

const participantSnapshot = (value, index) => ({
  id: nullableString(value?.id) ?? `participant-${index + 1}`,
  label: nullableString(value?.label) ?? `P${index + 1}`,
  teamDraft: createTeamDraft(value?.teamDraft),
  performancePlan: normalizePerformancePlan(value?.performancePlan),
  skillBranches: Array.isArray(value?.skillBranches)
    ? value.skillBranches.map(normalizeSkillBranch)
    : []
});

const judgementSnapshot = (value, index) => ({
  index: index + 1,
  markerId: nullableString(value?.markerId) ?? `judgement-${index + 1}`,
  noteId: nullableString(value?.noteId),
  time: finiteNumber(value?.time, Number.NaN),
  sourceCombo: Number.isInteger(value?.combo) ? value.combo : index + 1
});

const luckOutcomeSnapshot = (value, index) => ({
  id: nullableString(value?.id) ?? `luck-outcome-${index + 1}`,
  participantId: nullableString(value?.participantId),
  segmentIndex: Number(value?.segmentIndex),
  value: finiteNumber(value?.value, Number.NaN)
});

const overrideSnapshot = (value, index) => ({
  id: nullableString(value?.id) ?? `override-${index + 1}`,
  kind: String(value?.kind ?? ""),
  time: finiteNumber(value?.time, Number.NaN),
  participantId: nullableString(value?.participantId),
  amount: finiteNumber(value?.amount, Number.NaN),
  owner: isObject(value?.owner)
    ? {
        kind: nullableString(value.owner.kind) ?? "manual",
        id: nullableString(value.owner.id) ?? `override-${index + 1}`
      }
    : { kind: "manual", id: `override-${index + 1}` },
  note: nullableString(value?.note)
});

export function createGekisouScenario({
  sourceReleaseId,
  track,
  chart,
  participantCount,
  participants,
  focusedParticipantId,
  mode = "rules",
  randomnessPlan,
  counterfactualOverrides
} = {}) {
  const missions = Array.isArray(track?.gekisouMissions)
    ? track.gekisouMissions.slice(0, 3).map(missionSnapshot)
    : [];
  const rawRanges = Array.isArray(chart?.gekisouRanges)
    ? chart.gekisouRanges
    : Array.isArray(chart?.feverRanges)
      ? chart.feverRanges
      : [];
  const sourceParticipants = Array.isArray(participants)
    ? participants
    : Array.from(
        {
          length: Number.isInteger(participantCount) ? participantCount : 1
        },
        () => ({})
      );
  const normalizedParticipants = sourceParticipants.map(participantSnapshot);
  const scenario = {
    schemaVersion: GEKISOU_SCENARIO_SCHEMA_VERSION,
    sourceReleaseId: nullableString(sourceReleaseId),
    ruleSetVersion: GEKISOU_RULE_SET.id,
    mode: String(mode),
    music: {
      trackId: nullableString(track?.id),
      title: nullableString(track?.title),
      chartId: nullableString(chart?.id),
      difficulty: nullableString(chart?.difficulty),
      duration: finiteNumber(chart?.duration, Number.NaN),
      missions,
      ranges: rawRanges.slice(0, 3).map((range, index) =>
        rangeSnapshot(range, index, missions)
      ),
      skillTimings: Array.isArray(chart?.skillTimings)
        ? chart.skillTimings.map((time) => finiteNumber(time, Number.NaN))
        : [],
      judgements: Array.isArray(chart?.comboEvents)
        ? chart.comboEvents.map(judgementSnapshot)
        : []
    },
    participants: normalizedParticipants,
    focusedParticipantId:
      nullableString(focusedParticipantId) ?? normalizedParticipants[0]?.id ?? null,
    randomnessPlan: {
      mode: String(randomnessPlan?.mode ?? "fixed"),
      seed: Number.isInteger(randomnessPlan?.seed) ? randomnessPlan.seed : 0,
      outcomes: Array.isArray(randomnessPlan?.outcomes)
        ? randomnessPlan.outcomes.map(luckOutcomeSnapshot)
        : []
    },
    counterfactualOverrides: Array.isArray(counterfactualOverrides)
      ? counterfactualOverrides.map(overrideSnapshot)
      : []
  };
  return {
    ...scenario,
    scenarioHash: stableSnapshotHash(scenario)
  };
}

export function validateGekisouScenario(scenario) {
  const issues = [];
  if (!isObject(scenario)) {
    return [issue("invalid_scenario", "场景必须是对象")];
  }
  if (scenario.schemaVersion !== GEKISOU_SCENARIO_SCHEMA_VERSION) {
    issues.push(issue("unsupported_schema", "场景 schemaVersion 不受支持", "schemaVersion"));
  }
  if (scenario.ruleSetVersion !== GEKISOU_RULE_SET.id) {
    issues.push(issue("unknown_rule_set", "场景规则版本不受支持", "ruleSetVersion"));
  }
  if (!nullableString(scenario.sourceReleaseId)) {
    issues.push(issue("version_mismatch", "场景缺少来源 Release", "sourceReleaseId"));
  }
  if (!MODES.has(scenario.mode)) {
    issues.push(issue("invalid_mode", "场景模式必须是 rules 或 experiment", "mode"));
  }
  if (!isObject(scenario.music) || !scenario.music.trackId || !scenario.music.chartId) {
    issues.push(issue("invalid_music", "场景缺少歌曲或谱面", "music"));
  } else {
    if (!DIFFICULTIES.has(scenario.music.difficulty)) {
      issues.push(issue("invalid_difficulty", "谱面难度不受支持", "music.difficulty"));
    }
    if (!Array.isArray(scenario.music.missions) || scenario.music.missions.length !== 3) {
      issues.push(issue("invalid_gekisou_missions", "歌曲必须包含三段激奏任务", "music.missions"));
    } else {
      scenario.music.missions.forEach((mission, index) => {
        if (![1, 2, 3].includes(mission?.typeCode)) {
          issues.push(issue(
            "invalid_gekisou_mission",
            "激奏任务类型未知",
            `music.missions.${index}.typeCode`
          ));
        }
      });
    }
    if (!Array.isArray(scenario.music.ranges) || scenario.music.ranges.length !== 3) {
      issues.push(issue("invalid_gekisou_ranges", "谱面必须包含三段激奏区间", "music.ranges"));
    } else {
      scenario.music.ranges.forEach((range, index) => {
        if (!Number.isFinite(range?.start) || !Number.isFinite(range?.end) || range.end <= range.start) {
          issues.push(issue(
            "invalid_gekisou_range",
            "激奏区间必须包含递增的有限时间",
            `music.ranges.${index}`
          ));
        }
        if (index > 0 && range.start < scenario.music.ranges[index - 1].end) {
          issues.push(issue(
            "overlapping_gekisou_ranges",
            "激奏区间不能重叠",
            `music.ranges.${index}`
          ));
        }
      });
    }
    if (!Array.isArray(scenario.music.judgements)) {
      issues.push(issue("invalid_judgement_timeline", "谱面判定时间线必须是数组", "music.judgements"));
    } else {
      const markerIds = new Set();
      scenario.music.judgements.forEach((judgement, index) => {
        if (!nullableString(judgement?.markerId) || markerIds.has(judgement.markerId)) {
          issues.push(issue(
            "invalid_judgement_marker",
            "谱面判定标记缺失或重复",
            `music.judgements.${index}.markerId`
          ));
        } else {
          markerIds.add(judgement.markerId);
        }
        if (!Number.isFinite(judgement?.time) || judgement.time < 0 || judgement.time > scenario.music.duration) {
          issues.push(issue(
            "invalid_judgement_time",
            "谱面判定时间不在歌曲范围内",
            `music.judgements.${index}.time`
          ));
        }
      });
    }
  }

  if (
    !Array.isArray(scenario.participants)
    || scenario.participants.length < GEKISOU_RULE_SET.participantMinimum
    || scenario.participants.length > GEKISOU_RULE_SET.participantMaximum
  ) {
    issues.push(issue(
      "invalid_participant_count",
      "激奏房间必须包含 1–5 名参与者",
      "participants"
    ));
  } else {
    const ids = new Set();
    scenario.participants.forEach((participant, index) => {
      if (!nullableString(participant?.id)) {
        issues.push(issue("invalid_participant", "参与者缺少 ID", `participants.${index}.id`));
      } else if (ids.has(participant.id)) {
        issues.push(issue("duplicate_participant", "参与者 ID 重复", `participants.${index}.id`));
      } else {
        ids.add(participant.id);
      }
      if (
        participant?.teamDraft?.schemaVersion !== 1
        || participant?.teamDraft?.ruleSetVersion !== TEAM_RULE_SET.id
        || !Array.isArray(participant?.teamDraft?.slots)
        || participant.teamDraft.slots.length !== TEAM_RULE_SET.officialSlotCount
      ) {
        issues.push(issue("invalid_team_draft", "参与者卡组草稿无效", `participants.${index}.teamDraft`));
      }
      const performance = participant?.performancePlan;
      if (!isObject(performance) || !PERFORMANCE_PRESETS.has(performance.preset)) {
        issues.push(issue("invalid_performance_plan", "演奏计划预设无效", `participants.${index}.performancePlan`));
      } else {
        const markerIds = new Set((scenario.music?.judgements ?? []).map((entry) => entry.markerId));
        const segmentIds = new Set((scenario.music?.ranges ?? []).map((entry) => entry.index));
        const seenSegments = new Set();
        performance.segmentOverrides.forEach((override, overrideIndex) => {
          const path = `participants.${index}.performancePlan.segmentOverrides.${overrideIndex}`;
          if (!segmentIds.has(override.segmentIndex) || seenSegments.has(override.segmentIndex)) {
            issues.push(issue("invalid_segment_override", "分段覆盖引用未知或重复激奏段", path));
          }
          seenSegments.add(override.segmentIndex);
          if (!PERFORMANCE_JUDGEMENTS.has(override.judgement)) {
            issues.push(issue("invalid_judgement", "分段覆盖判定类型无效", `${path}.judgement`));
          }
        });
        const seenMarkers = new Set();
        performance.noteOverrides.forEach((override, overrideIndex) => {
          const path = `participants.${index}.performancePlan.noteOverrides.${overrideIndex}`;
          if (!markerIds.has(override.markerId) || seenMarkers.has(override.markerId)) {
            issues.push(issue("invalid_note_override", "逐音符覆盖引用未知或重复判定", path));
          }
          seenMarkers.add(override.markerId);
          if (!PERFORMANCE_JUDGEMENTS.has(override.judgement)) {
            issues.push(issue("invalid_judgement", "逐音符覆盖判定类型无效", `${path}.judgement`));
          }
        });
      }
      const selectedCardIds = new Set(
        (participant?.teamDraft?.slots ?? []).flatMap((slot) =>
          [slot?.memberCardId, slot?.supportCardId].filter(Boolean)
        )
      );
      participant?.skillBranches?.forEach((branch, branchIndex) => {
        const path = `participants.${index}.skillBranches.${branchIndex}`;
        if (!nullableString(branch?.skillId)) {
          issues.push(issue("invalid_skill_branch", "实验技能缺少技能 ID", `${path}.skillId`));
        }
        if (!Number.isInteger(branch?.markerIndex)
          || branch.markerIndex < 1
          || branch.markerIndex > (scenario.music?.skillTimings?.length ?? 0)) {
          issues.push(issue("invalid_skill_marker", "实验技能引用未知技能时机", `${path}.markerIndex`));
        }
        if (!Number.isFinite(branch?.durationSeconds) || branch.durationSeconds < 0) {
          issues.push(issue("invalid_skill_duration", "实验技能持续时间必须为非负数", `${path}.durationSeconds`));
        }
        if (!Number.isInteger(branch?.experimentalScoreDelta)) {
          issues.push(issue("invalid_skill_score_delta", "实验技能增分必须是整数", `${path}.experimentalScoreDelta`));
        }
        if (scenario.mode === "rules" && branch?.experimentalScoreDelta !== 0) {
          issues.push(issue("illegal_experimental_skill", "规则模式不能包含实验技能增分", path));
        }
        if (branch?.sourceCardId && !selectedCardIds.has(branch.sourceCardId)) {
          issues.push(issue("unknown_skill_source_card", "实验技能来源卡不在当前卡组", `${path}.sourceCardId`));
        }
      });
    });
    if (!ids.has(scenario.focusedParticipantId)) {
      issues.push(issue("invalid_focused_participant", "当前关注者不属于房间", "focusedParticipantId"));
    }
  }

  if (!isObject(scenario.randomnessPlan)
    || scenario.randomnessPlan.mode !== "fixed"
    || !Number.isInteger(scenario.randomnessPlan.seed)
    || !Array.isArray(scenario.randomnessPlan.outcomes)) {
    issues.push(issue("invalid_randomness_plan", "当前只支持固定种子与显式 LUCK 输入", "randomnessPlan"));
  } else {
    const participantIds = new Set((scenario.participants ?? []).map((entry) => entry.id));
    const luckSegments = new Set(
      (scenario.music?.ranges ?? [])
        .filter((range) => range.mission?.type === "luck")
        .map((range) => range.index)
    );
    const outcomeKeys = new Set();
    scenario.randomnessPlan.outcomes.forEach((outcome, index) => {
      const path = `randomnessPlan.outcomes.${index}`;
      if (!participantIds.has(outcome?.participantId)) {
        issues.push(issue("unknown_participant", "LUCK 输入引用未知参与者", `${path}.participantId`));
      }
      if (!luckSegments.has(outcome?.segmentIndex)) {
        issues.push(issue("invalid_luck_segment", "LUCK 输入只能引用 LUCK 激奏段", `${path}.segmentIndex`));
      }
      if (!Number.isInteger(outcome?.value)) {
        issues.push(issue("invalid_luck_value", "LUCK 输入必须是整数", `${path}.value`));
      }
      const key = `${outcome?.participantId}:${outcome?.segmentIndex}`;
      if (outcomeKeys.has(key)) {
        issues.push(issue("duplicate_luck_input", "同一参与者与激奏段只能有一个 LUCK 输入", path));
      }
      outcomeKeys.add(key);
    });
  }

  if (!Array.isArray(scenario.counterfactualOverrides)) {
    issues.push(issue("invalid_overrides", "反事实覆盖必须是数组", "counterfactualOverrides"));
  } else if (scenario.mode === "rules" && scenario.counterfactualOverrides.length > 0) {
    issues.push(issue("illegal_override", "规则模式不能包含反事实覆盖", "counterfactualOverrides"));
  } else if (scenario.mode === "experiment") {
    const participantIds = new Set((scenario.participants ?? []).map((entry) => entry.id));
    scenario.counterfactualOverrides.forEach((override, index) => {
      const path = `counterfactualOverrides.${index}`;
      if (override?.kind !== "score-delta") {
        issues.push(issue("unsupported_override", "当前只支持明确的分数增量覆盖", `${path}.kind`));
      }
      if (!participantIds.has(override?.participantId)) {
        issues.push(issue("unknown_participant", "覆盖引用了未知参与者", `${path}.participantId`));
      }
      if (!Number.isFinite(override?.time) || override.time < 0 || override.time > scenario.music.duration) {
        issues.push(issue("invalid_override_time", "覆盖时间不在谱面范围内", `${path}.time`));
      }
      if (!Number.isInteger(override?.amount)) {
        issues.push(issue("invalid_score_delta", "分数增量必须是整数", `${path}.amount`));
      }
    });
  }
  return issues;
}

export function compileGekisouEvents(scenario) {
  let sourceOrder = 0;
  const events = [];
  const append = (event) => {
    events.push({
      ...event,
      priority: EVENT_PRIORITIES[event.kind],
      sourceOrder: sourceOrder++,
      evidenceStatus: event.evidenceStatus ?? "confirmed-data"
    });
  };

  for (const range of scenario.music.ranges) {
    append({
      id: `range-${range.index}-start`,
      kind: "gekisou-range-start",
      time: range.start,
      segmentIndex: range.index,
      mission: range.mission
    });
    append({
      id: `range-${range.index}-end`,
      kind: "gekisou-range-end",
      time: range.end,
      segmentIndex: range.index,
      mission: range.mission
    });
  }
  scenario.music.skillTimings.forEach((time, index) => append({
    id: `skill-marker-${index + 1}`,
    kind: "skill-marker",
    time,
    markerIndex: index + 1,
    evidenceStatus: "confirmed-data"
  }));
  for (const participant of scenario.participants) {
    const segmentOverrides = new Map(
      participant.performancePlan.segmentOverrides.map((entry) => [entry.segmentIndex, entry])
    );
    const noteOverrides = new Map(
      participant.performancePlan.noteOverrides.map((entry) => [entry.markerId, entry])
    );
    for (const judgement of scenario.music.judgements) {
      const activeRange = scenario.music.ranges.find(
        (range) => judgement.time >= range.start && judgement.time <= range.end
      );
      const segmentOverride = activeRange ? segmentOverrides.get(activeRange.index) : null;
      const noteOverride = noteOverrides.get(judgement.markerId);
      const baseJudgement = participant.performancePlan.preset === "ap" ? "perfect" : "hit";
      const resolved = noteOverride ?? segmentOverride ?? {
        judgement: baseJudgement,
        comboBreak: false
      };
      append({
        id: `performance-${participant.id}-${judgement.markerId}`,
        kind: "performance-judgement",
        time: judgement.time,
        participantId: participant.id,
        markerId: judgement.markerId,
        noteId: judgement.noteId,
        judgement: resolved.judgement,
        comboBreak: resolved.comboBreak,
        segmentIndex: activeRange?.index ?? null,
        inputSource: noteOverride
          ? "note-override"
          : segmentOverride
            ? "segment-override"
            : participant.performancePlan.preset,
        evidenceStatus: "user-input"
      });
    }
    participant.skillBranches.forEach((branch) => {
      const time = scenario.music.skillTimings[branch.markerIndex - 1];
      const owner = {
        kind: "skill",
        id: branch.skillId,
        ...(branch.sourceCardId ? { sourceCardId: branch.sourceCardId } : {})
      };
      append({
        id: `${branch.id}-start`,
        kind: "experimental-skill-start",
        time,
        participantId: participant.id,
        skillId: branch.skillId,
        sourceCardId: branch.sourceCardId,
        markerIndex: branch.markerIndex,
        durationSeconds: branch.durationSeconds,
        note: branch.note,
        evidenceStatus: "counterfactual"
      });
      if (branch.experimentalScoreDelta !== 0) {
        append({
          id: `${branch.id}-score`,
          kind: "experimental-skill-score",
          time,
          participantId: participant.id,
          amount: branch.experimentalScoreDelta,
          owner,
          skillId: branch.skillId,
          note: branch.note,
          evidenceStatus: "counterfactual"
        });
      }
      append({
        id: `${branch.id}-end`,
        kind: "experimental-skill-end",
        time: time + branch.durationSeconds,
        participantId: participant.id,
        skillId: branch.skillId,
        sourceCardId: branch.sourceCardId,
        markerIndex: branch.markerIndex,
        evidenceStatus: "counterfactual"
      });
    });
  }
  scenario.randomnessPlan.outcomes.forEach((outcome) => {
    const range = scenario.music.ranges.find((entry) => entry.index === outcome.segmentIndex);
    append({
      id: outcome.id,
      kind: "luck-outcome",
      time: range.end,
      participantId: outcome.participantId,
      segmentIndex: outcome.segmentIndex,
      value: outcome.value,
      evidenceStatus: "user-input"
    });
  });
  scenario.counterfactualOverrides.forEach((override) => append({
    id: override.id,
    kind: "counterfactual-score-delta",
    time: override.time,
    participantId: override.participantId,
    amount: override.amount,
    owner: override.owner,
    note: override.note,
    evidenceStatus: "counterfactual"
  }));

  return events.sort((left, right) =>
    left.time - right.time
    || left.priority - right.priority
    || left.sourceOrder - right.sourceOrder
    || left.id.localeCompare(right.id)
  );
}

function rankingFromScores(entries) {
  const ordered = [...entries].sort((left, right) =>
    right.score - left.score || left.participantId.localeCompare(right.participantId)
  );
  let previousScore = null;
  let previousRank = 0;
  return ordered.map((entry, index) => {
    const rank = previousScore === entry.score ? previousRank : index + 1;
    previousScore = entry.score;
    previousRank = rank;
    return { ...entry, rank };
  });
}

function summarizePerformance(events) {
  let currentCombo = 0;
  let maxCombo = 0;
  let comboBreakCount = 0;
  const judgementCounts = {};
  for (const event of events) {
    judgementCounts[event.judgement] = (judgementCounts[event.judgement] ?? 0) + 1;
    if (event.comboBreak) {
      comboBreakCount += 1;
      currentCombo = 0;
    } else {
      currentCombo += 1;
      maxCombo = Math.max(maxCombo, currentCombo);
    }
  }
  return {
    totalJudgements: events.length,
    comboBreakCount,
    maxCombo,
    judgementCounts
  };
}

function invalidResult(scenario, issues) {
  const payload = {
    schemaVersion: 1,
    ruleSetVersion: GEKISOU_RULE_SET.id,
    sourceReleaseId: scenario?.sourceReleaseId ?? null,
    scenarioHash: scenario?.scenarioHash ?? null,
    status: "invalid_input",
    scoreStatus: "unavailable",
    optimizerEligible: false,
    issues,
    blockers: [],
    participants: [],
    segments: [],
    ledger: []
  };
  return { ...payload, ledgerHash: stableSnapshotHash(payload.ledger) };
}

export function runGekisouResearchSimulation(scenario) {
  const issues = validateGekisouScenario(scenario);
  if (issues.length > 0) return invalidResult(scenario, issues);

  const events = compileGekisouEvents(scenario);
  const scoreByParticipant = new Map(
    scenario.participants.map((participant) => [participant.id, 0])
  );
  const contributionByParticipant = new Map(
    scenario.participants.map((participant) => [participant.id, new Map()])
  );
  const segmentScores = new Map(
    scenario.music.ranges.map((range) => [
      range.index,
      new Map(scenario.participants.map((participant) => [participant.id, 0]))
    ])
  );
  const ledger = [];

  for (const event of events) {
    let scoreBefore = null;
    let scoreAfter = null;
    let scoreDelta = 0;
    if (event.kind === "counterfactual-score-delta"
      || event.kind === "experimental-skill-score") {
      scoreBefore = scoreByParticipant.get(event.participantId);
      scoreDelta = event.amount;
      scoreAfter = scoreBefore + scoreDelta;
      scoreByParticipant.set(event.participantId, scoreAfter);
      const contributionKey = `${event.owner.kind}:${event.owner.id}`;
      const participantContributions = contributionByParticipant.get(event.participantId);
      const previousContribution = participantContributions.get(contributionKey) ?? {
        owner: event.owner,
        amount: 0
      };
      participantContributions.set(contributionKey, {
        owner: previousContribution.owner,
        amount: previousContribution.amount + scoreDelta
      });
      const activeRange = scenario.music.ranges.find(
        (range) => event.time >= range.start && event.time <= range.end
      );
      if (activeRange) {
        const scores = segmentScores.get(activeRange.index);
        scores.set(event.participantId, scores.get(event.participantId) + scoreDelta);
      }
    }
    ledger.push({
      sequence: ledger.length + 1,
      eventId: event.id,
      kind: event.kind,
      time: event.time,
      participantId: event.participantId ?? null,
      segmentIndex: event.segmentIndex ?? null,
      mission: event.mission ?? null,
      markerId: event.markerId ?? null,
      judgement: event.judgement ?? null,
      comboBreak: event.comboBreak ?? null,
      inputSource: event.inputSource ?? null,
      skillId: event.skillId ?? null,
      durationSeconds: event.durationSeconds ?? null,
      value: event.value ?? null,
      scoreBefore,
      scoreDelta,
      scoreAfter,
      owner: event.owner ?? null,
      evidenceStatus: event.evidenceStatus
    });
  }

  const experiment = scenario.mode === "experiment";
  const finalRanking = rankingFromScores(
    scenario.participants.map((participant) => ({
      participantId: participant.id,
      score: scoreByParticipant.get(participant.id)
    }))
  );
  const rankByParticipant = new Map(
    finalRanking.map((entry) => [entry.participantId, entry.rank])
  );
  const participants = scenario.participants.map((participant) => ({
    id: participant.id,
    label: participant.label,
    score: experiment ? scoreByParticipant.get(participant.id) : null,
    finalRank: experiment ? rankByParticipant.get(participant.id) : null,
    performance: summarizePerformance(
      events.filter((event) =>
        event.kind === "performance-judgement"
        && event.participantId === participant.id
      )
    ),
    contributions: experiment
      ? [...contributionByParticipant.get(participant.id).values()].sort((left, right) =>
          right.amount - left.amount
          || `${left.owner.kind}:${left.owner.id}`.localeCompare(
            `${right.owner.kind}:${right.owner.id}`
          )
        )
      : []
  }));
  const segments = scenario.music.ranges.map((range) => ({
    index: range.index,
    mission: range.mission,
    start: range.start,
    end: range.end,
    performance: scenario.participants.map((participant) => ({
      participantId: participant.id,
      ...summarizePerformance(
        events.filter((event) =>
          event.kind === "performance-judgement"
          && event.participantId === participant.id
          && event.segmentIndex === range.index
        )
      )
    })),
    luckInputs: events
      .filter((event) => event.kind === "luck-outcome" && event.segmentIndex === range.index)
      .map((event) => ({
        participantId: event.participantId,
        value: event.value,
        evidenceStatus: event.evidenceStatus
      })),
    ranking: experiment
      ? rankingFromScores(
          scenario.participants.map((participant) => ({
            participantId: participant.id,
            score: segmentScores.get(range.index).get(participant.id)
          }))
        )
      : []
  }));
  return {
    schemaVersion: 1,
    ruleSetVersion: GEKISOU_RULE_SET.id,
    sourceReleaseId: scenario.sourceReleaseId,
    scenarioHash: scenario.scenarioHash,
    status: experiment ? "experimental" : "blocked",
    scoreStatus: experiment ? "counterfactual-only" : "unavailable",
    optimizerEligible: false,
    issues: [],
    blockers: experiment ? [] : ["score_formula_unverified"],
    participants,
    segments,
    ledger,
    ledgerHash: stableSnapshotHash(ledger),
    evidence: {
      overall: experiment ? "counterfactual" : "reconstructed-rule",
      fixedStructure: "confirmed-data",
      scoreFormula: experiment ? "counterfactual" : "unsupported"
    }
  };
}
