import assert from "node:assert/strict";
import test from "node:test";

import { classifyTileTitleDensity } from "../src/lib/tile-title-density.mjs";

test("regular tile titles include the twelve-code-point boundary", () => {
  assert.equal(classifyTileTitleDensity("123456789012"), "regular");
});

test("tile titles become long at thirteen code points", () => {
  assert.equal(classifyTileTitleDensity("1234567890123"), "long");
});

test("tile titles become extra-long at twenty-one code points", () => {
  assert.equal(classifyTileTitleDensity("123456789012345678901"), "extra-long");
});

test("supplementary Unicode characters count as one title character", () => {
  assert.equal(classifyTileTitleDensity("12345678901😀"), "regular");
});
