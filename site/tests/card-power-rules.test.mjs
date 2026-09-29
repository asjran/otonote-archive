import assert from "node:assert/strict";
import test from "node:test";

import {
  CARD_POWER_SCALE,
  addCardPower,
  cardPowerPoints,
  createCardPowerBP,
  createCardPowerInt,
  floorCardPower,
  multiplyCardPower
} from "../src/lib/scoring-rules/card-power.mjs";
import {
  calculateTgwCardSlotBonus,
  resolveTgwCardRankBonus
} from "../src/lib/scoring-rules/tgw-card.mjs";

test("native CardPower basis-point multiply keeps intermediate precision", () => {
  assert.equal(CARD_POWER_SCALE, 10000n);
  const base = createCardPowerInt(101, 203, 307);
  const rate = createCardPowerBP(10250, 10000, 9750);
  const product = multiplyCardPower(base, rate);
  assert.deepEqual(product, createCardPowerBP(1035250, 2030000, 2993250));
  assert.deepEqual(cardPowerPoints(product), {
    performance: 103, technic: 203, visual: 299, total: 605
  });
  assert.deepEqual(
    floorCardPower(addCardPower(product, createCardPowerBP(7500, 0, 0))),
    createCardPowerInt(104, 203, 299)
  );
});

test("native multiply truncates toward zero while ToFloor rounds down", () => {
  const product = multiplyCardPower(
    createCardPowerBP(-10001, 10001, 0),
    createCardPowerBP(5000, 5000, 0)
  );
  assert.deepEqual(product, createCardPowerBP(-5000, 5000, 0));
  assert.deepEqual(floorCardPower(product), createCardPowerInt(-1, 0, 0));
});

test("ToFloor preserves the native float32 boundary behavior", () => {
  assert.deepEqual(
    floorCardPower(createCardPowerBP(99999999, 0, 0)),
    createCardPowerInt(10000, 0, 0)
  );
});

test("T.G.W rank lookup exposes only configured raw all-parameter value", () => {
  const ranks = [
    { rank: 1, bonuses: [] },
    { rank: 2, bonuses: [{ type: 7, rawValue: 100 }] },
    { rank: 3, bonuses: [{ type: 7, rawValue: 200 }] }
  ];
  assert.deepEqual(resolveTgwCardRankBonus(ranks, 1), {
    rank: 1, type: 7, rawValue: 0,
    calculationStatus: "base_power_unverified"
  });
  assert.equal(resolveTgwCardRankBonus(ranks, 3).rawValue, 200);
  assert.throws(() => resolveTgwCardRankBonus(ranks, 4), /not configured/);
});

test("T.G.W slot bonus applies the formal client BP rate and per-slot floor", () => {
  const base = createCardPowerBP(1999900, 2000100, 501000);
  assert.deepEqual(
    calculateTgwCardSlotBonus(base, 2000),
    createCardPowerInt(39, 40, 10)
  );
  assert.deepEqual(calculateTgwCardSlotBonus(base, 0), createCardPowerInt(0, 0, 0));
  assert.throws(() => calculateTgwCardSlotBonus(base, -1), /nonnegative/);
});
