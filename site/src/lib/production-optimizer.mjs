import { createFormationCalculator } from "./scoring-rules/formation-power.mjs";
import { stableSnapshotHash } from "./scoring-engine.mjs";
import { createFormalSongCalculator } from "./scoring-rules/formal-song-score.mjs";

function* permutations(values, prefix = []) {
  if (!values.length) { yield prefix; return; }
  for (let i = 0; i < values.length; i += 1) {
    yield* permutations([...values.slice(0, i), ...values.slice(i + 1)], [...prefix, values[i]]);
  }
}

/** Exact search over the chosen 5 members, 5 supports and all 5 leaders.
 * Non-leader order affects neither power nor the mean over all 120 random skill
 * orders. This is a selected-card search, not a global card-library optimum.
 */
export async function optimizeProductionPairing({ rules, draft, chart, objective = "formation_power", signal, onProgress, topN = 10,
  yieldControl = () => new Promise((resolve) => setTimeout(resolve, 0)) }) {
  if (!Number.isInteger(topN) || topN < 1 || topN > 600) throw new RangeError("Invalid topN");
  if (draft.slots?.length !== 5 || draft.slots.some((s) => !s.memberCardId || !s.supportCardId)) {
    throw new Error("请选择五张成员卡和五张留影后再比较配对");
  }
  const calculator = createFormationCalculator(rules);
  if (!["formation_power", "expected_song_score"].includes(objective)) throw new Error("Unknown optimizer objective");
  const song = objective === "expected_song_score" ? createFormalSongCalculator(rules, chart) : null;
  const baseline = calculator.calculate(draft);
  const baselineScore = song?.calculate(draft);
  const baselineValue = baselineScore?.expectedScore ?? baseline.total.total;
  const members = draft.slots.map((s) => s.memberCardId);
  const supports = draft.slots.map((s) => s.supportCardId);
  const results = [];
  let evaluated = 0;
  for (let leader = 0; leader < 5; leader += 1) {
    const order = [...members];
    [order[2], order[leader]] = [order[leader], order[2]];
    for (const supportOrder of permutations(supports)) {
      if (signal?.aborted) return { status: "cancelled", results: [], evaluated };
      const candidate = { ...draft, slots: order.map((memberCardId, i) =>
        ({ memberCardId, supportCardId: supportOrder[i] })) };
      const power = calculator.calculate(candidate);
      const score = song?.calculate(candidate);
      const value = score?.expectedScore ?? power.total.total;
      const candidateId = candidate.slots.map((s) => `${s.memberCardId}+${s.supportCardId}`).join("|");
      results.push({ id: candidateId, draft: candidate, power: power.total.total, value,
        ...(score ? { expectedScore: score.expectedScore, minimumScore: score.minimumScore, maximumScore: score.maximumScore } : {}),
        delta: value - baselineValue, breakdown: power.breakdown });
      results.sort((a, b) => b.value - a.value || a.id.localeCompare(b.id));
      if (results.length > topN) results.pop();
      evaluated += 1;
      if (evaluated % 20 === 0) {
        onProgress?.({ completed: evaluated, total: 600 });
        await yieldControl(); // A task boundary lets Worker cancel messages run.
      }
    }
  }
  return { status: "completed", objective, searchScope: "selected_5_by_5_and_leader",
    verificationStatus: song ? song.timeline.verificationStatus : rules.verificationStatus, ruleSetVersion: rules.ruleSetVersion,
    warnings: baselineScore?.warnings ?? [],
    inputHash: stableSnapshotHash({ draft, objective, chartHash: song?.timeline.chartHash ?? null,
      ruleSetVersion: rules.ruleSetVersion, sourceReleaseId: rules.sourceReleaseId }),
    baseline: baselineValue, evaluated, totalCandidates: 600, results };
}
