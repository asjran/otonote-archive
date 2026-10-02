import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {selectEventYieldRows,eventYieldGoals} from '../src/lib/event-yield-goals.mjs';
import {eventYieldStageInput} from '../src/lib/event-yield-stage.mjs';
test('cycle stages choose independent collection and AP basis without inheriting a normal grade',()=>{
 const input={mode:'ordinary',includeChallenge:true,scope:'selected',basis:'minimumScore',challengeScope:'owned',challengeBasis:'expectedScore',draft:{slots:[]}};
 assert.equal(eventYieldStageInput(input,'ordinary').scope,'selected');
 const challenge=eventYieldStageInput(input,'challenge');
 assert.equal(challenge.scope,'owned');assert.equal(challenge.basis,'expectedScore');assert.equal(challenge.mode,'challenge');
 assert.equal(input.scope,'selected');
 assert.equal(eventYieldStageInput({...input,challengeScope:'same'},'challenge').scope,'selected');
 assert.equal(eventYieldStageInput({...input,mode:'challenge'},'challenge').scope,'selected');
});
test('joint event recommendation exposes both item and event-point objectives',()=>{
 const page=readFileSync(new URL('../src/pages/tools/event-efficiency/index.astro',import.meta.url),'utf8');
 const goals=page.match(/<select data-yield-goal>([\s\S]*?)<\/select>/)?.[1];
 assert.match(goals,/value="badges"/);
 assert.match(goals,/value="eventPoints"/);
 assert.match(goals,/^<option value="both"/);
});
test('both objectives retain different teams for the same song instead of hiding its point leader',()=>{
 const base={song:{id:'song',seconds:100},reward:{scoreRank:5},expectedScore:1000};
 const items={...base,id:'items-team',total:{badges:11550,eventPoints:3100},recommendationGoals:['badges']};
 const points={...base,id:'r-team',total:{badges:5770,eventPoints:3470},recommendationGoals:['eventPoints']};
 const selected=selectEventYieldRows([items,points],'both');
 assert.deepEqual(selected.map(r=>r.id),['items-team','r-team']);
 assert.deepEqual(selected.map(r=>r.recommendationGoals),[['badges'],['eventPoints']]);
 assert.deepEqual(selectEventYieldRows(selected,'eventPoints').map(r=>r.id),['r-team']);
 assert.deepEqual(eventYieldGoals('both','challenge'),['badges','eventPoints']);
 assert.deepEqual(eventYieldGoals('grade','challenge'),['badges']);
});
test('identical reward plans share both labels without duplicate display or losing labels on repeated trimming',()=>{
 const row={id:'a',song:{id:'s',seconds:10},reward:{scoreRank:5},expectedScore:1000,total:{badges:200,eventPoints:150}};
 const result=selectEventYieldRows([{...row,recommendationGoals:['badges']},{...row,recommendationGoals:['eventPoints']}]);
 assert.equal(result.length,1);assert.deepEqual(result[0].recommendationGoals,['badges','eventPoints']);
 assert.deepEqual(selectEventYieldRows(result),result);
});
