import assert from "node:assert/strict";
import test from "node:test";

import { calculateFormalNoteCore } from "../src/lib/scoring-rules/formal-note-core.mjs";

const input = {
  totalPower: 123456,
  scoreAdjustmentFactor: 1,
  musicScoreLevelFactor: 1,
  noteFactorPercent: 100,
  judgementFactorPercent: 100,
  comboBonusFactor: 1,
  scoreUpFactor: 1,
  luckScoreFactorPercent: 100,
  convertedNoteCount: 100,
  eventBonusFactor: 1,
  lifeOnusFactor: 0.5,
  assistModeNoteScoreFactor: 1,
  currentLife: 1
};

test("formal core floors the note amount before event and life factors", () => {
  const alive = calculateFormalNoteCore({ ...input, eventBonusFactor: 1.1 });
  const depleted = calculateFormalNoteCore({ ...input, eventBonusFactor: 1.1, currentLife: 0 });
  assert.equal(alive.firstFloor, 1234);
  assert.equal(alive.score, 1357);
  assert.equal(depleted.score, 678);
});

test("formal core rejects invalid native arithmetic inputs", () => {
  assert.throws(() => calculateFormalNoteCore({ ...input, convertedNoteCount: 0 }), RangeError);
  assert.throws(() => calculateFormalNoteCore({ ...input, totalPower: NaN }), TypeError);
});
