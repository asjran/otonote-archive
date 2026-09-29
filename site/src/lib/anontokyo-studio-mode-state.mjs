export const STUDIO_MODES = Object.freeze(["gameFaithful", "free"]);


function clone(value) {
  return structuredClone(value);
}


export function modeStorageKey(baseKey, mode) {
  if (!STUDIO_MODES.includes(mode)) throw new TypeError("unknown Studio mode");
  return `${baseKey}:${mode === "gameFaithful" ? "game-faithful" : "free"}:v2`;
}


function layoutDocument(payload, mode) {
  const sizes = payload.studio.storeSizes;
  const storeSize = mode === "gameFaithful" ? sizes[0] : sizes.at(-1);
  const placements = payload.studio.modes?.[mode]?.defaultLayout ?? [];
  return {
    schemaVersion: 1,
    sourceReleaseId: payload.sourceReleaseId,
    catalogHash: payload.studio.catalogHash,
    storeSize: { ...storeSize },
    placements: clone(placements),
  };
}


function deliveryState(payload, mode) {
  const first = payload.studio.deliveryOptions?.[0] ?? null;
  const start = payload.studio.scene?.deliveryStart ?? { x: 0, y: 0 };
  return {
    visible: true,
    optionId: first?.id ?? null,
    x: mode === "gameFaithful" ? start.x : 0,
    y: mode === "gameFaithful" ? start.y : 0,
  };
}


function warehouseState(payload, mode) {
  const source = payload.studio.scene?.warehouse ?? { x: 0, y: 0 };
  return {
    visible: mode === "gameFaithful",
    x: source.x,
    y: source.y,
  };
}


function defaultSnapshot(payload, mode) {
  return {
    schemaVersion: 2,
    mode,
    document: layoutDocument(payload, mode),
    delivery: deliveryState(payload, mode),
    warehouse: warehouseState(payload, mode),
    viewport: null,
  };
}


export function createModeDefaults(payload) {
  return {
    gameFaithful: defaultSnapshot(payload, "gameFaithful"),
    free: defaultSnapshot(payload, "free"),
  };
}


function isSnapshot(value, mode) {
  return Boolean(
    value &&
    value.schemaVersion === 2 &&
    value.mode === mode &&
    value.document &&
    value.document.schemaVersion === 1 &&
    Array.isArray(value.document.placements) &&
    value.document.storeSize &&
    value.delivery &&
    typeof value.delivery.visible === "boolean" &&
    Number.isInteger(value.delivery.x) &&
    Number.isInteger(value.delivery.y) &&
    value.warehouse &&
    typeof value.warehouse.visible === "boolean" &&
    Number.isInteger(value.warehouse.x) &&
    Number.isInteger(value.warehouse.y)
  );
}


function isLegacyDocument(value) {
  return Boolean(
    value &&
    value.schemaVersion === 1 &&
    Array.isArray(value.placements) &&
    value.storeSize
  );
}


export function restoreModeDocuments(payload, stored = {}) {
  const defaults = createModeDefaults(payload);
  const warnings = [];
  const result = {};
  for (const mode of STUDIO_MODES) {
    const candidate = stored[mode];
    if (candidate === undefined || candidate === null) {
      result[mode] = defaults[mode];
    } else if (isSnapshot(candidate, mode)) {
      result[mode] = clone(candidate);
    } else {
      result[mode] = defaults[mode];
      warnings.push(mode);
    }
  }
  let migratedLegacy = false;
  if (
    !stored.free &&
    isLegacyDocument(stored.legacy)
  ) {
    result.free = {
      ...defaults.free,
      document: clone(stored.legacy),
    };
    migratedLegacy = true;
  }
  return {
    ...result,
    warnings,
    migratedLegacy,
  };
}
