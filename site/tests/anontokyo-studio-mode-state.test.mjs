import assert from "node:assert/strict";
import test from "node:test";

import {
  createModeDefaults,
  modeStorageKey,
  restoreModeDocuments,
} from "../src/lib/anontokyo-studio-mode-state.mjs";


const payload = {
  sourceReleaseId: "global-test",
  studio: {
    catalogHash: "catalog-test",
    storeSizes: [
      { level: 1, width: 8, height: 8 },
      { level: 9, width: 12, height: 12 },
    ],
    modes: {
      gameFaithful: {
        defaultLayout: [
          { instanceId: "stage", furnitureId: "stage", x: 4, y: 2, direction: 0 },
        ],
      },
      free: { defaultLayout: [] },
    },
    deliveryOptions: [{ id: "balloon", name: "气球配送员" }],
  },
};


test("mode defaults use initial 8x8 and free 12x12 layouts", () => {
  const defaults = createModeDefaults(payload);
  assert.deepEqual(defaults.gameFaithful.document.storeSize, { level: 1, width: 8, height: 8 });
  assert.equal(defaults.gameFaithful.document.placements[0].instanceId, "stage");
  assert.deepEqual(defaults.free.document.storeSize, { level: 9, width: 12, height: 12 });
  assert.deepEqual(defaults.free.document.placements, []);
  assert.equal(defaults.gameFaithful.delivery.optionId, "balloon");
});


test("legacy v1 layout migrates only to free mode", () => {
  const legacy = {
    schemaVersion: 1,
    sourceReleaseId: "older",
    catalogHash: "older",
    storeSize: { level: 9, width: 12, height: 12 },
    placements: [{ instanceId: "legacy", furnitureId: "rack", x: 1, y: 1, direction: 0 }],
  };
  const restored = restoreModeDocuments(payload, { legacy });
  assert.equal(restored.free.document.placements[0].instanceId, "legacy");
  assert.equal(restored.gameFaithful.document.placements[0].instanceId, "stage");
  assert.equal(restored.migratedLegacy, true);
});


test("one damaged mode falls back without changing the other", () => {
  const validFree = {
    schemaVersion: 2,
    mode: "free",
    document: {
      schemaVersion: 1,
      storeSize: { level: 9, width: 12, height: 12 },
      placements: [{ instanceId: "free", furnitureId: "rack", x: 1, y: 1, direction: 0 }],
    },
    delivery: { visible: false, optionId: "balloon", x: 3, y: 3 },
    warehouse: { visible: true, x: 4, y: 4 },
    viewport: null,
  };
  const restored = restoreModeDocuments(payload, {
    gameFaithful: { broken: true },
    free: validFree,
  });
  assert.equal(restored.free.document.placements[0].instanceId, "free");
  assert.equal(restored.gameFaithful.document.placements[0].instanceId, "stage");
  assert.deepEqual(restored.warnings, ["gameFaithful"]);
});


test("snapshot missing scene state falls back without crashing the editor", () => {
  const restored = restoreModeDocuments(payload, {
    free: {
      schemaVersion: 2,
      mode: "free",
      document: {
        schemaVersion: 1,
        storeSize: { level: 9, width: 12, height: 12 },
        placements: [],
      },
      delivery: { visible: true, optionId: "balloon", x: 0, y: 0 },
    },
  });
  assert.equal(restored.free.warehouse.visible, false);
  assert.deepEqual(restored.warnings, ["free"]);
});


test("mode storage keys remain independent", () => {
  assert.equal(modeStorageKey("ournotes:studio", "gameFaithful"), "ournotes:studio:game-faithful:v2");
  assert.equal(modeStorageKey("ournotes:studio", "free"), "ournotes:studio:free:v2");
});
