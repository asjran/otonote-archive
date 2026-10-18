// Cold process, local data only. The same harness can load a frozen --root.
// Example: node tools/benchmark_event_yield_search.mjs --data /tmp/data.json \
//   --chart /tmp/chart.json --event 2 --output /tmp/event-yield.json
import {readFileSync,writeFileSync,readdirSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {cpus,platform,arch,release} from 'node:os';
const {values}=parseArgs({options:{
 root:{type:'string',default:resolve(import.meta.dirname,'..')},data:{type:'string'},'band-items':{type:'string'},chart:{type:'string'},event:{type:'string'},
 input:{type:'string'},output:{type:'string'},mode:{type:'string',default:'ordinary'},goal:{type:'string',default:'badges'},
 basis:{type:'string',default:'expectedScore'},'live-boost':{type:'string',default:'1'},'challenge-cost':{type:'string',default:'200'},
 budget:{type:'string',default:'100'},'starting-cp':{type:'string',default:'0'},'include-challenge':{type:'boolean',default:false},
 'challenge-rows':{type:'string'},evaluations:{type:'string',default:'0'},'time-limit-ms':{type:'string',default:'120000'},
 'refine-score-ties':{type:'boolean',default:false},'cpu-limit-ms':{type:'string',default:'0'}
}});
for(const key of ['data','chart','event','output'])if(!values[key])throw Error(`Missing --${key}`);
for(const key of ['event','live-boost','challenge-cost','budget','starting-cp','evaluations','time-limit-ms','cpu-limit-ms'])
 if(!Number.isSafeInteger(Number(values[key]))||Number(values[key])<0)throw Error(`Invalid --${key}`);
if(values['include-challenge']&&!values['challenge-rows'])throw Error('--include-challenge requires fixed --challenge-rows; generating them inside the timed run would change the input');
const load=p=>import(pathToFileURL(resolve(values.root,p)));
const {optimizeEventYield}=await load('site/src/lib/event-yield-optimizer.mjs');
const {createTeamDraft}=await load('site/src/lib/team-draft.mjs');
const {createInventoryManager}=await load('site/src/lib/inventory-manager.mjs');
const {maximizeAccount}=await load('site/src/lib/workbench-account-model.mjs');
const {withBandItemLevels}=await load('packages/scoring/scoring-rules/band-item-levels.mjs');
const data=JSON.parse(readFileSync(values.data)),rawRules=data.rules??data,chart=JSON.parse(readFileSync(values.chart));
const rules=values['band-items']?withBandItemLevels(rawRules,JSON.parse(readFileSync(values['band-items']))):rawRules;
const personal=values.input?JSON.parse(readFileSync(values.input)):{};
const manager=createInventoryManager(rules),inventory=personal.inventory??{memberCardIds:rules.tables.MemberCard.map(r=>`member-card-${r._id}`),
 supportCardIds:rules.tables.SupportCard.map(r=>`support-card-${r._id}`),growth:{}};
if(!personal.inventory)for(const kind of ['member','support'])for(const id of inventory[`${kind}CardIds`])inventory.growth[id]=manager.preset(id,kind,'maximum');
const account=maximizeAccount({},rules);account.tgwCardRank=Math.max(1,...rules.tables.VipRankBonus.map(r=>r._vipRank));
const draft=personal.draft??createTeamDraft({selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,modifiers:personal.account??account});
const suppliedRows=values['challenge-rows']?JSON.parse(readFileSync(values['challenge-rows'])):[];
const challengeRows=suppliedRows.results??suppliedRows;
const candidate=personal.candidate??{id:chart.id,trackId:chart.trackId,difficulty:chart.difficulty,seconds:100,title:'fixed benchmark chart'};
const input={rules,chart,draft,inventory,candidate,scope:'owned',eventId:Number(values.event),mode:values.mode,goal:values.goal,basis:values.basis,
 liveBoost:Number(values['live-boost']),challengeCost:Number(values['challenge-cost']),budget:Number(values.budget),startingCP:Number(values['starting-cp']),
 includeChallenge:values['include-challenge'],challengeRows,maxEvaluations:Number(values.evaluations),refineScoreTies:values['refine-score-ties']};
const hash=value=>createHash('sha256').update(value).digest('hex'),inputHash=hash(JSON.stringify(input));
const sources={};
for(const directory of ['packages/scoring','site/src/lib'])for(const entry of readdirSync(resolve(values.root,directory),{recursive:true,withFileTypes:true})){
 if(!entry.isFile()||!(entry.name.endsWith('.mjs')||directory==='packages/scoring'&&entry.name.endsWith('.json')))continue;
 const path=resolve(entry.parentPath??entry.path,entry.name);sources[path.slice(resolve(values.root).length+1)]=hash(readFileSync(path));
}
const sorted=Object.fromEntries(Object.entries(sources).sort(([a],[b])=>a.localeCompare(b)));
const scoringSources=Object.fromEntries(Object.entries(sorted).filter(([p])=>
 p.startsWith('packages/scoring/')&&!/bound|maximum-pairing|search-queue/.test(p)||p==='site/src/lib/formation-candidate-evaluator.mjs'));
const controller=new AbortController(),start=performance.now(),cpu=process.cpuUsage(),phases={};
let stage='',stageAt=start,bestTuple=null,finalBestAtMs=null,lastProgress=null;
const result=await optimizeEventYield({...input,signal:controller.signal,yieldControl:async()=>{},onProgress:p=>{
 const next=p.phase==='practical'?p.stage:p.phase;
 if(next!==stage){phases[stage]=(phases[stage]??0)+performance.now()-stageAt;stage=next;stageAt=performance.now();}
 if(p.bestCandidate){const r=p.bestCandidate,tuple=JSON.stringify([input.goal==='grade'?r.reward?.scoreRank:null,r.total,input.refineScoreTies?r.expectedScore:null]);
  if(tuple!==bestTuple){bestTuple=tuple;finalBestAtMs=performance.now()-start;}}
 lastProgress={phase:p.phase,expanded:p.expanded,completed:p.completed,frontier:p.frontier};
 if(Number(values['time-limit-ms'])&&performance.now()-start>=Number(values['time-limit-ms']))controller.abort();
 const used=process.cpuUsage(cpu);if(Number(values['cpu-limit-ms'])&&(used.user+used.system)/1000>=Number(values['cpu-limit-ms']))controller.abort();
}});
phases[stage]=(phases[stage]??0)+performance.now()-stageAt;
const usage=process.cpuUsage(cpu),first=result.results[0];
const counterParts={practical:result.practical.fullScoreCalculations,exact:result.certifiedSearch?.fullScoreCalculations,bound:result.certifiedSearch?.boundScoreCalculations};
// The frozen baseline's global ceiling exits before constructing a score
// bound. Only this audited proof tag admits deriving the missing exact zeros.
let counterCoverage=Object.values(counterParts).every(Number.isSafeInteger)?'complete':'incomplete';
if(counterCoverage==='incomplete'&&result.certifiedSearch?.proof==='global_grade_and_bonus_ceiling'&&Number.isSafeInteger(counterParts.practical)){
 counterParts.exact??=0;counterParts.bound??=0;counterCoverage='derived_global_ceiling';
}
const row={root:resolve(values.root),node:process.version,inputHash,sourceHash:hash(JSON.stringify(sorted)),scoringModelHash:hash(JSON.stringify(scoringSources)),sourceManifest:sorted,
 environment:{platform:platform(),arch:arch(),osRelease:release(),cpu:cpus()[0]?.model,cpuCount:cpus().length,v8:process.versions.v8},
 inputFiles:Object.fromEntries(['data','band-items','chart','input','challenge-rows'].filter(k=>values[k]).map(k=>[k,{path:resolve(values[k]),sha256:hash(readFileSync(values[k]))}])),
 sourceReleaseId:rules.sourceReleaseId,chartId:chart.id,mode:input.mode,goal:input.goal,basis:input.basis,includeChallenge:input.includeChallenge,
 farmingBudget:input.budget,liveBoost:input.liveBoost,startingCP:input.startingCP,challengeCost:input.challengeCost,
 account:values.input?'supplied_local_input':'maximum_account_and_full_owned_maximum_growth',
 accountParameters:Object.fromEntries(['bandItems','bandItemTotals','characterRanks','tgwCardRank','memoryPoints'].map(key=>[key,draft.modifiers?.[key]??null])),
 memberCount:inventory.memberCardIds.length,supportCount:inventory.supportCardIds.length,budget:input.maxEvaluations,timeLimitMs:Number(values['time-limit-ms']),cpuLimitMs:Number(values['cpu-limit-ms']),
 wallMs:performance.now()-start,cpuMs:(usage.user+usage.system)/1000,rssBytes:process.resourceUsage().maxRSS*1024,
 finalBestAtMs,rewardTuple:first?{scoreRank:first.reward.scoreRank,total:first.total}:null,score:first?.expectedScore,status:result.status,optimality:result.optimality,
 counterCoverage,counterParts,fullScoreCalculations:counterCoverage!=='incomplete'?Object.values(counterParts).reduce((a,b)=>a+b,0):null,
 evaluated:result.evaluated,practical:result.practical,certificate:result.certifiedSearch,phases,lastProgress,bestTeam:first?.draft.slots};
writeFileSync(values.output,JSON.stringify(row,null,2)+'\n');
console.log(JSON.stringify({output:values.output,wallMs:row.wallMs,rewardTuple:row.rewardTuple,bestProven:row.certificate?.bestProven,
 expanded:row.certificate?.expanded,fullScoreCalculations:row.fullScoreCalculations,remainingGap:row.certificate?.optimalityGap}));
