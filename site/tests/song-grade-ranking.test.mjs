import test from 'node:test';
import assert from 'node:assert/strict';
import {validGradeThresholds,gradeAtScore,songGradeReference,rankGradeRows,customSkillScore} from '../src/lib/song-grade-ranking.mjs';
const thresholds=[2,3,4,5,6,7].map((rank,i)=>({rank,score:i*1000000}));
const row={id:'a',title:'A',difficulty:'expert',level:25,bands:[],expectedScore:500000,baseScore:400000,chartSeconds:100,benchmark:{power:100000},gradeReferences:{global:{verified:true,thresholds}}};
test('score thresholds decide rank at exact crossings without any team',()=>{
 assert.equal(gradeAtScore(thresholds,0),2);assert.equal(gradeAtScore(thresholds,999999),2);assert.equal(gradeAtScore(thresholds,1000000),3);assert.equal(gradeAtScore(thresholds,9000000),7);
 assert.throws(()=>gradeAtScore(thresholds,-1));assert.throws(()=>gradeAtScore(thresholds,1.5));
 assert.equal(validGradeThresholds(thresholds.slice(1)),null);assert.equal(validGradeThresholds(thresholds.map((r,i)=>({...r,score:i===1?0:r.score}))),null);
});
test('unified grade view includes both libraries and prefers verified reference consistently',()=>{
 const jp={...row,id:'jp-only',gradeReferences:{jp:{...row.gradeReferences.global,edition:'jp'}}};
 assert.equal(rankGradeRows([row,jp]).length,2);
 const mixed={...row,gradeReferences:{global:{verified:false,thresholds},jp:jp.gradeReferences.jp}};
 assert.equal(songGradeReference(mixed).gradeReference.edition,'jp');
 assert.equal(songGradeReference(mixed).requiredPower,750000);
});
test('custom skill parameters scale window gain and never invent missing duration data',()=>{
 const r={...row,skillScoreGain:100000,skillReference:{gains:Array.from({length:41},(_,i)=>i*10000)}};
 assert.equal(customSkillScore(r,{skillPercent:100,skillSeconds:5}),row.expectedScore);
 assert.equal(customSkillScore(r,{skillPercent:80,skillSeconds:6}),496000);
 assert.equal(customSkillScore(r,{skillPercent:0,skillSeconds:20}),row.baseScore);
 assert.equal(customSkillScore(r,{skillPercent:100,skillSeconds:0}),row.baseScore);
 assert.equal(customSkillScore(row,{skillSeconds:6}),null);
 assert.throws(()=>customSkillScore(r,{skillPercent:-1}));assert.throws(()=>customSkillScore(r,{skillPercent:1001}));
 assert.throws(()=>customSkillScore(r,{skillSeconds:5.1}));assert.throws(()=>customSkillScore(r,{skillSeconds:21}));
 assert.ok(songGradeReference(r,{profile:'custom',skillPercent:100,skillSeconds:10}).requiredPower<songGradeReference(r,{profile:'custom',skillPercent:100,skillSeconds:5}).requiredPower);
});
test('target power uses the selected fixed skill profile, not one universal power number',()=>{
 assert.equal(songGradeReference(row,{edition:'global',targetRank:5}).requiredPower,750000);
 assert.equal(songGradeReference(row,{edition:'global',targetRank:5,profile:'benchmark'}).requiredPower,600000);
 const entered=songGradeReference(row,{edition:'global',targetRank:6,score:3000000});assert.equal(entered.enteredRank,5);assert.equal(entered.targetGap,1000000);
 assert.equal(songGradeReference(row,{edition:'global',targetRank:2}).displayPower,0);
 assert.equal(songGradeReference({...row,baseScore:410000},{edition:'global'}).displayPower,732000);
});
test('missing or unverified edition keeps score lookup but never borrows another edition power',()=>{
 assert.equal(songGradeReference(row,{edition:'jp'}).requiredPower,null);
 const pending={...row,gradeReferences:{global:{verified:false,thresholds}}};
 const result=songGradeReference(pending,{edition:'global',score:3000000});assert.equal(result.requiredPower,null);assert.equal(result.enteredRank,5);
 assert.equal(songGradeReference({...row,benchmark:null},{edition:'global'}).requiredPower,null);
});
test('grade ranking orders low required power first with shared song filters and unrated rows last',()=>{
 const rows=[row,{...row,id:'b',title:'B',baseScore:600000},{...row,id:'c',baseScore:null},{...row,id:'d',gradeReferences:{jp:row.gradeReferences.global}}];
 assert.deepEqual(rankGradeRows(rows,{edition:'global'}).map(r=>[r.id,r.rank]),[['b',1],['a',2],['c',null]]);
 assert.deepEqual(rankGradeRows(rows,{edition:'global',query:'B'}).map(r=>r.id),['b']);
 assert.equal(rankGradeRows(rows,{edition:'global',difficulty:'easy'}).length,0);
});
