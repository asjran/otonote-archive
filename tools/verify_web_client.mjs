#!/usr/bin/env node
/** Exercise the actual browser bundle against a local immutable snapshot. No network. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {scoringRulesAvailable} from '../site/src/lib/scoring-release-gate.mjs';
const [codePath,storePath,locale='zh-CN',reportPath] = process.argv.slice(2);
const code=resolve(codePath),store=resolve(storePath);
globalThis.location=new URL(`http://preview.invalid/global/${locale}/`);
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
const pointer=JSON.parse(await readFile(join(store,'current.json'),'utf8'));
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
    globalThis.location=new URL(`http://preview.invalid/global/${locale}/${path}/`);
    const page=await import(new URL(route.module,app.root));
    const paths=page.getStaticPaths ? await page.getStaticPaths({}) : [{params:{},props:{}}];
    if(!paths.length) {results.push({route:route.pattern,status:'empty'});continue;}
    const entry=route.pattern==='stories/episodes/[id]' ? paths.find(p=>p.params.id===story)??paths[0] : paths[0];
    path=route.pattern.replace(/\[(?:\.\.\.)?([^\]]+)\]/g,(_,key)=>entry.params[key]);
    globalThis.location=new URL(`http://preview.invalid/global/${locale}/${path}/`);
    const html=await renderToString(renderContext(location,entry.params,app),page.default,entry.props??{},{},true);
    if(!(html instanceof Response) && !(route.pattern.startsWith('database/details/') ? html.includes('data-db-detail') : html.includes('<main'))) throw Error('Missing page content');
    const calculatorMarkers={'tools/deck-builder/index':'data-team-draft-data','tools/optimizer/index':'data-team-draft-data',
      'tools/song-calculator/index':'data-scoring-research-data','tools/song-ranking/index':'data-ranking-data'};
    const marker=calculatorMarkers[route.pattern] ?? calculatorMarkers[route.pattern+'/index'];
    if(marker && !(html instanceof Response)) {
      if(toolsExpected && (!html.includes(marker) || html.includes('data-scoring-unavailable')))
        throw Error('Current scoring content is available but tool controls are missing');
      if(!toolsExpected && !html.includes('data-scoring-unavailable')) throw Error('Unavailable scoring content must not expose stale calculations');
      if(toolsExpected && rules.verificationStatus==='reference_compatible' && !html.includes('data-scoring-reference'))
        throw Error('Reference estimate must disclose its verification scope');
    }
    results.push({route:route.pattern,path,status:html instanceof Response?'redirect':'passed',entries:paths.length,bytes:html.length});
  } catch(error) {results.push({route:route.pattern,status:'failed',error:error.stack});}
}
const report={locale,code:codePath,snapshot:pointer.manifest,results};
if(reportPath) await writeFile(reportPath,JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
if(results.some(r=>r.status==='failed')) process.exitCode=1;
