/** Explicit local benchmark; formal rules/chart inputs are not bundled here.
 * node site/tests/benchmark-challenge-search.mjs --rules FILE --chart FILE --output FILE
 * Optional: --source-root DIR --account FILE --objective expected_song_score
 * --max-evaluations N limits a comparison run; --max-ms N cancels a slow run.
 */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const option=(name,fallback)=>{const i=process.argv.indexOf('--'+name);return i<0?fallback:process.argv[i+1];};
const rulesPath=option('rules'),chartPath=option('chart'),output=option('output');
if(!rulesPath||!chartPath||!output)throw Error('Required: --rules FILE --chart FILE --output FILE');
const root=resolve(option('source-root',fileURLToPath(new URL('../../',import.meta.url))));
const {optimizeChallenge}=await import(pathToFileURL(resolve(root,'site/src/lib/challenge-optimizer.mjs')));
const {createTeamDraft}=await import(pathToFileURL(resolve(root,'site/src/lib/team-draft.mjs')));
const rules=JSON.parse(await readFile(rulesPath,'utf8')),chart=JSON.parse(await readFile(chartPath,'utf8'));
chart.sourceReleaseId??=rules.sourceReleaseId;
const accountPath=option('account'),modifiers=accountPath?JSON.parse(await readFile(accountPath,'utf8')):{
 characterRanks:Object.fromEntries(rules.tables.Character.map(c=>[c._id,25])),
 bandItems:Object.fromEntries(rules.tables.BandItem.map(c=>[c._id,25])),tgwCardRank:12
};
const draft=createTeamDraft({selectedSongId:chart.trackId,selectedDifficulty:chart.difficulty,modifiers});
const eventId=Number(option('event',rules.tables.ChallengeMusic.find(r=>`music-${r._liveMusicId}`===chart.trackId)?._eventId));
const objective=option('objective','maximum_song_score'),maxEvaluations=Number(option('max-evaluations',0)),maxMs=Number(option('max-ms',120000));
if(!Number.isInteger(maxEvaluations)||maxEvaluations<0||!Number.isFinite(maxMs)||maxMs<=0)throw Error('Invalid benchmark budget');
const digest=value=>createHash('sha256').update(value).digest('hex');
const sources=['site/src/lib/challenge-optimizer.mjs','site/src/lib/event-formation-search.mjs',
 'packages/scoring/scoring-rules/ordinary-score-bound.mjs','packages/scoring/scoring-rules/maximum-pairing.mjs'];
const sourceHashes=Object.fromEntries(await Promise.all(sources.map(async path=>[path,digest(await readFile(resolve(root,path)))])));
const controller=new AbortController(),started=performance.now(),cpu=process.cpuUsage();
const result=await optimizeChallenge({rules,chart,draft,eventId,scope:'reference',objective,maxEvaluations,signal:controller.signal,
 yieldControl:async()=>{},onProgress:()=>{if(performance.now()-started>maxMs)controller.abort();}});
const usage=process.cpuUsage(cpu),report={runtime:process.version,sourceReleaseId:rules.sourceReleaseId,chart:chart.id,eventId,
 scope:'reference',objective,account:accountPath?'supplied account; only fingerprint retained':'synthetic: all item/rank levels 25, TGW 12',
 inputHash:digest(JSON.stringify({rules,chart,draft,eventId,objective})),sourceHashes,maxEvaluations,maxMs,
 wallMs:performance.now()-started,cpuMs:(usage.user+usage.system)/1000,status:result.status,
 score:result.results[0]?.value,certificate:result.certifiedSearch};
await mkdir(dirname(resolve(output)),{recursive:true});await writeFile(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
