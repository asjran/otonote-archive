import test from 'node:test';
import assert from 'node:assert/strict';
import { eventBonusCharacters } from '../src/lib/event-bonus-characters.mjs';

const catalog = {
  bands:[{id:'band-a',masterId:1},{id:'band-b',masterId:2}],
  characters:[{id:'a',masterId:11,bandId:'band-a'},{id:'b',masterId:12,bandId:'band-a'},
    {id:'c',masterId:21,bandId:'band-b'},{id:'d',masterId:22,bandId:'band-b'}],
  memberCards:[{masterId:101,characterId:'a'}],
  supportCards:[{masterId:201,featuredCharacterIds:['b','c']}]
};
const ids = (...rules) => eventBonusCharacters(rules.map(constraints=>({constraints})), catalog).map(c=>c.id);

test('mixed casts retain every explicitly targeted character across bands',()=>{
  assert.deepEqual(ids({characterId:11},{characterId:21},{characterId:11}),['a','c']);
});
test('band bonuses expand their members alongside individual cross-band bonuses',()=>{
  assert.deepEqual(ids({bandId:1},{characterId:21}),['a','b','c']);
});
test('card-specific rules resolve member and multi-character support cards without duplicates',()=>{
  assert.deepEqual(ids({memberCardId:101},{supportCardId:201},{characterId:11}),['a','b','c']);
});
test('intersect conditions within a rule and ignore unknown targets and attribute-only bonuses',()=>{
  assert.deepEqual(ids({bandId:1,characterId:12}),['b']);
  assert.deepEqual(ids({bandId:1,characterId:21},{bandId:99},{memberCardId:999},{supportCardId:999},{cardType:2}),[]);
  assert.deepEqual(ids({bandId:1,supportCardId:201}),['b']);
  assert.deepEqual(ids(),[]);
});
