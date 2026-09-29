import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {cardSkillRows,filterCalculatorCards,cardPlacementConflict} from '../src/lib/calculator-card-model.mjs';
import {matchesSongChart,matchesSongMission} from '../src/lib/calculator-song-picker.mjs';
const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const card=(kind,id)=>{
 const projection=JSON.parse(readFileSync(new URL(`../src/data/generated/database-shards/${kind}-cards/${kind}-card-${id}.json`,import.meta.url))).record;
 return {id:`${kind}-card-${id}`,masterId:id,kind,skills:projection.skillRefs.map(ref=>{
  const skill=JSON.parse(readFileSync(new URL(`../src/data/generated/database-shards/skills/${ref.skillId}.json`,import.meta.url))).record;
  return {slot:ref.slot,kind:skill.kind,name:skill.name,levels:skill.levels.map(l=>({level:l.level,summary:l.renderedSummary}))};
 })};
};
test('skill preview follows live, gekisou and leader levels independently',()=>{
 const c=card('member',26),g={rank:3,skillLevel:2,gekisouSkillLevel:4};
 const rows=cardSkillRows(c,rules,g);
 assert.equal(rows.find(r=>r.slot==='live').level,2);assert.equal(rows.find(r=>r.slot==='gekisou').level,4);
 assert.equal(rows.find(r=>r.slot==='leader').level,rules.tables.MemberCardRank.find(r=>r._group===1&&r._rank===3)._leaderSkillLevel);
 assert.ok(rows.every(r=>r.available));assert.equal(g.rank,3);
});
test('support skill level follows rank rather than displayed maximum',()=>{
 const c=card('support',31),minimum=cardSkillRows(c,rules,{rank:1}),maximum=cardSkillRows(c,rules,undefined,{maximum:true});
 assert.ok(minimum.every(r=>r.level===1));assert.ok(maximum.every(r=>r.level===5&&r.maximum));
 assert.notEqual(minimum.find(r=>r.kind==='gekisou_support').summary,maximum.find(r=>r.kind==='gekisou_support').summary);
});
test('card filters combine ownership, mission, effect, band and multiple attributes',()=>{
 const cards=[{id:'a',masterId:1,kind:'member',shortLabel:'星 之歌',relationLabel:'MyGO',rarity:3,attributeCode:1,bandIds:['b'],characterIds:['c'],skillFacets:{'gekisou-type':['just'],'gekisou-effect':['just:4004']}},
 {id:'b',masterId:2,kind:'member',shortLabel:'星 之歌',rarity:4,attributeCode:2,bandIds:['b'],characterIds:['d'],skillFacets:{'gekisou-type':['luck'],'gekisou-effect':['luck:11002']}}];
 assert.deepEqual(filterCalculatorCards(cards,{query:'星 MyGO',attributes:['1','2'],band:'b',mission:'just',effect:'just:4004',owned:'owned'},{memberCardIds:['a']}).map(c=>c.id),['a']);
 assert.equal(filterCalculatorCards(cards,{mission:'just',effect:'luck:11002'}).length,0);
 assert.deepEqual(filterCalculatorCards(cards).map(c=>c.id),['b','a']);assert.equal(cards[0].id,'a');
});
test('cannot place a second member of same character or duplicate support',()=>{
 const draft={slots:[{memberCardId:'member-1',supportCardId:'support-1'},{memberCardId:'member-2',supportCardId:'support-2'}]},lookup=(_kind,id)=>({characterId:id==='member-1'?'tomori':'anon'});
 assert.equal(cardPlacementConflict({id:'member-26',kind:'member',characterId:'tomori'},draft,1,lookup),0);
 assert.equal(cardPlacementConflict({id:'member-26',kind:'member',characterId:'tomori'},draft,0,lookup),-1);
 assert.equal(cardPlacementConflict({id:'support-1',kind:'support'},draft,1,lookup),0);
});
test('song mission filters distinguish any matching segment from three identical ones',()=>{
 assert.equal(matchesSongMission([1,2,3],'3'),true);assert.equal(matchesSongMission([1,2,3],'3-only'),false);
 assert.equal(matchesSongMission([3,3,3],'3-only'),true);assert.equal(matchesSongMission([1,1,1],'mixed'),false);
 assert.equal(matchesSongMission([1,2,3],'mixed'),true);
});
test('difficulty and level ranges apply to the same available chart',()=>{
 assert.equal(matchesSongChart({difficulty:'expert',level:27,disabled:false},{difficulty:'expert',min:'25',max:'28'}),true);
 assert.equal(matchesSongChart({difficulty:'hard',level:27,disabled:false},{difficulty:'expert',min:'25'}),false);
 assert.equal(matchesSongChart({difficulty:'expert',level:27,disabled:true},{}),false);
 assert.equal(matchesSongChart({difficulty:'expert',level:27,disabled:false},{min:'28',max:'25'}),false);
});
