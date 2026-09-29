import test from "node:test";
import assert from "node:assert/strict";
import { filterEntries } from "../src/lib/system-browser.mjs";
import { selectStudioLevel } from "../src/lib/studio-practice.mjs";

test("recruitment filters combine theme, card type, rarity and text", () => {
  const rows = [
    { search: "MyGO Tomori", categories: "limited event", kind: "2", rarity: "SSR" },
    { search: "MyGO snapshot", categories: "permanent", kind: "3", rarity: "SSR" },
  ];
  assert.deepEqual(filterEntries(rows, "TOMORI", "event", "2", "SSR"), [rows[0]]);
  assert.deepEqual(filterEntries(rows, "", "birthday"), []);
  assert.deepEqual(filterEntries(rows, "MyGO", "", "3", "R"), []);
  assert.deepEqual(filterEntries(rows, "  "), rows);
});

test("switching bands keeps a valid level and falls back for a missing one", () => {
  const units = [{ id: 1, levels: [{ level: 1 }, { level: 2 }] }, { id: 2, levels: [{ level: 1 }] }];
  assert.equal(selectStudioLevel(units, "1", "2").level.level, 2);
  assert.equal(selectStudioLevel(units, "2", "2").level.level, 1);
  assert.equal(selectStudioLevel([], 1, 1), null);
});
