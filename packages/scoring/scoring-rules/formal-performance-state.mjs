import { scoreFrame } from './formal-score-replay.mjs';

/** LiveLifeController.ApplyCommand 0x55c7b04. Values use native int32 math.
 * Commands: note damage, skill damage, recovery, guard +/- and reduction +/-. */
export function applyLifeCommand(state, command, maximumLife) {
  let { life, guard, reduction } = state;
  const { kind, value = 0, safety = false, overHeal = false } = command;
  const damage = reduction <= 0 ? value : reduction >= 10000 ? 0
    : Math.max(0, Math.trunc(Math.imul(10000 - reduction, value) / 10000));
  if (kind === 0 && guard <= 0) life = Math.max(0, (life - damage) | 0);
  else if (kind === 1 && guard <= 0 && (life > 0 || !safety)) life = Math.max(safety ? 1 : 0, (life - damage) | 0);
  else if (kind === 2 && life > 0) life = Math.min((life + value) | 0, maximumLife * (overHeal ? 2 : 1));
  else if (kind === 3) guard = (guard + 1) | 0;
  else if (kind === 4) guard = Math.max(0, guard - 1);
  else if (kind === 5) reduction = (reduction + value) | 0;
  else if (kind === 6) reduction = Math.max(0, (reduction - value) | 0);
  return { life, guard, reduction };
}

/** GetLifeAtMs 0x55c77e4 and AddCommand 0x55c73a8.
 * Preserve the native cached prefix, including its cursor-only invalidation
 * when a late command is inserted. Rebuilding a clean historical fold would
 * differ from the client for explicitly delayed inputs. */
export function createLifeReplay(maximumLife, musicLengthMs) {
  const lastBucket = scoreFrame(musicLengthMs) + 49;
  const bucketOf = time => Math.min(lastBucket, scoreFrame(time));
  const buckets = new Map();
  let cacheBucket = -1, cache = { life: maximumLife, guard: 0, reduction: 0 };
  function add(command) {
    const bucket = bucketOf(command.timeMs);
    if (!buckets.has(bucket)) buckets.set(bucket, []);
    const commands = buckets.get(bucket);
    let index = commands.length;
    while (index && commands[index - 1].timeMs > command.timeMs) index--;
    commands.splice(index, 0, { ...command });
    if (cacheBucket >= bucket) cacheBucket = bucket - 1;
  }
  function at(timeMs) {
    const target = bucketOf(timeMs), reuse = cacheBucket >= 0 && cacheBucket < target;
    let state = reuse ? { ...cache } : { life: maximumLife, guard: 0, reduction: 0 };
    const first = reuse ? cacheBucket + 1 : 0;
    for (let bucket = first; bucket < target; bucket++) {
      for (const command of buckets.get(bucket) ?? []) state = applyLifeCommand(state, command, maximumLife);
    }
    if (cacheBucket < target || cacheBucket < 0) { cacheBucket = target - 1; cache = { ...state }; }
    for (const command of buckets.get(target) ?? []) {
      if (command.timeMs > timeMs) break;
      state = applyLifeCommand(state, command, maximumLife);
    }
    return state.life;
  }
  return { add, at };
}

/** ComboCounter.RecomputeStateFrom 0x6a57284 / GetTimingCombo 0x6a57398.
 * Entries retain arrival order within a timestamp; scoring queries are strict
 * '< chart time', so simultaneous notes share the pre-group combo. */
export function createComboReplay(bonusRows) {
  const entries = [];
  const steps = bonusRows.filter(row => row._comboBonusType === 0).sort((a, b) => a._requiredComboCount - b._requiredComboCount);
  let sum = 0;
  const bonuses = steps.map(row => ({ count: row._requiredComboCount,
    factor: Math.fround(1 + Math.min(1, sum = Math.fround(sum + Math.fround(row._bonusFactor)))) }));
  function add(timeMs, judgement) {
    let index = entries.length;
    while (index && entries[index - 1].timeMs > timeMs) index--;
    entries.splice(index, 0, { timeMs, judgement });
    let combo = index ? entries[index - 1].combo : 0;
    let maxCombo = index ? entries[index - 1].maxCombo : 0;
    let allPerfect = index ? entries[index - 1].allPerfect : true;
    let fullCombo = index ? entries[index - 1].fullCombo : true;
    for (; index < entries.length; index++) {
      const entry = entries[index];
      combo = entry.judgement <= 2 ? 0 : combo + 1;
      maxCombo = Math.max(maxCombo, combo);
      allPerfect &&= entry.judgement >= 5;
      fullCombo &&= entry.judgement >= 3;
      Object.assign(entry, { combo, maxCombo, allPerfect, fullCombo });
    }
  }
  function at(timeMs) {
    let lo = 0, hi = entries.length;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (entries[mid].timeMs < timeMs) lo = mid + 1; else hi = mid; }
    const combo = lo ? entries[lo - 1].combo : 0;
    return { combo, comboFactor: bonuses.findLast(step => step.count <= combo)?.factor ?? 1 };
  }
  return { add, at, get state() { return entries.at(-1) ?? { combo: 0, maxCombo: 0, allPerfect: true, fullCombo: true }; } };
}
