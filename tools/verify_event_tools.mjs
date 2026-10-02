/** Render only the affected tools against an immutable content snapshot. */
import {readFile,writeFile} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
const [codeArg,storeArg,locale='zh-CN',reportPath,region='global']=process.argv.slice(2);
const code=resolve(codeArg),store=resolve(storeArg);
globalThis.location=new URL(`http://preview.invalid/${region}/${locale}/`);
globalThis.__OURNOTES_BASE__=location.pathname;
globalThis.fetch=async input=>{
 const url=new URL(input,location),file=resolve(store,url.pathname.slice('/content/'.length));
 if(url.origin!==location.origin||!url.pathname.startsWith('/content/')||!file.startsWith(store+'/'))throw Error('Unexpected content request');
 try{return new Response(await readFile(file));}catch{return new Response('',{status:404});}
};
const app=JSON.parse(await readFile(join(code,'compiled/manifest.json'),'utf8'));
app.root=pathToFileURL(join(code,'compiled')+'/').href;
const shell=await readFile(join(code,'index.html'),'utf8');
const boot=shell.match(/src="\/app\/releases\/[a-f0-9]+\/([^"]+)"/)[1];
const {renderToString,renderContext}=await import(new URL(boot,app.root));
const markers={'tools':'/tools/event-efficiency/','tools/deck-builder':'data-team-draft-data',
 'tools/optimizer':'data-team-draft-data','tools/song-calculator':'data-scoring-research-data','tools/event-efficiency':'data-event-inputs','tools/song-ranking':'data-ranking-data'};
const results=[];
for(const [pattern,marker] of Object.entries(markers)){
 const route=app.routes.find(r=>r.pattern===pattern);if(!route)throw Error('Missing route: '+pattern);
 globalThis.location=new URL(`http://preview.invalid/${region}/${locale}/${pattern}/`);
 const page=await import(new URL(route.module,app.root));
 const html=await renderToString(renderContext(location,{},app),page.default,{}, {},true);
 if(typeof html!=='string'||!html.includes(marker)||html.includes('data-scoring-unavailable'))throw Error('Tool unavailable: '+pattern);
 results.push({route:pattern,status:'passed',bytes:Buffer.byteLength(html)});
}
const report={code:codeArg,region,locale,results};
if(reportPath)await writeFile(reportPath,JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
