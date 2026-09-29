import assert from "node:assert/strict";
import test from "node:test";

import {
  filterRecords,
  matchesSearch,
  normalizeText,
  paramsFromFilters,
  sortRecords
} from "../src/lib/filtering.mjs";

test("normalizes full-width and mixed-case search terms", () => {
  assert.equal(normalizeText(" Ａrchive "), "archive");
  assert.equal(matchesSearch("角色 Archive 01", "ARCHIVE"), true);
});

test("filters search and facets together", () => {
  const records = [
    { search: "角色档案 ch-001", status: "pending", label: "CH-001" },
    { search: "角色档案 ch-002", status: "identified", label: "CH-002" }
  ];
  assert.deepEqual(
    filterRecords(records, {
      query: "002",
      facets: { status: "identified" }
    }),
    [records[1]]
  );
});

test("filters facets that contain multiple relationships", () => {
  const records = [
    {
      search: "MyGO!!!!!",
      character: "character-1,character-2",
      label: "SC-51"
    }
  ];
  assert.deepEqual(
    filterRecords(records, {
      query: "",
      facets: { character: "character-2" }
    }),
    records
  );
});

test("sorts archive labels numerically", () => {
  const records = [
    { label: "CD-10" },
    { label: "CD-2" },
    { label: "CD-1" }
  ];
  assert.deepEqual(
    sortRecords(records).map((record) => record.label),
    ["CD-1", "CD-2", "CD-10"]
  );
});

test("serializes only active filters", () => {
  const params = paramsFromFilters({
    query: "角色",
    facets: { status: "all", kind: "card" },
    sort: "desc"
  });
  assert.equal(params.toString(), "q=%E8%A7%92%E8%89%B2&kind=card&sort=desc");
});
