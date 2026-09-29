import assert from 'node:assert/strict';
import test from 'node:test';
import { buildPublishedSearchIndex } from '../src/lib/unified-search-index.mjs';

const base = { sourceReleaseId: 'r1', entries: [
  { id: 'music-1', title: '歌曲', type: 'music', href: '/music/music-1/' },
  { id: 'old-story', title: '未发布剧情', type: 'story', href: '/stories/episodes/old-story/' }
] };
const sources = { releaseId: 'r1', locale: 'zh-CN', library: {
  sourceReleaseId: 'r1', locale: 'zh-CN', characters: [{ id: 1, name: '高松灯' }], bands: [{ id: 1, name: 'MyGO!!!!!' }],
  entries: [{ id: 'story-1', title: '相遇', description: '第一次见面', chapterName: '开始', characterIds: [1], bandIds: [1] }]
}, items: [{ id: 'item-1', name: '材料', description: '觉醒道具', masterId: 1 }],
  skills: [{ id: 'skill-1', name: '技能', highestSummary: '分数增加', effects: [{ name: '得分' }], masterId: 1 }] };

test('only published story routes enter the index alongside items and skills', () => {
  const result = buildPublishedSearchIndex(base, sources);
  assert.deepEqual(result.entries.map(e => e.id), ['music-1', 'story-1', 'item-1', 'skill-1']);
  assert.equal(result.entries[1].href, '/stories/episodes/story-1/');
  assert.ok(result.entries[1].searchableText.includes('高松灯 MyGO!!!!!'));
  assert.equal(result.entries[2].href, '/database/items/#detail=item-1');
  assert.equal(result.entries[3].href, '/database/skills/#detail=skill-1');
  assert.deepEqual(result.suggestions, ['MyGO!!!!!']);
  assert.equal(base.entries.length, 2);
});

test('search generation rejects mixed releases or locales', () => {
  assert.throws(() => buildPublishedSearchIndex(base, { ...sources, releaseId: 'r2' }), /active release/);
  assert.throws(() => buildPublishedSearchIndex(base, { ...sources, locale: 'en' }), /active release/);
});
