import assert from "node:assert/strict";
import test from "node:test";

import {
  assignCharacter,
  createDefaultAssignmentState,
  normalizeAssignmentState
} from "../src/lib/anontokyo-staff-assignment.mjs";


const dataset = {
  records: [
    { id: "anon", name: "爱音", levelLimit: 0 },
    { id: "tomori", name: "灯", levelLimit: 3 },
    { id: "uika", name: "初华", levelLimit: 10 },
    { id: "taki", name: "立希", levelLimit: 0 },
  ],
  assignmentStudio: {
    roles: [
      { id: "cashier", name: "收银员" },
      { id: "sales", name: "导购员" },
      { id: "restock", name: "补货员" },
    ],
    freePreviewCapacities: { cashier: 2, sales: 2, restock: 1 },
    capacityByLevel: Array.from({ length: 20 }, (_, index) => {
      const level = index + 1;
      return {
        level,
        capacities:
          level >= 6
            ? { cashier: 2, sales: 2, restock: 1 }
            : level >= 5
              ? { cashier: 2, sales: 1, restock: 1 }
              : { cashier: 1, sales: 1, restock: 1 }
      };
    })
  }
};


test("defaults every character to exactly one standby state", () => {
  const state = createDefaultAssignmentState(dataset);
  assert.equal(state.mode, "free");
  assert.equal(state.level, 20);
  assert.deepEqual(state.assignments, {
    anon: "standby",
    tomori: "standby",
    uika: "standby",
    taki: "standby"
  });
});


test("moves a character instead of duplicating it between roles", () => {
  let state = createDefaultAssignmentState(dataset);
  state = assignCharacter(dataset, state, "anon", "cashier").state;
  state = assignCharacter(dataset, state, "anon", "sales").state;

  assert.equal(state.assignments.anon, "sales");
  assert.equal(
    Object.values(state.assignments).filter((role) => role === "cashier").length,
    0
  );
});


test("rejects locked characters and full roles without changing state", () => {
  const levelState = normalizeAssignmentState(dataset, {
    mode: "level",
    level: 1,
    assignments: { anon: "cashier", tomori: "standby", uika: "standby", taki: "standby" }
  }).state;

  const locked = assignCharacter(dataset, levelState, "tomori", "sales");
  assert.equal(locked.error.code, "character_locked");
  assert.deepEqual(locked.state, levelState);

  const full = assignCharacter(dataset, levelState, "taki", "cashier");
  assert.equal(full.error.code, "role_full");
  assert.deepEqual(full.state, levelState);
});


test("lowering level recalls locked and overflow characters deterministically", () => {
  const normalized = normalizeAssignmentState(dataset, {
    schemaVersion: 1,
    mode: "level",
    level: 1,
    assignments: {
      anon: "cashier",
      tomori: "sales",
      uika: "restock",
      taki: "cashier",
      ghost: "sales"
    }
  });

  assert.deepEqual(normalized.state.assignments, {
    anon: "cashier",
    tomori: "standby",
    uika: "standby",
    taki: "standby"
  });
  assert.deepEqual(
    normalized.corrections.map((item) => item.code),
    ["character_locked", "character_locked", "role_overflow", "unknown_character"]
  );
});


test("repairs malformed storage and clamps invalid levels", () => {
  const normalized = normalizeAssignmentState(dataset, {
    schemaVersion: 99,
    mode: "broken",
    level: 400,
    assignments: { anon: "not-a-role" }
  });

  assert.equal(normalized.state.schemaVersion, 1);
  assert.equal(normalized.state.mode, "free");
  assert.equal(normalized.state.level, 20);
  assert.equal(normalized.state.assignments.anon, "standby");
  assert.ok(normalized.corrections.length > 0);
});
