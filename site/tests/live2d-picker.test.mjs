import test from 'node:test';
import assert from 'node:assert/strict';
import { adjacentLook, filterCharacters, filterLooks, lookKind } from '../src/lib/live2d-picker.mjs';

const characters = [
  { id: 1, name: '高松灯', group: 'band-1', aliases: ['Tomori'] },
  { id: 'sub_popo', name: '波波', group: 'story', aliases: ['popo'] },
];
const models = [
  { id: 'one', characterId: 1, modelPath: '001_adv/model/adv_live2d_tomori_001_casual_spring_01', state: 'available', usage: 'story' },
  { id: 'two', characterId: 1, modelPath: '001_adv/model/adv_live2d_tomori_001_school_winter_hs_1st', state: 'available', usage: 'story' },
  { id: 'missing', characterId: 1, modelPath: '001_adv/model/adv_live2d_tomori_001_live_01', state: 'unavailable', usage: 'story' },
  { id: 'npc', characterId: 'sub_popo', modelPath: 'sub_popo/model/adv_live2d_sub_popo_school_winter_hs', state: 'available', usage: 'story' },
];

test('character filtering supports localized aliases, resource names, groups and empty results without changing input', () => {
  const before = structuredClone(models);
  assert.deepEqual(filterCharacters(characters, models, 'all', ' TOMORI ').map(c => c.id), [1]);
  assert.deepEqual(filterCharacters(characters, models, 'story', 'school').map(c => c.id), ['sub_popo']);
  assert.deepEqual(filterCharacters(characters, models, 'band-1', '波波'), []);
  assert.deepEqual(models, before);
});

test('look filtering combines character, type and translated or raw name', () => {
  assert.deepEqual(filterLooks(models, '1', 'school', '冬季').map(m => m.id), ['two']);
  assert.deepEqual(filterLooks(models, 1, 'daily', 'school'), []);
  assert.deepEqual(filterLooks(models, 'sub_popo', 'all', 'School', true).map(m => m.id), ['npc']);
  assert.equal(lookKind({ modelPath: 'model/adv_live2d_uika_006_child_casual_summer_01_still' }), 'special');
});

test('quick switching wraps within the same character and skips unavailable looks', () => {
  assert.equal(adjacentLook(models, 'two', 1).id, 'one');
  assert.equal(adjacentLook(models, 'one', -1).id, 'two');
  assert.equal(adjacentLook(models, 'npc', 1).id, 'npc');
  assert.equal(adjacentLook([], 'unknown', 1), undefined);
});
