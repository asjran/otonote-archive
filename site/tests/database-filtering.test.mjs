import assert from "node:assert/strict";
import test from "node:test";

import {
  filterItems,
  filterSkills,
  itemParams,
  skillParams,
  sortItems,
  sortSkills
} from "../src/lib/database-filtering.mjs";

const skills = [
  {
    id: "leader-skill-106",
    search: "表现提升 MyGO!!!!! 高松燈",
    kind: "leader",
    effects: ["1002", "1003"],
    targets: ["band-1"],
    conditional: false,
    status: "identified",
    cards: 1,
    name: "パフォーマンスUP"
  },
  {
    id: "support-skill-23",
    search: "ライブスキル延長 Ave Mujica 三角初華",
    kind: "support",
    effects: ["15000"],
    targets: ["band-2"],
    conditional: true,
    status: "partial",
    cards: 2,
    name: "ライブスキル延長"
  }
];

test("skill filters combine normalized search and relationship facets", () => {
  const result = filterSkills(skills, {
    query: "ＭＹＧＯ　燈",
    kind: "leader",
    effect: "1002",
    target: "band-1",
    conditional: "no",
    status: "identified"
  });

  assert.deepEqual(result.map((skill) => skill.id), ["leader-skill-106"]);
});

test("skill sorting and URL params preserve only active choices", () => {
  assert.deepEqual(
    sortSkills(skills, "cards").map((skill) => skill.id),
    ["support-skill-23", "leader-skill-106"]
  );
  assert.equal(
    skillParams({
      query: "得分",
      kind: "all",
      effect: "1002",
      target: "all",
      conditional: "all",
      status: "all",
      sort: "id"
    }).toString(),
    "q=%E5%BE%97%E5%88%86&effect=1002"
  );
});

const items = [
  {
    id: "item-3",
    search: "コイン coin",
    type: "14",
    usages: ["skill_level", "member_awake"],
    icon: "present",
    availability: "active",
    order: 3,
    cards: 12,
    name: "コイン"
  },
  {
    id: "item-10000001",
    search: "メンバーピース 高松燈",
    type: "9",
    usages: ["member_rank"],
    icon: "missing",
    availability: "active",
    order: 10000001,
    cards: 1,
    name: "メンバーピース"
  }
];

test("item filters combine type, usage and asset state", () => {
  const result = filterItems(items, {
    query: "coin",
    type: "14",
    usage: "skill_level",
    icon: "present",
    availability: "active"
  });

  assert.deepEqual(result.map((item) => item.id), ["item-3"]);
});

test("item sorting and URL params preserve only active choices", () => {
  assert.deepEqual(
    sortItems(items, "cards").map((item) => item.id),
    ["item-3", "item-10000001"]
  );
  assert.equal(
    itemParams({
      query: "",
      type: "all",
      usage: "member_rank",
      icon: "all",
      availability: "all",
      sort: "order"
    }).toString(),
    "usage=member_rank"
  );
});

test('multiple skill kinds and effects use OR within groups and AND between groups', () => {
  const filters = { kind: 'leader,support', effect: '1002,15000', target: 'band-1,band-2', conditional: 'yes,no' };
  assert.deepEqual(filterSkills(skills, filters).map(s => s.id), skills.map(s => s.id));
  assert.deepEqual(filterSkills(skills, {...filters, status: 'partial'}).map(s => s.id), ['support-skill-23']);
  const params = skillParams(filters);
  assert.equal(params.get('kind'), 'leader,support');
  assert.equal(params.get('target'), 'band-1,band-2');
});

test('item type and usage selections combine without losing existing single-select links', () => {
  assert.equal(filterItems(items, {type: '14,9', usage: 'skill_level,member_rank'}).length, 2);
  assert.deepEqual(filterItems(items, {type: '14,9', usage: 'member_awake', icon: 'present'}).map(i => i.id), ['item-3']);
  assert.equal(itemParams({type: '14,9', usage: 'skill_level,member_rank'}).get('type'), '14,9');
});

test('skill taxonomy filters compose with kind and preserve multi-select URLs', () => {
  const records = [
    { id: 'just', kind: 'gekisou', facets: { 'gekisou-type': ['just'], 'gekisou-effect': ['just:13000'] } },
    { id: 'just-support', kind: 'gekisou_support', facets: { 'gekisou-type': ['just'], 'gekisou-effect': ['just:13005'] } },
    { id: 'luck', kind: 'gekisou', facets: { 'gekisou-type': ['luck'] } },
    { id: 'heal', kind: 'support', facets: { 'skill-role': ['heal'] } },
    { id: 'life', kind: 'live', facets: { 'live-type': ['life'] } },
    { id: 'pure', kind: 'live', facets: { 'live-type': ['simple'] } }
  ];
  assert.deepEqual(filterSkills(records, { 'gekisou-type': 'just', kind: 'gekisou_support' }).map(s => s.id), ['just-support']);
  assert.deepEqual(filterSkills(records, { 'gekisou-type': 'just', 'gekisou-effect': 'just:13000' }).map(s => s.id), ['just']);
  assert.deepEqual(filterSkills(records, { 'skill-role': 'heal' }).map(s => s.id), ['heal']);
  assert.deepEqual(filterSkills(records, { 'live-type': 'life' }).map(s => s.id), ['life']);
  assert.deepEqual(filterSkills(records, { 'live-type': 'simple,life' }).map(s => s.id), ['life', 'pure']);
  assert.deepEqual(filterSkills(records, { 'gekisou-type': 'all', 'skill-role': 'all', 'live-type': 'all' }), records);
  const selected = { 'gekisou-type': 'just,luck', 'gekisou-effect': 'just:13000', 'live-type': 'all', 'skill-role': 'all' };
  const params = skillParams(selected);
  assert.equal(params.get('gekisou-type'), 'just,luck');
  assert.equal(params.get('gekisou-effect'), 'just:13000');
  assert.equal(params.has('live-type'), false);
  assert.deepEqual(filterSkills(records, Object.fromEntries(params)).map(s => s.id), ['just']);
});
