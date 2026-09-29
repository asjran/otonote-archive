/** Activity effects have distinct destinations. Adapters are version-bound
 * application modules, never executable scripts taken from imported JSON. */
export const EVENT_PHASES = Object.freeze(["member_power", "support_power", "song_context", "note_score", "fixed_score", "event_points", "rewards"]);

export function resolveEventContext(rules, context, adapters = []) {
  if (context != null && (typeof context !== "object" || Array.isArray(context))) throw new Error("Invalid event context");
  if (context == null || context.id == null) {
    if (context && Object.keys(context).some((k) => !["id"].includes(k))) throw new Error("Invalid no-event context");
    return { id: null, sourceReleaseId: rules.sourceReleaseId, effects: [], status: "no_event" };
  }
  if (context.sourceReleaseId !== rules.sourceReleaseId) throw new Error("event release_mismatch");
  if (!Number.isSafeInteger(context.id) || context.id < 1) throw new Error("Invalid event id");
  const event = rules.tables.Event?.find((r) => r._id === context.id);
  if (!event) throw new Error(`活动 ${context.id} 不在当前数据版本中`);
  const adapter = adapters.find((a) => a.sourceReleaseId === rules.sourceReleaseId && a.supports(event));
  if (!adapter) throw new Error(`unsupported_event_mechanism: ${context.id}`);
  const result = adapter.resolve(event, rules, context);
  if (!Array.isArray(result.effects) || result.effects.some((e) => !EVENT_PHASES.includes(e.phase))) {
    throw new Error("Invalid event adapter output");
  }
  return { ...result, id: context.id, sourceReleaseId: rules.sourceReleaseId };
}

/** A future, audited adapter supplies code for EACH declared destination.
 * Imported data cannot run code. No common multiplier leaks points/rewards
 * into note scores; callers explicitly invoke the destination they need. */
export function createEventPipeline(rules, context, adapters = []) {
  const resolved = resolveEventContext(rules, context, adapters);
  const adapter = resolved.id == null ? null : adapters.find(a => a.sourceReleaseId === rules.sourceReleaseId
    && a.supports(rules.tables.Event.find(r => r._id === resolved.id)));
  const phases = new Set(resolved.effects.map(e => e.phase));
  for (const phase of phases) if (typeof adapter?.handlers?.[phase] !== "function") throw new Error(`Missing event phase handler: ${phase}`);
  return {
    context: resolved,
    apply(phase, value, input = {}) {
      if (!EVENT_PHASES.includes(phase)) throw new Error(`Unknown event phase: ${phase}`);
      if (!phases.has(phase)) return value;
      return adapter.handlers[phase](structuredClone(value), resolved.effects.filter(e => e.phase === phase),
        { ...input, event: resolved, rules });
    }
  };
}
