// Replays supplied, local formal data. No network or private inventory upload.
// Example: node tools/benchmark_challenge_search.mjs --data /tmp/event.json \
//   --chart /tmp/music-chart.json --event 2 --root /tmp/frozen-source --output /tmp/run.json
import {readFileSync,writeFileSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const {values}=parseArgs({options:{
  root:{type:'string',default:resolve(import.meta.dirname,'..')},data:{type:'string'},chart:{type:'string'},event:{type:'string'},
  scope:{type:'string',default:'reference'},objective:{type:'string',default:'maximum_song_score'},
  evaluations:{type:'string',default:'0'},'time-limit-ms':{type:'string',default:'120000'},input:{type:'string'},output:{type:'string'}
}});
if(!values.data||!values.chart||!values.event||!values.output)throw Error('--data, --chart, --event and --output are required');
for(const key of ['evaluations','time-limit-ms'])if(!Number.isSafeInteger(Number(values[key]))||Number(values[key])<0)throw Error(`Invalid ${key}`);
const load=p=>import(pathToFileURL(resolve(values.root,p)));
const {optimizeChallenge}=await load('site/src/lib/challenge-optimizer.mjs');
const {createTeamDraft}=await load('site/src/lib/team-draft.mjs');
const data=JSON.parse(readFileSync(values.data)),rules=data.rules??data,chart=JSON.parse(readFileSync(values.chart));
const personal=values.input?JSON.parse(readFileSync(values.input)):{};
// Explicit reproducible reference account, distinct from any user's settings.
const modifiers=personal.account??{characterRanks:Object.fromEntries(rules.tables.Character.map(c=>[c._id,25])),
  bandItems:Object.fromEntries(rules.tables.BandItem.map(c=>[c._id,25])),tgwCardRank:21};
const draft=personal.draft??createTeamDraft({selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,modifiers});
const input={rules,chart,draft,inventory:personal.inventory,scope:values.scope,eventId:Number(values.event),objective:values.objective,
  maxEvaluations:Number(values.evaluations)};
const inputHash=createHash('sha256').update(JSON.stringify(input)).digest('hex');
const controller=new AbortController(),start=performance.now(),cpu=process.cpuUsage(),phases={};
let stage='',stageAt=start,best=-Infinity,finalBestAtMs=null;
const result=await optimizeChallenge({...input,signal:controller.signal,yieldControl:async()=>{},onProgress:p=>{
  const next=p.phase==='practical'?p.stage:p.phase;
  if(next!==stage){phases[stage]=(phases[stage]??0)+performance.now()-stageAt;stage=next;stageAt=performance.now();}
  if(p.bestCandidate?.value>best){best=p.bestCandidate.value;finalBestAtMs=performance.now()-start;}
  if(Number(values['time-limit-ms'])&&performance.now()-start>=Number(values['time-limit-ms']))controller.abort();
}});
phases[stage]=(phases[stage]??0)+performance.now()-stageAt;
const usage=process.cpuUsage(cpu),row={root:resolve(values.root),node:process.version,inputHash,
  sourceReleaseId:rules.sourceReleaseId,chartId:chart.id,objective:values.objective,scope:values.scope,
  account:values.input?'supplied_local_input':'all_band_items_25_character_ranks_25_tgw_21',
  memberCount:personal.inventory?.memberCardIds?.length??rules.tables.MemberCard.length,
  supportCount:personal.inventory?.supportCardIds?.length??rules.tables.SupportCard.length,
  budget:Number(values.evaluations),timeLimitMs:Number(values['time-limit-ms']),wallMs:performance.now()-start,
  cpuMs:(usage.user+usage.system)/1000,rssBytes:process.resourceUsage().maxRSS*1024,
  finalBestAtMs,score:result.results[0]?.value,status:result.status,optimality:result.optimality,
  evaluated:result.evaluated,practical:result.practical,certificate:result.certifiedSearch,phases,
  ...(globalThis.__searchProfile?{profile:globalThis.__searchProfile}:{}),
  bestTeam:result.results[0]?.draft.slots};
writeFileSync(values.output,JSON.stringify(row,null,2)+'\n');
console.log(JSON.stringify({output:values.output,wallMs:row.wallMs,score:row.score,bestProven:row.certificate?.bestProven,
  expanded:row.certificate?.expanded,evaluated:row.certificate?.evaluated,remainingGap:row.certificate?.optimalityGap}));
