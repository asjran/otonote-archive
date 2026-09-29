import assert from "node:assert/strict";
import test from "node:test";
import { progressiveRecords, progressiveStateFromParams, progressiveParams, progressLabel } from "../src/lib/pagination.mjs";

const records = length => Array.from({ length }, (_, index) => index + 1);

test("small directories show every record, regardless of the previous page size", () => {
  for (const total of [0, 60, 62, 84, 96]) {
    const result = progressiveRecords(records(total), { shown: 12, batchSize: 12 });
    assert.deepEqual(result.records, records(total));
    assert.equal(result.remaining, 0);
  }
});

test("large directories append records without dropping or repeating the prefix", () => {
  const all = records(139);
  const first = progressiveRecords(all);
  const second = progressiveRecords(all, { shown: first.shown + first.nextCount });
  assert.equal(first.shown, 24);
  assert.equal(second.shown, 48);
  assert.deepEqual(second.records.slice(0, first.shown), first.records);
  assert.deepEqual(second.records.slice(first.shown), all.slice(24, 48));
  const last = progressiveRecords(all, { shown: 144 });
  assert.deepEqual(last.records, all);
  assert.equal(last.remaining, 0);
  assert.equal(last.nextCount, 0);
});

test("filter reset starts from the first records and small matches show completely", () => {
  const filtered = records(139).filter(n => n % 2 === 0);
  assert.deepEqual(progressiveRecords(filtered, { shown: 24 }).records, filtered);
  assert.deepEqual(progressiveRecords(records(150), { shown: 24 }).records, records(24));
});

test("old page links reveal a prefix through the linked page", () => {
  const shown = progressiveStateFromParams(new URLSearchParams("page=3&pageSize=48"));
  assert.equal(shown, 144);
  assert.deepEqual(progressiveRecords(records(200), { shown }).records, records(144));
  const params = progressiveParams(new URLSearchParams("q=test&page=3&pageSize=48"), { total: 200, shown });
  assert.equal(params.toString(), "q=test&shown=144");
  assert.equal(progressiveStateFromParams(params), shown);
});

test("expanded URLs restore on back navigation; small and reset lists omit display state", () => {
  assert.equal(progressiveStateFromParams(new URLSearchParams("shown=72")), 72);
  assert.equal(progressiveStateFromParams(new URLSearchParams()), 24);
  const params = new URLSearchParams("q=test&sort=desc&page=3&pageSize=12&shown=72");
  assert.equal(progressiveParams(params, { total: 60, shown: 60 }).toString(), "q=test&sort=desc");
  assert.equal(progressiveParams(params, { total: 139, shown: 24 }).toString(), "q=test&sort=desc");
});

test("malformed and excessive URL counts are bounded by the actual results", () => {
  for (const value of ["-3", "0", "NaN", "Infinity", "2.5", "9999999999999999999999"]) {
    assert.equal(progressiveStateFromParams(new URLSearchParams(`shown=${value}`)), 24);
  }
  assert.equal(progressiveRecords(records(139), { shown: 999999 }).shown, 139);
  assert.equal(progressiveRecords(records(139), { shown: -1 }).shown, 24);
});

test("progress labels distinguish partial lists from completion in supported locales", () => {
  const partial = progressiveRecords(records(139));
  const complete = progressiveRecords(records(60));
  assert.equal(progressLabel(partial), "已显示 24 / 139 项");
  assert.equal(progressLabel(complete), "已展示全部 60 项");
  assert.equal(progressLabel(complete, "en"), "All 60 items shown");
  assert.equal(progressLabel(complete, "zh-TW"), "已展示全部 60 項");
  assert.equal(progressLabel(complete, "ja"), "全 60 件を表示しました");
});
