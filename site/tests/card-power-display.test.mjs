import assert from "node:assert/strict";
import test from "node:test";
import { formatCardPower } from "../src/lib/card-power-display.mjs";
import { createGrowthSnapshot } from "../src/lib/growth-simulator.mjs";

test("support growth values display as percentages at initial and maximum levels", () => {
  const card = { performancePowerMax: 600, technicPowerMax: 500, visualPowerMax: 400 };
  const profile = {
    cardKind: "support", ranks: [{ limitLevel: 60 }], awakes: [], materialRequirements: [],
    levelCurve: [
      { level: 1, rawExp: 0, rates: { performance: 3333, technic: 3333, visual: 3333 } },
      { level: 60, rawExp: 1000, rates: { performance: 10000, technic: 10000, visual: 10000 } }
    ]
  };
  const snapshot = level => createGrowthSnapshot({ card, profile, projection: { skillRefs: [] }, state: { level, rank: 0 } });
  assert.equal(formatCardPower(snapshot(1).power.performance, "support"), "1.99%");
  assert.deepEqual(["performance", "technic", "visual"].map(axis => formatCardPower(snapshot(60).power[axis], "support")), ["6%", "5%", "4%"]);
  assert.equal(snapshot(60).power.performance, 600);
});

test("member power remains absolute and zero / fractional rates remain valid", () => {
  assert.equal(formatCardPower(12345, "member", "en"), "12,345");
  assert.equal(formatCardPower(0, "support"), "0%");
  assert.equal(formatCardPower(1250, "support"), "12.5%");
  assert.equal(formatCardPower(1, "support"), "0.01%");
});
