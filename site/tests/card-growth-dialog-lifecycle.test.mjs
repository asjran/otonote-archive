import assert from "node:assert/strict";
import test from "node:test";

import {
  nextGrowthDialogState
} from "../src/lib/growth-dialog-lifecycle.mjs";

test("keeps growth state when the dialog closes and resets only explicitly", () => {
  const initial = {
    level: 1,
    rank: 0,
    awake: 0,
    skillLevels: { "skill-1": 1 }
  };
  const edited = {
    level: 42,
    rank: 3,
    awake: 2,
    skillLevels: { "skill-1": 4 }
  };

  assert.deepEqual(nextGrowthDialogState("dialog-close", edited, initial), edited);
  assert.deepEqual(nextGrowthDialogState("explicit-reset", edited, initial), initial);
});
