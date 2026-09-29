import assert from "node:assert/strict";
import test from "node:test";

import {
  filterUnifiedSearch,
  normalizeSearchQuery
} from "../src/lib/unified-search.mjs";

const entries = [
  {
    id: "music-1",
    type: "music",
    title: "迷星叫",
    subtitle: "MyGO!!!!! · 高松燈",
    href: "/music/music-1/",
    searchableText: "迷星叫 まよいうた MyGO!!!!! 高松燈"
  },
  {
    id: "character-1",
    type: "character",
    title: "高松燈",
    subtitle: "MyGO!!!!!",
    href: "/characters/character-1/",
    searchableText: "高松燈 燈 Tomori MyGO!!!!!"
  },
  {
    id: "story-1",
    type: "story",
    title: "第一话",
    subtitle: "主线剧情",
    href: "/stories/episodes/story-1/",
    searchableText: "第一话 故事摘要"
  }
];

test("normalizes full-width and case differences for one shared query", () => {
  assert.equal(normalizeSearchQuery("  ＭｙＧＯ!!!!!  "), "mygo!!!!!");
  assert.equal(normalizeSearchQuery("高松 燈"), "高松燈");
});

test("ranks title matches before metadata matches", () => {
  const results = filterUnifiedSearch(entries, { query: "高松燈" });
  assert.deepEqual(results.map((entry) => entry.id), ["character-1", "music-1"]);
});

test("filters by entity type without returning unrelated records", () => {
  const results = filterUnifiedSearch(entries, {
    query: "第一",
    type: "story"
  });
  assert.deepEqual(results.map((entry) => entry.id), ["story-1"]);
});

test("empty queries do not dump the entire archive", () => {
  assert.deepEqual(filterUnifiedSearch(entries, { query: "" }), []);
});

const { searchUnified, highlightParts } = await import('../src/lib/unified-search.mjs');

test('space-separated keywords match across fields regardless of order', () => {
  assert.deepEqual(filterUnifiedSearch(entries, { query: 'MyGO 燈' }).map(e => e.id), ['character-1', 'music-1']);
  assert.deepEqual(filterUnifiedSearch(entries, { query: 'MyGO 不存在' }), []);
  assert.equal(filterUnifiedSearch(entries, { query: 'Ｔｏｍｏｒｉ' })[0].id, 'character-1');
});

test('category totals count all matches before the visible result limit', () => {
  const all = Array.from({ length: 40 }, (_, i) => ({ id: `card-${i}`, title: `MyGO ${i}`, type: 'member_card' }));
  all.push({ id: 'song', title: 'MyGO', type: 'music' });
  const result = searchUnified(all, { query: 'mygo', type: 'member_card' });
  assert.equal(result.matches.length, 24);
  assert.equal(result.total, 40);
  assert.equal(result.totalAll, 41);
  assert.equal(result.counts.music, 1);
  assert.equal(result.counts.member_card, 40);
  assert.deepEqual(searchUnified(all, { query: 'mygo', type: 'member_card', limit: 48 }).matches.slice(0, 24), result.matches);
});

test('highlighting retains original text, including full-width, spaces and markup-like titles', () => {
  const title = '<b>ＭｙＧＯ!!!!!</b> 高松 燈';
  const parts = highlightParts(title, 'mygo 高松燈');
  assert.equal(parts.map(part => part.text).join(''), title);
  assert.deepEqual(parts.filter(part => part.match).map(part => part.text), ['ＭｙＧＯ', '高松 燈']);
  assert.deepEqual(highlightParts('日常', ''), [{ text: '日常', match: false }]);
});
