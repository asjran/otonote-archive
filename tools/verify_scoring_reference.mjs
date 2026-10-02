// Verify current cards across every rank/skill level. This tests model support, not gameplay accuracy.
import {readFileSync,writeFileSync} from 'node:fs';
import {createTeamDraft} from '../site/src/lib/team-draft.mjs';
import {createFormationCalculator} from '../packages/scoring/scoring-rules/formation-power.mjs';
import {createFormalSkillResolver} from '../packages/scoring/scoring-rules/formal-skills.mjs';
import {createGekisouSongCalculator} from '../packages/scoring/scoring-rules/gekisou-song-score.mjs';
const rules=JSON.parse(readFileSync(process.argv[2]));
const chart={...JSON.parse(readFileSync(process.argv[3])),sourceReleaseId:rules.sourceReleaseId};
const calc=createFormationCalculator(rules),skills=createFormalSkillResolver(rules),gekisou=createGekisouSongCalculator(rules,chart);
let checks=0,gekisouChecks=0;const failures=[];
for (const m of rules.tables.MemberCard)for(const s of rules.tables.SupportCard)for(const level of [1,2,3,4,5]) {
 const members=rules.tables.MemberCard.filter(x=>x._characterID!==m._characterID).filter((x,i,a)=>a.findIndex(y=>y._characterID===x._characterID)===i).slice(0,4).map(x=>x._id);members.splice(2,0,m._id);
 const supports=rules.tables.SupportCard.filter(x=>x._id!==s._id).slice(0,4).map(x=>x._id);supports.splice(2,0,s._id);
 const slots=members.map((id,i)=>({memberCardId:`member-card-${id}`,supportCardId:`support-card-${supports[i]}`}));
 const growth=Object.fromEntries(slots.flatMap(x=>[[x.memberCardId,{rank:level,awake:level,skillLevel:level,gekisouSkillLevel:level}],[x.supportCardId,{rank:level}]]));
 const draft=createTeamDraft({slots,selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,modifiers:{growth}});
 try{calc.calculate(draft);skills(draft);checks++;if(s._id===1 || m._id===1){gekisou.calculate(draft);gekisouChecks++;}}catch(e){failures.push({member:m._id,support:s._id,level,message:e.message});}
}
console.log(JSON.stringify({checks,gekisouChecks,failures:failures.slice(0,30),failureCount:failures.length}));
writeFileSync(process.argv[4],JSON.stringify({sourceReleaseId:rules.sourceReleaseId,ruleSetVersion:rules.ruleSetVersion,
 referenceProfile:rules.referenceProfile,memberCount:rules.tables.MemberCard.length,supportCount:rules.tables.SupportCard.length,
 checks,gekisouChecks,failures},null,2));
if(failures.length)process.exitCode=1;
