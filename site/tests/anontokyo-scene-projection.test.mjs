import assert from "node:assert/strict";
import test from "node:test";

import {
  depthForFootprint,
  globalTileToLocal,
  tileToWorld,
  worldToTile,
} from "../src/lib/anontokyo-scene-projection.mjs";


test("game axes project x right-down and y left-down", () => {
  assert.deepEqual(tileToWorld(1, 0), { x: 80, y: 40 });
  assert.deepEqual(tileToWorld(0, 1), { x: -80, y: 40 });
  assert.deepEqual(tileToWorld(-5, -5), { x: 0, y: -400 });
  assert.deepEqual(tileToWorld(-2, 11), { x: -1040, y: 360 });
});


test("tile projection round trips screen coordinates", () => {
  for (const tile of [{ x: 0, y: 0 }, { x: 4, y: 2 }, { x: -2, y: 11 }]) {
    assert.deepEqual(worldToTile(tileToWorld(tile.x, tile.y)), tile);
  }
});


test("global tile conversion uses the store anchor row in reverse", () => {
  assert.deepEqual(globalTileToLocal(3842, 81, 4000), { x: 4, y: 2 });
  assert.deepEqual(globalTileToLocal(3107, 81, 4000), { x: -2, y: 11 });
  assert.deepEqual(globalTileToLocal(4400, 81, 4000), { x: -5, y: -5 });
});


test("depth uses the closest edge of an occupied footprint", () => {
  assert.equal(depthForFootprint({ x: 4, y: 2 }, { width: 3, height: 4 }), 13);
  assert.equal(depthForFootprint({ x: -2, y: 11 }, { width: 3, height: 3 }), 15);
});
