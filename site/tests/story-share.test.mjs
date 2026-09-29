import test from "node:test";
import assert from "node:assert/strict";
import { selectedRange, wrapStoryText, shareImageHeight } from "../src/lib/story-share-layout.mjs";

test("selection includes both endpoints in source order, including backwards selection", () => {
  assert.equal(selectedRange(null), null);
  assert.equal(selectedRange(-1), null);
  assert.deepEqual(selectedRange(7), { start: 7, end: 7, count: 1 });
  assert.deepEqual(selectedRange(7, 3), { start: 3, end: 7, count: 5 });
  assert.deepEqual(selectedRange(3, 7), selectedRange(7, 3));
});

test("wrapping preserves multilingual text, whitespace, blank lines and whole emoji", () => {
  const measure = value => [...new Intl.Segmenter(undefined, { granularity: "grapheme" }).segment(value)].length;
  assert.deepEqual(wrapStoryText("你好世界\n\nHello  band!", 4, measure), ["你好世界", "", "Hell", "o  b", "and!"]);
  assert.deepEqual(wrapStoryText("a👩‍👩‍👧‍👦b", 1, measure), ["a", "👩‍👩‍👧‍👦", "b"]);
  assert.deepEqual(wrapStoryText("一\r\n二\r三", 5, measure), ["一", "二", "三"]);
  assert.deepEqual(wrapStoryText("", 4, measure), [""]);
});

test("image size guards reject oversized exports rather than cropping any dialogue", () => {
  assert.equal(shareImageHeight(200, [80, 120, 70], 100), 570);
  assert.equal(shareImageHeight(100, Array(80).fill(95), 100), 7800);
  assert.throws(() => shareImageHeight(100, Array(81).fill(20), 100), RangeError);
  assert.throws(() => shareImageHeight(100, [7900], 100), RangeError);
  assert.throws(() => shareImageHeight(100, [], 100), RangeError);
});
