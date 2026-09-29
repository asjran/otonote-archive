import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {summarizeSearchSpace,formatCombinationCount} from '../src/lib/optimizer-search-summary.mjs';
import {resolveSearchInput} from '../src/lib/scoring-rules/formation-input.mjs';
import {createTeamDraft} from '../src/lib/team-draft.mjs';
const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
test('Mujica band restriction keeps all 62 supports; expert does not shrink the inventory',()=>{
  const draft=createTeamDraft({selectedSongId:'music-100001',selectedDifficulty:'expert'});
  const input=resolveSearchInput(rules,draft,{scope:'theoretical',constraints:{bandId:2}});
  const summary=summarizeSearchSpace(rules,input);
  assert.deepEqual(summary,{members:15,characters:5,supports:62,memberSelections:'243',combinations:'943472091600'});
  assert.equal(formatCombinationCount(summary.combinations),'约 9434.72 亿');
  const hard=resolveSearchInput(rules,{...draft,selectedDifficulty:'hard'},{scope:'theoretical',constraints:{bandId:2}});
  assert.deepEqual(summarizeSearchSpace(rules,hard),summary);
});
test('five selected pairs still allow 120 assignments and five leaders',()=>{
  const draft=createTeamDraft({slots:[1,2,3,4,5].map(i=>({memberCardId:`member-card-${i}`,supportCardId:`support-card-${i}`}))});
  const input=resolveSearchInput(rules,draft);
  assert.equal(summarizeSearchSpace(rules,input).combinations,'600');
  const fixed=resolveSearchInput(rules,draft,{constraints:{leaderId:1}});
  assert.equal(summarizeSearchSpace(rules,fixed).combinations,'120');
});
test('count matches independent enumeration of distinct-character selections',()=>{
  const fake={tables:{MemberCard:Array.from({length:8},(_,i)=>({_id:i,_characterID:i<3?1:i}))}};
  const ids=fake.tables.MemberCard.map(r=>`member-card-${r._id}`);
  let count=0;
  function enumerate(start,chosen){if(chosen.length===5){if(new Set(chosen.map(r=>r._characterID)).size===5)count++;return;}for(let i=start;i<8;i++)enumerate(i+1,[...chosen,fake.tables.MemberCard[i]]);}
  enumerate(0,[]);
  const summary=summarizeSearchSpace(fake,{inventory:{memberCardIds:ids,supportCardIds:[1,2,3,4,5]},constraints:{}});
  assert.equal(summary.memberSelections,String(count));assert.equal(BigInt(summary.combinations),BigInt(count)*120n*5n);
});
