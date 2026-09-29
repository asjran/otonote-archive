import assert from "node:assert/strict";
import test from "node:test";

import {
  applyLayoutCommand,
  validateLayoutDocument
} from "../src/lib/anontokyo-layout-engine.mjs";


const catalog = {
  map: {
    grid: { width: 10, height: 10 },
    storeAnchorTileIndex: 80,
    editableTileIndexes: [80, 81, 82, 83, 70, 71, 72, 73, 60, 61, 62, 63, 50, 51, 53],
    fixedTileIndexes: [53]
  },
  furniture: [
    {
      id: "rack",
      footprint: { width: 1, height: 2 },
      directions: [0, 1, 2, 3]
    }
  ],
  storeSizes: [
    { level: 0, width: 1, height: 1 },
    { level: 1, width: 4, height: 4 }
  ]
};

const emptyLayout = {
  schemaVersion: 1,
  sourceReleaseId: "global-staging-fixture",
  catalogHash: "catalog-fixture",
  storeSize: { level: 1, width: 4, height: 4 },
  placements: []
};


test("place accepts a legal footprint and rejects an out-of-bounds footprint", () => {
  const placed = applyLayoutCommand(emptyLayout, catalog, {
    type: "place",
    placement: {
      instanceId: "rack-1",
      furnitureId: "rack",
      x: 1,
      y: 1,
      direction: 0
    }
  });
  assert.equal(placed.ok, true);
  assert.equal(placed.document.placements.length, 1);

  const rejected = applyLayoutCommand(emptyLayout, catalog, {
    type: "place",
    placement: {
      instanceId: "rack-2",
      furnitureId: "rack",
      x: 3,
      y: 3,
      direction: 0
    }
  });
  assert.deepEqual(rejected, {
    ok: false,
    error: { code: "outside-store", message: "家具超出当前店铺范围" }
  });
});


test("map rules reject a non-editable or fixed tile", () => {
  const nonEditable = applyLayoutCommand(emptyLayout, catalog, {
    type: "place",
    placement: { instanceId: "rack-3", furnitureId: "rack", x: 1, y: 3, direction: 1 }
  });
  assert.equal(nonEditable.ok, false);
  assert.equal(nonEditable.error.code, "non-editable-tile");

  const fixed = applyLayoutCommand(emptyLayout, catalog, {
    type: "place",
    placement: { instanceId: "rack-4", furnitureId: "rack", x: 2, y: 3, direction: 1 }
  });
  assert.equal(fixed.ok, false);
  assert.equal(fixed.error.code, "fixed-object-collision");
});


test("duplicate creates a new legal instance without mutating the source", () => {
  const document = {
    ...emptyLayout,
    placements: [
      { instanceId: "rack-1", furnitureId: "rack", x: 0, y: 0, direction: 0 }
    ]
  };
  const result = applyLayoutCommand(document, catalog, {
    type: "duplicate",
    instanceId: "rack-1",
    newInstanceId: "rack-copy",
    x: 2,
    y: 0
  });
  assert.equal(result.ok, true);
  assert.equal(result.document.placements.length, 2);
  assert.equal(document.placements.length, 1);
});


test("layout import validates the whole document and supports catalog migration", () => {
  const imported = {
    ...emptyLayout,
    sourceReleaseId: "older-release",
    catalogHash: "older-catalog",
    placements: [
      { instanceId: "rack-1", furnitureId: "rack", x: 0, y: 0, direction: 0 }
    ]
  };
  const migrated = validateLayoutDocument(imported, catalog, {
    sourceReleaseId: "current-release",
    catalogHash: "current-catalog"
  });
  assert.equal(migrated.ok, true);
  assert.equal(migrated.document.sourceReleaseId, "current-release");
  assert.equal(migrated.document.catalogHash, "current-catalog");

  const missing = validateLayoutDocument({
    ...imported,
    placements: [...imported.placements, {
      instanceId: "missing-1",
      furnitureId: "missing",
      x: 2,
      y: 0,
      direction: 0
    }]
  }, catalog, { sourceReleaseId: "current-release", catalogHash: "current-catalog" });
  assert.equal(missing.ok, false);
  assert.equal(missing.error.code, "missing-furniture");
  assert.deepEqual(missing.error.details, ["missing"]);

  const missingInstanceId = validateLayoutDocument({
    ...imported,
    placements: [{ furnitureId: "rack", x: 0, y: 0, direction: 0 }]
  }, catalog, { sourceReleaseId: "current-release", catalogHash: "current-catalog" });
  assert.equal(missingInstanceId.ok, false);
  assert.equal(missingInstanceId.error.code, "invalid-document");
});


test("place rejects overlap with an existing rotated footprint", () => {
  const document = {
    ...emptyLayout,
    placements: [
      {
        instanceId: "rack-1",
        furnitureId: "rack",
        x: 1,
        y: 1,
        direction: 1
      }
    ]
  };
  const result = applyLayoutCommand(document, catalog, {
    type: "place",
    placement: {
      instanceId: "rack-2",
      furnitureId: "rack",
      x: 2,
      y: 1,
      direction: 0
    }
  });
  assert.deepEqual(result, {
    ok: false,
    error: { code: "collision", message: "家具与现有布局重叠" }
  });
});


test("edit commands preserve the last legal layout", () => {
  const document = {
    ...emptyLayout,
    placements: [
      { instanceId: "rack-1", furnitureId: "rack", x: 0, y: 0, direction: 0 },
      { instanceId: "rack-2", furnitureId: "rack", x: 2, y: 0, direction: 0 }
    ]
  };
  const collided = applyLayoutCommand(document, catalog, {
    type: "move",
    instanceId: "rack-2",
    x: 0,
    y: 1
  });
  assert.equal(collided.ok, false);
  assert.equal(collided.error.code, "collision");
  assert.deepEqual(document.placements[1], {
    instanceId: "rack-2",
    furnitureId: "rack",
    x: 2,
    y: 0,
    direction: 0
  });

  const removed = applyLayoutCommand(document, catalog, {
    type: "remove",
    instanceId: "rack-2"
  });
  assert.equal(removed.ok, true);
  const rotated = applyLayoutCommand(removed.document, catalog, {
    type: "rotate",
    instanceId: "rack-1",
    direction: 1
  });
  assert.equal(rotated.ok, true);
  assert.equal(rotated.document.placements[0].direction, 1);

  const resized = applyLayoutCommand(rotated.document, catalog, {
    type: "resize",
    storeSize: { level: 0, width: 1, height: 1 }
  });
  assert.deepEqual(resized, {
    ok: false,
    error: { code: "resize-conflict", message: "缩小范围会压到现有家具" }
  });
});
