import assert from "node:assert/strict";
import test from "node:test";

import {
  assetShape,
  selectFeaturedAssets
} from "../src/lib/presentation.mjs";

test("classifies asset shapes from source dimensions", () => {
  assert.equal(assetShape({ width: 1920, height: 1080 }), "landscape");
  assert.equal(assetShape({ width: 900, height: 1200 }), "portrait");
  assert.equal(assetShape({ width: 2048, height: 1536 }), "square");
});

test("selects unique assets that match each editorial slot", () => {
  const assets = [
    { id: "wide-1", kind: "card", width: 1920, height: 1080 },
    { id: "wide-2", kind: "card", width: 1920, height: 1080 },
    { id: "portrait-1", kind: "card", width: 900, height: 1200 },
    { id: "portrait-2", kind: "card", width: 900, height: 1200 },
    { id: "portrait-3", kind: "card", width: 900, height: 1200 },
    { id: "square-1", kind: "background", width: 2048, height: 2048 },
    { id: "square-2", kind: "background", width: 2048, height: 1536 },
    { id: "banner-low", kind: "banner", width: 490, height: 160 },
    { id: "banner-1", kind: "banner", width: 750, height: 290 }
  ];

  const featured = selectFeaturedAssets(assets);

  assert.deepEqual(
    featured.map(({ asset, slot }) => [asset.id, slot]),
    [
      ["wide-1", "primary"],
      ["portrait-1", "portrait"],
      ["portrait-2", "portrait"],
      ["portrait-3", "portrait"],
      ["square-2", "square"],
      ["square-1", "square"],
      ["banner-1", "banner"]
    ]
  );
  assert.equal(new Set(featured.map(({ asset }) => asset.id)).size, 7);
});
