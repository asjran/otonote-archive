#!/usr/bin/env node
/** Exercise the actual browser bundle against a local immutable snapshot. No network. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {scoringRulesAvailable} from '../packages/scoring/scoring-release-gate.mjs';
import {catalogIdentity,stableContent} from '../site/src/lib/edition-library.mjs';
const [codePath,storePath,locale='zh-CN',reportPath,region='global'] = process.argv.slice(2);
if(!['global','jp'].includes(region)) throw Error('Unknown edition');
const code=resolve(codePath),store=resolve(storePath);
globalThis.location=new URL(`http://preview.invalid/${region}/${locale}/`);
globalThis.__OURNOTES_BASE__=location.pathname;
globalThis.fetch=async input=>{
  const url=new URL(input,location);
  if(url.origin!==location.origin || !url.pathname.startsWith('/content/')) throw Error('Unexpected fetch: '+url);
  const file=resolve(store,url.pathname.slice('/content/'.length));
  if(!file.startsWith(store+'/')) throw Error('Unsafe fetch');
  try {return new Response(await readFile(file));} catch {return new Response('',{status:404});}
};
const app=JSON.parse(await readFile(join(code,'compiled/manifest.json'),'utf8'));
app.root=pathToFileURL(join(code,'compiled')+'/').href;
const shell=await readFile(join(code,'index.html'),'utf8');
const boot=shell.match(/src="\/app\/releases\/[a-f0-9]+\/([^"]+)"/)[1];
const {renderToString,renderContext}=await import(new URL(boot,app.root));
const pointer=JSON.parse(await readFile(join(store,region==='global'?'current.json':'jp/current.json'),'utf8'));
const manifest=JSON.parse(await readFile(join(store,pointer.manifest.slice('/content/'.length)),'utf8'));
const snapshotRoot=join(store,pointer.manifest.slice('/content/'.length),'..');
const ruleRecord=manifest.locales[locale].files['supplemental/formal-scoring-rules.json'];
const rules=ruleRecord ? JSON.parse(await readFile(join(snapshotRoot,ruleRecord.path),'utf8')) : null;
const toolsExpected=scoringRulesAvailable(rules,manifest.contentReleaseId);
globalThis[Symbol.for('ournotes.content-root.v1')]=manifest.root;
const story=Object.keys(manifest.locales[locale].files).find(n=>n.startsWith('projection/story-text/'))?.split('/').at(-1).replace('.json','');
// ESM modules are cached within a document. Start with the episode so its
// lazy text import sees the same URL it would see in a fresh browser document.
app.routes.sort((a,b)=>Number(b.pattern==='stories/episodes/[id]')-Number(a.pattern==='stories/episodes/[id]'));
const results=[];
for(const route of app.routes) {
  try {
    let path=route.pattern.replace('[id]',story??'test');
    globalThis.location=new URL(`http://preview.invalid/${region}/${locale}/${path}/`);
    const page=await import(new URL(route.module,app.root));
    const paths=page.getStaticPaths ? await page.getStaticPaths({}) : [{params:{},props:{}}];
    if(!paths.length) {results.push({route:route.pattern,status:'empty'});continue;}
    const entry=route.pattern==='stories/episodes/[id]' ? paths.find(p=>p.params.id===story)??paths[0] : paths[0];
    path=route.pattern.replace(/\[(?:\.\.\.)?([^\]]+)\]/g,(_,key)=>entry.params[key]);
    globalThis.location=new URL(`http://preview.invalid/${region}/${locale}/${path}/`);
    const html=await renderToString(renderContext(location,entry.params,app),page.default,entry.props??{},{},true);
    if(!(html instanceof Response) && !(route.pattern.startsWith('database/details/') ? html.includes('data-db-detail') : html.includes('<main'))) throw Error('Missing page content');
    const calculatorMarkers={'tools/deck-builder/index':'data-team-draft-data','tools/optimizer/index':'data-team-draft-data',
      'tools/song-calculator/index':'data-scoring-research-data'};
    const marker=calculatorMarkers[route.pattern] ?? calculatorMarkers[route.pattern+'/index'];
    if(marker && !(html instanceof Response)) {
      if(toolsExpected && (!html.includes(marker) || html.includes('data-scoring-unavailable')))
        throw Error('Current scoring content is available but tool controls are missing');
      if(!toolsExpected && !html.includes('data-scoring-unavailable')) throw Error('Unavailable scoring content must not expose stale calculations');
      if(toolsExpected && rules.verificationStatus==='reference_compatible' && !html.includes('data-scoring-reference'))
        throw Error('Reference estimate must disclose its verification scope');
    }
    if (route.pattern.replace(/\/index$/, '') === 'tools/song-ranking' && !(html instanceof Response)) {
      const payload = html.match(/<script[^>]*data-ranking-data[^>]*>([\s\S]*?)<\/script>/)?.[1];
      if (!payload) throw Error('Shared ranking payload is missing');
      const {rankings} = JSON.parse(payload);
      const sourceCache=new Map();
      for (const mode of ['ordinary','gekisou']) for (const row of rankings[mode]) {
        if (row.pending ? row.expectedScore !== null : !row.applicableEditions?.length)
          throw Error('Ranking result is missing its calculation provenance');
        for (const edition of row.applicableEditions) {
          if (!sourceCache.has(edition)) {
          const p = JSON.parse(await readFile(join(store,edition==='global'?'current.json':'jp/current.json'),'utf8'));
          const m = JSON.parse(await readFile(join(store,p.manifest.slice('/content/'.length)),'utf8'));
          const record = m.locales[locale].files['supplemental/song-rankings.json'];
          const data = JSON.parse(await readFile(join(store,m.root.slice('/content/'.length),record.path),'utf8'));
          const catalogRecord=m.locales[locale].files['projection/catalog.json'];
          const catalog=JSON.parse(await readFile(join(store,m.root.slice('/content/'.length),catalogRecord.path),'utf8'));
          const identities=new Map(catalog.musicCharts.map(chart=>{
            const track=catalog.musicTracks.find(t=>t.id===chart.trackId);
            const song=track && catalogIdentity('musicTracks',track,catalog);
            return [chart.id,song && chart.contentIdentity ? stableContent([song,chart.difficulty,chart.contentIdentity]) : null];
          }));
          sourceCache.set(edition,{data,identities});
          }
          const {data,identities}=sourceCache.get(edition);
          if (data.unavailable || data.sourceReleaseId !== rankings.releases[edition] ||
              !data[mode].some(source => source.expectedScore === row.expectedScore &&
                (source.chartFingerprint === row.chartFingerprint || row.chartIdentity && identities.get(source.id)===row.chartIdentity)))
            throw Error('Shared ranking does not match its published source result');
        }
      }
    }
    results.push({route:route.pattern,path,status:html instanceof Response?'redirect':'passed',entries:paths.length,bytes:html.length});
  } catch(error) {results.push({route:route.pattern,status:'failed',error:error.stack});}
}
const report={locale,code:codePath,snapshot:pointer.manifest,results};
if(reportPath) await writeFile(reportPath,JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
if(results.some(r=>r.status==='failed')) process.exitCode=1;
