import assert from "node:assert/strict";
import test from "node:test";

import {
  filterMusicRecords,
  musicParams,
  sortMusicRecords
} from "../src/lib/music-filtering.mjs";

const records = [
  {
    id: "slow",
    search: "迷星叫 MyGO!!!!! 高松燈",
    bands: ["band-1"],
    categories: ["1"],
    level: 27,
    bpm: 190,
    order: 1,
    title: "まよいうた",
    start: "2025/01/01",
    notes: 818
  },
  {
    id: "fast",
    search: "KiLLKiSS Ave Mujica 三角初華",
    bands: ["band-2"],
    categories: ["1"],
    level: 28,
    bpm: 200,
    order: 2,
    title: "きるきす",
    start: "2025/02/01",
    notes: 1000
  }
];

test("music filters combine normalized search, band and level range", () => {
  const result = filterMusicRecords(records, {
    query: "ＭＹＧＯ 燈",
    band: "band-1",
    category: "all",
    level: "26",
    bpm: "fast"
  });

  assert.deepEqual(result.map((record) => record.id), ["slow"]);
});

test("music sorting uses the selected numeric field", () => {
  assert.deepEqual(
    sortMusicRecords(records, "notes").map((record) => record.id),
    ["fast", "slow"]
  );
  assert.deepEqual(
    sortMusicRecords(records, "order").map((record) => record.id),
    ["slow", "fast"]
  );
});

test("music URL params omit default values", () => {
  assert.equal(
    musicParams({
      query: "迷星叫",
      band: "all",
      category: "1",
      level: "all",
      bpm: "all",
      sort: "order"
    }).toString(),
    "q=%E8%BF%B7%E6%98%9F%E5%8F%AB&category=1"
  );
});
