import { skillOrdersFor } from './skill-order-sampling.mjs';
import { createEventPipeline } from "./event-rules.mjs";
import { createFormationCalculator } from "./formation-power.mjs";
import { calculateFormalNoteCore } from "./formal-note-core.mjs";
import { createFormalSkillResolver } from "./formal-skills.mjs";
import { createFormalTickConverter } from "./formal-time.mjs";
import { reconstructFormalChart } from "./formal-chart.mjs";
import { stableSnapshotHash } from "../scoring-engine.mjs";
import { referenceScoringRules } from '../scoring-release-gate.mjs';

const f32 = Math.fround;


/** Reconstruct scoring events from authored nodes using production code.
 * Whole-song status retains the ideal-input / simultaneous-order limitation. */
export function prepareFormalChart(rules, chart) {
  if ((!referenceScoringRules(rules) && rules.native?.sourceReleaseId !== rules.sourceReleaseId) || rules.native?.nativeSha256 !== rules.nativeSha256) {
    throw new Error("Native scoring release_mismatch");
  }
  if (!chart?.notes?.length) throw new Error("请先选择并加载完整谱面");
  if (chart.sourceReleaseId && chart.sourceReleaseId !== rules.sourceReleaseId) throw new Error("Chart release_mismatch");
  const masterId = Number(/^music-chart-(\d+)$/.exec(chart.id)?.[1]);
  const master = rules.tables.LiveMusicScore.find((r) => r._id === masterId);
  if (!master) throw new Error("谱面不属于当前正式版 Master");
  const clock = createFormalTickConverter(chart.bpmEvents);
  const weights = new Map(rules.tables.LiveNoteParameter.map((r) => [r._noteOperateType, r._scorePercent]));
  const combos = rules.tables.LiveComboScoreBonus.filter((r) => r._comboBonusType === 0)
    .sort((a, b) => a._requiredComboCount - b._requiredComboCount);
  let cumulative = 0;
  const bonusSteps = combos.map((r) => ({ count: r._requiredComboCount,
    factor: f32(1 + Math.min(1, cumulative = f32(cumulative + f32(r._bonusFactor)))) }));
  const events = reconstructFormalChart(chart).map((event) => {
    if (!Number.isInteger(event.timeMs) || event.timeMs < 0 || !weights.has(event.type)) throw new Error("Invalid scoring event");
    return { ...event, weight: weights.get(event.type) };
  });
  let step = -1;
  events.forEach((event, index) => {
    event.combo = index + 1;
    while (step + 1 < bonusSteps.length && bonusSteps[step + 1].count <= event.combo) step++;
    event.comboFactor = step < 0 ? 1 : bonusSteps[step].factor;
  });
  // Recover exact tick of authored skill positions from rounded display seconds.
  // Fail if the source precision cannot identify an integer tick unambiguously.
  let elapsed = 0;
  // Display seconds were projected with source decimal BPM, before native
  // float32 conversion. Recover ticks in that clock, then use the native one.
  const displaySegments = clock.segments.map(s => ({ ...s, bpm: chart.bpmEvents.find(e => (e.tick ?? e.t) === s.tick)?.bpm ?? 120 }));
  const sourceBpm = displaySegments.map((s, i, all) => {
    if (i) elapsed += (s.tick - all[i - 1].tick) * 60 / (all[i - 1].bpm * 480);
    return { ...s, seconds: elapsed };
  });
  const authoredTime = (seconds) => {
    if (!Number.isFinite(seconds) || seconds < 0) throw new Error("Invalid authored timing");
    const segment = sourceBpm.findLast((s) => s.seconds <= seconds + 0.000001);
    const tick = segment.tick + Math.round((seconds - segment.seconds) * segment.bpm * 8);
    const reconstructed = segment.seconds + (tick - segment.tick) / (segment.bpm * 8);
    if (Math.abs(reconstructed - seconds) > 0.000002) throw new Error("Cannot recover authored tick");
    return clock.atTick(tick);
  };
  const skillTimes = (chart.skillTimings ?? []).map(authoredTime).sort((a, b) => a - b);
  // BuildFeverList -> MakePosition uses TickToTimeMs, too. Rounding display
  // seconds directly can move a section edge into the wrong score bucket.
  const gekisouRanges = (chart.gekisouRanges ?? chart.feverRanges ?? []).map(r => ({ startMs: authoredTime(r.start), endMs: authoredTime(r.end) }));
  if (skillTimes.length !== 5 || skillTimes.some((s, i) => i && s <= skillTimes[i - 1])) {
    throw new Error("当前计算仅支持五次成员技能的普通演出谱面");
  }
  const weighted = events.reduce((sum, event) => f32(sum + event.weight), 0);
  const convertedNoteCount = Math.ceil(f32(weighted / 100));
  const warnings = ["谱面节点、滑键补点与时间已按正式包重建；同刻判定顺序及技能触发采用理想输入假设，整曲结果仍为估算。"];
  if (events.length !== master._fullComboCount) warnings.push(`谱面转换 ${events.length} 连击，与正式 Master ${master._fullComboCount} 不一致。`);
  return { chartId: chart.id, trackId: chart.trackId, difficulty: chart.difficulty,
    sourceReleaseId: rules.sourceReleaseId, level: master._musicScoreLevel,
    masterFullCombo: master._fullComboCount, events, skillTimes, gekisouRanges, convertedNoteCount,
    difficultyFactor: f32(1 + f32(f32(master._musicScoreLevel - 5) * rules.native.difficultyIncrement)),
    verificationStatus: referenceScoringRules(rules) ? 'reference_formula_reconstructed_chart' : 'code_formula_reconstructed_chart', warnings,
    chartHash: stableSnapshotHash({ chart, ruleSetVersion: rules.ruleSetVersion, topologyVersion: "global-25-native-bars-v1" }) };
}

export function createFormalSongCalculator(rules, chart, { eventAdapters = [], scorePrecision = 'full' } = {}) {
  const orders = skillOrdersFor(scorePrecision);
  const timeline = prepareFormalChart(rules, chart);
  const formation = createFormationCalculator(rules, { eventAdapters });
  const resolveSkills = createFormalSkillResolver(rules);
  const setting = (key) => Number(rules.tables.LiveSettings.find((r) => r._key === key)?._value);
  const judgement = rules.tables.LiveJudgementParameter.find((r) => r._noteSimulateJudgement === 5)._scorePercent;
  function calculate(draft, { includeTrace = false } = {}) {
    if (draft.slots?.length !== 5 || draft.slots.some((s) => !s.memberCardId || !s.supportCardId)) throw new Error("请选择五张成员卡和五张留影");
    if (draft.selectedSongId !== timeline.trackId || draft.selectedDifficulty !== timeline.difficulty) throw new Error("歌曲或难度与载入谱面不一致");
    const power = formation.calculate(draft);
    const eventPipeline = createEventPipeline(rules, draft.modifiers?.event, eventAdapters);
    const skills = resolveSkills(draft);
    const common = { totalPower: power.total.total, scoreAdjustmentFactor: setting("note_score_adjustment_factor"),
      musicScoreLevelFactor: timeline.difficultyFactor, judgementFactorPercent: judgement,
      luckScoreFactorPercent: 100, convertedNoteCount: timeline.convertedNoteCount,
      eventBonusFactor: 1, lifeOnusFactor: setting("note_score_life_onus_factor"),
      assistModeNoteScoreFactor: 1, currentLife: setting("life_base") };
    const noteScore = (event, factor) => calculateFormalNoteCore(eventPipeline.apply("note_score", { ...common, noteFactorPercent: event.weight,
      comboBonusFactor: event.comboFactor, scoreUpFactor: factor }, { draft, note: event })).score;
    const baseNotes = timeline.events.map((event) => noteScore(event, 1));
    const baseScore = baseNotes.reduce((a, b) => a + b, 0);
    // ApplyFactorCommand (0x55e2a14) adds/removes EACH float32 factor.
    // Accumulating integers and dividing once loses native rounding history,
    // including the small residual after a skill ends. Cache note scores by
    // factor, but retain that history across all 120 complete order sweeps.
    const scoreCaches = baseNotes.map((score) => new Map([[1, score]]));
    const orderCache = new Map();
    const scoreOrder = (order, trace = false) => {
      const commands = order.flatMap((slot, i) => skills[slot].liveEffects.filter((e) => e.active).flatMap((effect) => {
        const value = f32(Math.floor(f32(effect.rate * 100000)) / 100000);
        const start = timeline.skillTimes[i];
        return [{ timeMs: start, type: effect.type, value, ending: false },
          { timeMs: start + effect.durationMs, type: effect.type, value: -value, ending: true }];
      })).sort((a, b) => a.timeMs - b.timeMs || Number(b.ending) - Number(a.ending));
      // Different card orders can produce the exact same ordered commands.
      // Retain all 120 orders' probability mass, but evaluate that trace once.
      const cacheKey = !trace && !eventAdapters.length && eventPipeline.context.id == null
        ? JSON.stringify(commands) : null;
      if (cacheKey !== null && orderCache.has(cacheKey)) return orderCache.get(cacheKey);
      let cursor = 0, general = 1, perfect = 0, score = 0;
      const notes = trace ? [] : undefined;
      timeline.events.forEach((event, i) => {
        while (cursor < commands.length && commands[cursor].timeMs <= event.timeMs) {
          const command = commands[cursor++];
          if (command.type === 2000) general = f32(general + command.value);
          else perfect = f32(perfect + command.value);
        }
        const factor = f32(general + perfect);
        let value = scoreCaches[i].get(factor);
        if (value === undefined) { value = noteScore(event, factor); scoreCaches[i].set(factor, value); }
        score += value;
        if (trace) notes.push({ ...event, scoreUpFactor: factor, score: value, cumulativeScore: score });
      });
      const noteTotal = score;
      score = eventPipeline.apply("fixed_score", score, { draft, order });
      if (!Number.isSafeInteger(score) || score < 0) throw new Error("Invalid event fixed score result");
      const result = { score, noteTotal, fixedScore: score - noteTotal, notes };
      if (cacheKey !== null) orderCache.set(cacheKey, result);
      return result;
    };
    let total = 0, noteTotal = 0, minimum = Infinity, maximum = -Infinity, bestOrder, worstOrder;
    for (const order of orders) {
      const scored = scoreOrder(order), score = scored.score;
      total += score; noteTotal += scored.noteTotal;
      if (score < minimum) { minimum = score; worstOrder = order; }
      if (score > maximum) { maximum = score; bestOrder = order; }
    }
    return { status: "estimated", scorePrecision, verificationStatus: timeline.verificationStatus,
      scenario: eventPipeline.context.id == null ? "ordinary_non_event_all_perfect_full_life_no_assist" : "ordinary_event_all_perfect_full_life_no_assist", event: eventPipeline.context, sourceReleaseId: rules.sourceReleaseId,
      ruleSetVersion: rules.ruleSetVersion, inputHash: stableSnapshotHash({ draft, chartHash: timeline.chartHash, ...(scorePrecision === 'screen' ? { scorePrecision } : {}) }),
      power: power.total.total, baseScore, expectedScore: total / orders.length, minimumScore: minimum, maximumScore: maximum,
      skillScoreGain: noteTotal / orders.length - baseScore, eventFixedScoreGain: (total - noteTotal) / orders.length, orderCount: orders.length,
      bestOrder: [...bestOrder], worstOrder: [...worstOrder], skills,
      chart: { id: timeline.chartId, level: timeline.level, difficultyFactor: timeline.difficultyFactor,
        convertedNoteCount: timeline.convertedNoteCount, eventCount: timeline.events.length,
        masterFullCombo: timeline.masterFullCombo, skillTimes: timeline.skillTimes, chartHash: timeline.chartHash },
      warnings: timeline.warnings, ...(includeTrace ? { bestOrderNotes: scoreOrder(bestOrder, true).notes, bestOrderFixedScore: scoreOrder(bestOrder).fixedScore } : {}) };
  }
  function upperBound(totalPower, scoreUpFactor) {
    if (eventAdapters.length) throw new Error("Event optimizer requires an independently audited upper bound");
    return timeline.events.reduce((sum, event) => sum + calculateFormalNoteCore({ totalPower,
      scoreAdjustmentFactor: setting("note_score_adjustment_factor"), musicScoreLevelFactor: timeline.difficultyFactor,
      noteFactorPercent: event.weight, judgementFactorPercent: judgement, comboBonusFactor: event.comboFactor,
      scoreUpFactor, luckScoreFactorPercent: 100, convertedNoteCount: timeline.convertedNoteCount,
      eventBonusFactor: 1, lifeOnusFactor: 1, assistModeNoteScoreFactor: 1, currentLife: 1000 }).score, 0);
  }
  return { calculate, timeline, upperBound };
}
