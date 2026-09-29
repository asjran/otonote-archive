import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { studioUnlocks, selectStudioLevel } from "../src/lib/studio-practice.mjs";

const art = JSON.parse(readFileSync(new URL("../public/growth/manifest.json", import.meta.url)));
const levels = [
  { level: 1, unlockBandRank: 0 }, { level: 4, unlockBandRank: 0 },
  { level: 5, unlockBandRank: 4 }, { level: 14, unlockBandRank: 4 },
  { level: 15, unlockBandRank: 5 }, { level: 24, unlockBandRank: 5 },
  { level: 85, unlockBandRank: 12 }, { level: 90, unlockBandRank: 12 },
];
const units = [{ id: 1, levels }, { id: 2, levels: levels.slice(0, 4) }];

test("serialized game labels map D4, C1 and B4 to the real unlock thresholds", () => {
  for (const [label, rank, cap] of [["D3", 3, 4], ["D4", 4, 14], ["C1", 5, 24], ["B4", 12, 90]]) {
    assert.equal(art.bandRanks.find(row => row.label === label).rank, rank);
    assert.equal(studioUnlocks(units[0], rank).cap, cap);
  }
});

test("lowering band rank clamps the practice level to the available cap", () => {
  assert.equal(selectStudioLevel(units, 1, 90, 4).level.level, 14);
  assert.equal(selectStudioLevel(units, 1, 14, 3).level.level, 4);
  assert.equal(selectStudioLevel(units, 1, 5, 4).level.level, 5);
  assert.equal(selectStudioLevel(units, 2, 90, 12).level.level, 14);
});

test("unlock overview is derived per band and reports the next gate", () => {
  assert.deepEqual(studioUnlocks(units[0], 4).next, { bandRank: 5, minLevel: 15, maxLevel: 24 });
  assert.equal(studioUnlocks(units[1], 4).next, null);
  assert.equal(studioUnlocks(units[0], 24).next, null);
  assert.equal(selectStudioLevel([], 1, 1, 1), null);
  assert.equal(studioUnlocks(null, 1).cap, 0);
});
