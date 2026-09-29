export const GOLDEN_REPLAY_SCHEMA_VERSION = 1;
export const GOLDEN_REPLAY_STATUSES = Object.freeze([
  "fixture",
  "observed",
  "reconciled",
  "rejected"
]);

const finiteInteger = (value) =>
  Number.isSafeInteger(value) && Number.isFinite(value);

const issue = (code, path, message) => ({ code, path, message });

export function validateGoldenReplay(replay) {
  const issues = [];
  if (!replay || typeof replay !== "object" || Array.isArray(replay)) {
    return [issue("invalid_replay", "", "Golden Replay must be an object")];
  }
  if (replay.schemaVersion !== GOLDEN_REPLAY_SCHEMA_VERSION) {
    issues.push(issue("unsupported_schema", "schemaVersion", "Unsupported Golden Replay schema"));
  }
  for (const key of ["sampleId", "sourceReleaseId", "ruleSetVersion"]) {
    if (typeof replay[key] !== "string" || replay[key].length === 0) {
      issues.push(issue("required_string", key, `${key} is required`));
    }
  }
  if (!GOLDEN_REPLAY_STATUSES.includes(replay.verificationStatus)) {
    issues.push(issue("invalid_verification_status", "verificationStatus", "Unknown verification status"));
  }
  if (!Array.isArray(replay.sourceEvidence)) {
    issues.push(issue(
      "source_evidence_required",
      "sourceEvidence",
      "sourceEvidence must be an array"
    ));
  } else if (
    ["observed", "reconciled"].includes(replay.verificationStatus)
    && replay.sourceEvidence.length === 0
  ) {
    issues.push(issue(
      "client_evidence_required",
      "sourceEvidence",
      "Observed and reconciled samples require client evidence"
    ));
  }
  for (const key of ["judgements", "scoreCommands"]) {
    if (!Array.isArray(replay[key])) {
      issues.push(issue(
        "required_array",
        key,
        `${key} must be an array, including when empty`
      ));
    }
  }
  if (!finiteInteger(replay.formation?.totalPower) || replay.formation.totalPower < 0) {
    issues.push(issue("invalid_total_power", "formation.totalPower", "Formation power must be a non-negative integer"));
  }
  if (!Array.isArray(replay.chart?.events) || replay.chart.events.length === 0) {
    issues.push(issue("events_required", "chart.events", "At least one scoring event is required"));
  } else {
    replay.chart.events.forEach((event, index) => {
      for (const key of [
        "notePercent",
        "judgementPercent",
        "comboPercent",
        "scorePercent",
        "fixedScore"
      ]) {
        if (!finiteInteger(event?.[key])) {
          issues.push(issue("integer_required", `chart.events[${index}].${key}`, `${key} must be an integer`));
        }
      }
    });
  }
  if (!finiteInteger(replay.expected?.finalScore)) {
    issues.push(issue("expected_score_required", "expected.finalScore", "Expected final score is required"));
  }
  return issues;
}

function calculateFixtureEvent(totalPower, event, accumulatedScore) {
  const floorAfterBase = Math.floor((totalPower * event.notePercent) / 100);
  const factorNumerator =
    event.judgementPercent * event.comboPercent * event.scorePercent;
  const floorAfterFactors = Math.floor(
    (floorAfterBase * factorNumerator) / 1_000_000
  );
  const score = floorAfterFactors + event.fixedScore;
  if (![floorAfterBase, floorAfterFactors, score].every(Number.isSafeInteger)) {
    throw new RangeError("Scoring fixture exceeded the safe integer range");
  }
  return {
    eventId: event.id ?? null,
    totalPower,
    notePercent: event.notePercent,
    judgementPercent: event.judgementPercent,
    comboPercent: event.comboPercent,
    scorePercent: event.scorePercent,
    fixedScore: event.fixedScore,
    floorAfterBase,
    floorAfterFactors,
    score,
    accumulatedBefore: accumulatedScore,
    accumulatedAfter: accumulatedScore + score
  };
}

export function reconcileGoldenReplay(replay) {
  const issues = validateGoldenReplay(replay);
  if (issues.length > 0) {
    return {
      status: "invalid_input",
      formal: false,
      score: null,
      issues,
      trace: []
    };
  }
  if (replay.ruleSetVersion !== "scoring-fixture-v1") {
    return {
      status: "unsupported_rule_set",
      formal: false,
      score: null,
      issues: [],
      trace: []
    };
  }

  let score = 0;
  const trace = replay.chart.events.map((event) => {
    const entry = calculateFixtureEvent(replay.formation.totalPower, event, score);
    score = entry.accumulatedAfter;
    return entry;
  });
  const expectedNotes = Array.isArray(replay.expected.noteScores)
    ? replay.expected.noteScores
    : [];
  const noteMismatchIndex = trace.findIndex(
    (entry, index) =>
      expectedNotes[index] !== undefined && expectedNotes[index] !== entry.score
  );
  const finalMatches = replay.expected.finalScore === score;
  const matched = noteMismatchIndex === -1 && finalMatches;
  return {
    status: matched
      ? replay.verificationStatus === "reconciled"
        ? "reconciled"
        : "matched_fixture"
      : "mismatch",
    formal: matched && replay.verificationStatus === "reconciled",
    score,
    expectedScore: replay.expected.finalScore,
    issues: [],
    trace,
    difference: matched
      ? null
      : {
          eventIndex: noteMismatchIndex === -1 ? null : noteMismatchIndex,
          expected:
            noteMismatchIndex === -1
              ? replay.expected.finalScore
              : expectedNotes[noteMismatchIndex],
          actual:
            noteMismatchIndex === -1 ? score : trace[noteMismatchIndex].score
        }
  };
}
