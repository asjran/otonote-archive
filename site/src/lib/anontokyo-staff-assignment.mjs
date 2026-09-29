export const ASSIGNMENT_SCHEMA_VERSION = 1;
export const STANDBY_ROLE = "standby";


function records(dataset) {
  return Array.isArray(dataset?.records) ? dataset.records : [];
}


function studio(dataset) {
  const value = dataset?.assignmentStudio;
  if (!value || !Array.isArray(value.roles) || !Array.isArray(value.capacityByLevel)) {
    throw new Error("AnonTokyo staff assignment dataset is incomplete");
  }
  return value;
}


function clampLevel(value) {
  const number = Number.isInteger(value) ? value : Number.parseInt(String(value), 10);
  if (!Number.isFinite(number)) return 20;
  return Math.max(1, Math.min(20, number));
}


export function assignmentContext(dataset, state) {
  const config = studio(dataset);
  const mode = state?.mode === "level" ? "level" : "free";
  const level = clampLevel(state?.level ?? 20);
  const capacityRow = config.capacityByLevel.find((item) => item.level === level);
  if (mode === "level" && !capacityRow) {
    throw new Error(`AnonTokyo staff assignment has no capacity row for level ${level}`);
  }
  return {
    mode,
    level,
    capacities:
      mode === "free"
        ? { ...config.freePreviewCapacities }
        : { ...capacityRow.capacities },
    roles: config.roles.map((role) => ({ ...role })),
  };
}


export function createDefaultAssignmentState(dataset, overrides = {}) {
  const mode = overrides.mode === "level" ? "level" : "free";
  const level = clampLevel(overrides.level ?? 20);
  return {
    schemaVersion: ASSIGNMENT_SCHEMA_VERSION,
    mode,
    level,
    assignments: Object.fromEntries(
      records(dataset).map((character) => [character.id, STANDBY_ROLE])
    )
  };
}


function correction(code, characterId = null) {
  return characterId ? { code, characterId } : { code };
}


export function normalizeAssignmentState(dataset, input) {
  const corrections = [];
  const source = input && typeof input === "object" ? input : {};
  if (source.schemaVersion !== ASSIGNMENT_SCHEMA_VERSION) {
    corrections.push(correction("schema_version"));
  }
  const mode = source.mode === "level" || source.mode === "free" ? source.mode : "free";
  if (mode !== source.mode) corrections.push(correction("invalid_mode"));
  const level = clampLevel(source.level ?? 20);
  if (level !== source.level) corrections.push(correction("invalid_level"));

  const state = createDefaultAssignmentState(dataset, { mode, level });
  const context = assignmentContext(dataset, state);
  const roleIds = new Set(context.roles.map((role) => role.id));
  const counts = Object.fromEntries(context.roles.map((role) => [role.id, 0]));
  const proposed = source.assignments && typeof source.assignments === "object"
    ? source.assignments
    : {};
  const knownIds = new Set(records(dataset).map((character) => character.id));

  for (const character of records(dataset)) {
    const target = proposed[character.id] ?? STANDBY_ROLE;
    if (target === STANDBY_ROLE) continue;
    if (!roleIds.has(target)) {
      corrections.push(correction("invalid_role", character.id));
      continue;
    }
    if (mode === "level" && Number(character.levelLimit ?? 0) > level) {
      corrections.push(correction("character_locked", character.id));
      continue;
    }
    if (counts[target] >= Number(context.capacities[target] ?? 0)) {
      corrections.push(correction("role_overflow", character.id));
      continue;
    }
    state.assignments[character.id] = target;
    counts[target] += 1;
  }

  for (const characterId of Object.keys(proposed)) {
    if (!knownIds.has(characterId)) {
      corrections.push(correction("unknown_character", characterId));
    }
  }

  return { state, corrections };
}


export function assignCharacter(dataset, input, characterId, targetRole) {
  const normalized = normalizeAssignmentState(dataset, input);
  const state = normalized.state;
  const character = records(dataset).find((item) => item.id === characterId);
  if (!character) {
    return { state, error: { code: "unknown_character", characterId } };
  }
  const context = assignmentContext(dataset, state);
  const roleIds = new Set(context.roles.map((role) => role.id));
  if (targetRole !== STANDBY_ROLE && !roleIds.has(targetRole)) {
    return { state, error: { code: "unknown_role", characterId, role: targetRole } };
  }
  if (state.mode === "level" && Number(character.levelLimit ?? 0) > state.level) {
    return {
      state,
      error: {
        code: "character_locked",
        characterId,
        requiredLevel: Number(character.levelLimit ?? 0)
      }
    };
  }
  if (targetRole !== STANDBY_ROLE && state.assignments[characterId] !== targetRole) {
    const occupied = Object.entries(state.assignments).filter(
      ([id, role]) => id !== characterId && role === targetRole
    ).length;
    if (occupied >= Number(context.capacities[targetRole] ?? 0)) {
      return {
        state,
        error: { code: "role_full", characterId, role: targetRole }
      };
    }
  }
  return {
    state: {
      ...state,
      assignments: { ...state.assignments, [characterId]: targetRole }
    },
    error: null
  };
}
