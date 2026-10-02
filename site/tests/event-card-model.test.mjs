import assert from 'node:assert/strict';
import test from 'node:test';
import { collectEventCards } from '../src/lib/event-card-model.mjs';
const reward = (type, id) => ({resourceType:type, resourceId:id, name:`Card ${type}:${id}`, count:1, rarity:3, resolved:true});
const base = () => ({pickupCards:[],achievements:[],exchanges:[],effects:[],ranking:{rewards:[]},challengeSongs:[]});
test('card identity includes type and preserves every acquisition threshold alongside bonuses', () => {
  const event = base();
  event.pickupCards = [reward(2,63)];
  event.achievements = [100000,150000].map(points => ({points,rewards:[reward(2,63),reward(1,33)]}));
  event.exchanges = [{products:[{reward:reward(3,63),cost:100000,limit:5}]}];
  event.effects = [0,1].map(() => ({constraints:{memberCardId:63,supportCardId:0}}));
  const before = structuredClone(event);
  const cards = collectEventCards(event,reward);
  assert.equal(cards.length,2);
  assert.deepEqual(cards[0].sources.map(source => source.points),[100000,150000]);
  assert.equal(cards[0].bonus,true);
  assert.equal(cards[1].bonus,false);
  assert.equal(cards[1].sources[0].cost,100000);
  assert.equal(cards[1].sources[0].limit,5);
  assert.deepEqual(event,before);
});
test('bonus-only cards are included once and missing catalog entries remain identifiable', () => {
  const event = base();
  event.effects = [{constraints:{memberCardId:61,supportCardId:62}},{constraints:{memberCardId:61,bandId:3,cardType:2}}];
  const cards = collectEventCards(event,() => undefined);
  assert.deepEqual(cards.map(card => [card.resourceType,card.resourceId]),[[2,61],[3,62]]);
  assert.ok(cards.every(card => card.bonus && !card.resolved && !card.sources.length));
});
test('ranking reward cards are included without inventing an exchange or points source', () => {
  const event = base();
  event.challengeSongs = [{rankingRewards:[{rewards:[reward(3,10),reward(17,20000001)]}]}];
  const cards = collectEventCards(event,reward);
  assert.equal(cards.length,1);
  assert.deepEqual(cards[0].sources,[{kind:'ranking'}]);
});
