import assert from "node:assert/strict";
import test from "node:test";

import {
  bandItemDialogHref,
  parseBandItemDialogState
} from "../src/lib/band-item-dialog-state.mjs";

const items = new Map([
  ["band-item-101", [1, 2, 10]],
  ["band-item-201", [1, 10]]
]);

test("accepts only known BandItems and levels", () => {
  assert.deepEqual(
    parseBandItemDialogState("?item=band-item-101&level=2", items),
    { itemId: "band-item-101", level: 2 }
  );
  assert.deepEqual(
    parseBandItemDialogState("?item=band-item-101&level=99", items),
    { itemId: "band-item-101", level: 10 }
  );
  assert.deepEqual(
    parseBandItemDialogState("?item=unknown&level=1", items),
    { itemId: null, level: null }
  );
});

test("serializes open, level change and close without stale parameters", () => {
  assert.equal(
    bandItemDialogHref("/database/band-items/?q=old", "band-item-101", 1),
    "/database/band-items/?item=band-item-101&level=1"
  );
  assert.equal(
    bandItemDialogHref(
      "/database/band-items/?item=band-item-101&level=1",
      "band-item-101",
      10
    ),
    "/database/band-items/?item=band-item-101&level=10"
  );
  assert.equal(
    bandItemDialogHref(
      "/database/band-items/?item=band-item-101&level=10",
      null
    ),
    "/database/band-items/"
  );
});
