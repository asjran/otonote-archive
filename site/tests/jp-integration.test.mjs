import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {homeEvents,scheduleLabel} from '../src/lib/home-content.mjs';
import {projectFormalChart} from '../../tools/project_formal_charts.mjs';
import {createFormationCalculator} from '../src/lib/scoring-rules/formation-power.mjs';
import {createTeamDraft} from '../src/lib/team-draft.mjs';

test('homepage includes upcoming events and changes status at JP schedule boundaries',()=>{
  const event={id:1,schedule:{startAt:'2026/09/30 18:00:00',endAt:'2026/10/08 21:00:00'}};
  const [row]=homeEvents([event],'jp',Date.parse('2026-09-30T08:00:00Z'));
  assert.equal(row.start,Date.parse('2026-09-30T09:00:00Z'));
  assert.equal(scheduleLabel(row.start,row.end,row.start-1),'即将登场');
  assert.equal(scheduleLabel(row.start,row.end,row.start),'进行中');
  assert.equal(scheduleLabel(row.start,row.end,row.end),'已结束');
  assert.deepEqual(homeEvents([],'jp'),[]);
});
test('published chart timeline and density use the calculator reconstruction',()=>{
  const chart=JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10000103.json',import.meta.url)));
  const output=projectFormalChart(chart);
  assert.equal(output.comboEvents.length,768);
  assert.equal(output.statistics.runtimeFullCombo,768);
  assert.equal(output.density.reduce((n,b)=>n+b.count,0),768);
  assert.equal(output.comboEvents.at(-1).combo,768);
  assert.equal(output.statistics.explicitJudgementCount+output.statistics.slideComboCandidateCount-output.statistics.skippedSlideComboCount-output.statistics.mergedEndpointReduction,768);
});
test('JUST leader target checks the member skill, not song mission or band',()=>{
  const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
  const members=rules.tables.MemberCard.slice(0,5);
  const just=rules.tables.GekisouSkill.find(s=>s._gekisouMissionType===3);
  const other=rules.tables.GekisouSkill.find(s=>s._gekisouMissionType!==3);
  members.forEach((m,i)=>{m._gekisouSkillID=i%2?other._id:just._id;});
  const leader=members[2];
  const effect=rules.tables.LeaderSkillEffect.find(e=>e._leaderSkillID===leader._leaderSkillID);
  rules.tables.LeaderSkillEffect=[{...effect,_level:1,_skillTargetIDs:[53],_skillEffectType:1002,_effectValue:2000}];
  const draft=createTeamDraft({slots:members.map((m,i)=>({memberCardId:`member-card-${m._id}`,supportCardId:`support-card-${i+1}`}))});
  const result=createFormationCalculator(rules).calculate(draft);
  assert.deepEqual(result.slots.map(s=>s.ratesBP.leader[2]),[2000,0,2000,0,2000]);
});
