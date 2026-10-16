// Serial paired runs: AB, BA. Each search gets a fresh process and the same
// harness, Node binary, input, budget and account. No network access is used.
import {mkdirSync,readFileSync,writeFileSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {resolve} from 'node:path';
import {spawn} from 'node:child_process';
const {values}=parseArgs({options:{
  'baseline-root':{type:'string'},'candidate-root':{type:'string'},'output-dir':{type:'string'},
  data:{type:'string'},'band-items':{type:'string'},chart:{type:'string'},event:{type:'string'},
  input:{type:'string'},scope:{type:'string',default:'reference'},objective:{type:'string',default:'maximum_song_score'},
  'account-preset':{type:'string',default:'maximum'},evaluations:{type:'string',default:'0'},
  'time-limit-ms':{type:'string',default:'240000'},pairs:{type:'string',default:'2'}
}});
for(const key of ['baseline-root','candidate-root','output-dir','data','chart','event'])if(!values[key])throw Error(`Missing --${key}`);
const pairs=Number(values.pairs);
if(!Number.isSafeInteger(pairs)||pairs<1)throw Error('--pairs must be a positive integer');
const directory=resolve(values['output-dir']);mkdirSync(directory,{recursive:true});
const harness=resolve(import.meta.dirname,'benchmark_challenge_search.mjs'),samples=[];
for(let pair=0;pair<pairs;pair++)for(const label of pair%2?['candidate','baseline']:['baseline','candidate']){
  const output=resolve(directory,`${samples.length+1}-${label}.json`),args=[harness,'--root',resolve(values[`${label}-root`]),'--output',output];
  for(const key of ['data','band-items','chart','event','input','scope','objective','account-preset','evaluations','time-limit-ms'])
    if(values[key]!=null)args.push(`--${key}`,values[key]);
  await new Promise((done,reject)=>{
    const child=spawn(process.execPath,args,{stdio:'inherit'});
    child.on('error',reject);child.on('exit',code=>code===0?done():reject(Error(`Search exited ${code}`)));
  });
  samples.push({label,file:output,...JSON.parse(readFileSync(output))});
}
const unique=key=>[...new Set(samples.map(row=>JSON.stringify(row[key])))];
const comparable=['inputHash','scoringModelHash','environment','node','budget','timeLimitMs'].every(key=>unique(key).length===1);
const proven=samples.filter(row=>row.certificate?.bestProven),provenScores=[...new Set(proven.map(row=>row.score))];
const summarize=label=>{
  const rows=samples.filter(row=>row.label===label),mean=get=>rows.reduce((n,r)=>n+get(r),0)/rows.length;
  return {runs:rows.length,wallMs:mean(r=>r.wallMs),cpuMs:mean(r=>r.cpuMs),rssBytes:mean(r=>r.rssBytes),
    expanded:mean(r=>r.certificate?.expanded??0),fullScoreCalculations:mean(r=>r.fullScoreCalculations),
    proven:rows.every(r=>r.certificate?.bestProven),scores:[...new Set(rows.map(r=>r.score))]};
};
const baseline=summarize('baseline'),candidate=summarize('candidate');
const summary={comparable,provenScoresAgree:provenScores.length<=1,baseline,candidate,
  speedup:baseline.wallMs/candidate.wallMs,wallReduction:1-candidate.wallMs/baseline.wallMs,
  samples:samples.map(({sourceManifest,...row})=>row)};
writeFileSync(resolve(directory,'summary.json'),JSON.stringify(summary,null,2)+'\n');
console.log(JSON.stringify({summary:resolve(directory,'summary.json'),comparable,baseline,candidate,speedup:summary.speedup}));
if(!comparable||!summary.provenScoresAgree)process.exitCode=1;
