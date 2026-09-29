const ERROR_MESSAGES = Object.freeze({
  "unknown-furniture": "家具资料不存在",
  "duplicate-instance": "布局实例重复",
  "unsupported-direction": "家具不支持该朝向",
  "outside-store": "家具超出当前店铺范围",
  "non-editable-tile": "家具占用了不可编辑区域",
  "fixed-object-collision": "家具与原地图固定物件重叠",
  collision: "家具与现有布局重叠",
  "unknown-instance": "布局实例不存在",
  "invalid-store-size": "店铺面积不受支持",
  "resize-conflict": "缩小范围会压到现有家具",
  "invalid-document": "布局文件格式不正确",
  "unsupported-schema": "布局文件版本不受支持",
  "missing-furniture": "布局引用了当前资料中不存在的家具"
});


function reject(code, details) {
  return {
    ok: false,
    error: {
      code,
      message: ERROR_MESSAGES[code],
      ...(details === undefined ? {} : { details })
    }
  };
}


function footprintFor(furniture, direction) {
  const rotated = direction % 2 === 1;
  return rotated
    ? { width: furniture.footprint.height, height: furniture.footprint.width }
    : { ...furniture.footprint };
}


function overlaps(left, right) {
  return (
    left.x < right.x + right.width &&
    left.x + left.width > right.x &&
    left.y < right.y + right.height &&
    left.y + left.height > right.y
  );
}


function occupiedTiles(catalog, placement, footprint) {
  const map = catalog.map;
  if (
    !map ||
    !Number.isInteger(map.grid?.width) ||
    !Number.isInteger(map.storeAnchorTileIndex)
  ) return [];
  const result = [];
  for (let y = placement.y; y < placement.y + footprint.height; y += 1) {
    for (let x = placement.x; x < placement.x + footprint.width; x += 1) {
      result.push(map.storeAnchorTileIndex - y * map.grid.width + x);
    }
  }
  return result;
}


function validatePlacement(document, catalog, placement, ignoredInstanceId = null) {
  if (
    !placement ||
    typeof placement !== "object" ||
    typeof placement.instanceId !== "string" ||
    !placement.instanceId
  ) return reject("invalid-document");
  const furniture = catalog.furniture.find(
    (item) => item.id === placement?.furnitureId
  );
  if (!furniture) return reject("unknown-furniture");
  if (!furniture.directions.includes(placement.direction)) {
    return reject("unsupported-direction");
  }
  const footprint = footprintFor(furniture, placement.direction);
  if (
    !Number.isInteger(placement.x) ||
    !Number.isInteger(placement.y) ||
    placement.x < 0 ||
    placement.y < 0 ||
    placement.x + footprint.width > document.storeSize.width ||
    placement.y + footprint.height > document.storeSize.height
  ) {
    return reject("outside-store");
  }
  const tiles = occupiedTiles(catalog, placement, footprint);
  const fixed = new Set(catalog.map?.fixedTileIndexes ?? []);
  if (tiles.some((tile) => fixed.has(tile))) {
    return reject("fixed-object-collision");
  }
  const editable = new Set(catalog.map?.editableTileIndexes ?? []);
  if (editable.size > 0 && tiles.some((tile) => !editable.has(tile))) {
    return reject("non-editable-tile");
  }
  const candidate = { x: placement.x, y: placement.y, ...footprint };
  const collision = document.placements.some((existing) => {
    if (existing.instanceId === ignoredInstanceId) return false;
    const existingFurniture = catalog.furniture.find(
      (item) => item.id === existing.furnitureId
    );
    if (!existingFurniture) return false;
    return overlaps(candidate, {
      x: existing.x,
      y: existing.y,
      ...footprintFor(existingFurniture, existing.direction)
    });
  });
  return collision ? reject("collision") : { ok: true };
}


export function applyLayoutCommand(document, catalog, command) {
  if (command?.type === "place") {
    const placement = command.placement;
    if (document.placements.some((item) => item.instanceId === placement?.instanceId)) {
      return reject("duplicate-instance");
    }
    const validation = validatePlacement(document, catalog, placement);
    if (!validation.ok) return validation;
    return {
      ok: true,
      document: {
        ...document,
        placements: [...document.placements, { ...placement }]
      }
    };
  }

  if (command?.type === "duplicate") {
    const current = document.placements.find(
      (item) => item.instanceId === command.instanceId
    );
    if (!current) return reject("unknown-instance");
    const placement = {
      ...current,
      instanceId: command.newInstanceId,
      x: command.x,
      y: command.y
    };
    if (
      !placement.instanceId ||
      document.placements.some((item) => item.instanceId === placement.instanceId)
    ) return reject("duplicate-instance");
    const validation = validatePlacement(document, catalog, placement);
    if (!validation.ok) return validation;
    return {
      ok: true,
      document: {
        ...document,
        placements: [...document.placements, placement]
      }
    };
  }

  if (command?.type === "move" || command?.type === "rotate") {
    const current = document.placements.find(
      (item) => item.instanceId === command.instanceId
    );
    if (!current) return reject("unknown-instance");
    const placement = {
      ...current,
      ...(command.type === "move" ? { x: command.x, y: command.y } : {}),
      ...(command.type === "rotate" ? { direction: command.direction } : {})
    };
    const validation = validatePlacement(
      document,
      catalog,
      placement,
      current.instanceId
    );
    if (!validation.ok) return validation;
    return {
      ok: true,
      document: {
        ...document,
        placements: document.placements.map((item) =>
          item.instanceId === current.instanceId ? placement : item
        )
      }
    };
  }

  if (command?.type === "remove") {
    if (!document.placements.some((item) => item.instanceId === command.instanceId)) {
      return reject("unknown-instance");
    }
    return {
      ok: true,
      document: {
        ...document,
        placements: document.placements.filter(
          (item) => item.instanceId !== command.instanceId
        )
      }
    };
  }

  if (command?.type === "resize" || command?.type === "resizeStore") {
    const supported = catalog.storeSizes.some(
      (size) =>
        size.level === command.storeSize?.level &&
        size.width === command.storeSize.width &&
        size.height === command.storeSize.height
    );
    if (!supported) return reject("invalid-store-size");
    const resized = { ...document, storeSize: { ...command.storeSize } };
    const conflicts = resized.placements.some(
      (placement) => !validatePlacement(
        { ...resized, placements: resized.placements },
        catalog,
        placement,
        placement.instanceId
      ).ok
    );
    return conflicts ? reject("resize-conflict") : { ok: true, document: resized };
  }

  if (command?.type === "clear") {
    return { ok: true, document: { ...document, placements: [] } };
  }

  if (command?.type === "restoreInitial") {
    const restored = { ...document, placements: [] };
    for (const placement of catalog.initialLayout ?? []) {
      const result = applyLayoutCommand(restored, catalog, {
        type: "place",
        placement
      });
      if (!result.ok) return result;
      restored.placements = result.document.placements;
    }
    return { ok: true, document: restored };
  }

  return reject("unknown-furniture");
}


export function validateLayoutDocument(value, catalog, current) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return reject("invalid-document");
  }
  if (value.schemaVersion !== 1) return reject("unsupported-schema");
  if (!Array.isArray(value.placements) || !value.storeSize) {
    return reject("invalid-document");
  }
  const missing = [...new Set(value.placements
    .map((placement) => placement?.furnitureId)
    .filter((id) => typeof id !== "string" || !catalog.furniture.some((item) => item.id === id))
  )].filter((id) => typeof id === "string").sort();
  if (missing.length > 0) return reject("missing-furniture", missing);

  const base = {
    ...value,
    sourceReleaseId: current.sourceReleaseId,
    catalogHash: current.catalogHash,
    placements: []
  };
  const resized = applyLayoutCommand(
    { ...base, storeSize: catalog.storeSizes.at(-1), placements: [] },
    catalog,
    { type: "resizeStore", storeSize: value.storeSize }
  );
  if (!resized.ok) return resized;
  let document = { ...base, storeSize: { ...value.storeSize } };
  for (const placement of value.placements) {
    const placed = applyLayoutCommand(document, catalog, { type: "place", placement });
    if (!placed.ok) return placed;
    document = placed.document;
  }
  return { ok: true, document };
}
