/** Exhaustive JP route/resource audit of a sealed browser bundle. Story workers
 * isolate URL-dependent eager imports exactly as separate browser documents. */
import {readFile,writeFile,stat} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Worker,isMainThread,workerData,parentPort} from 'node:worker_threads';
const args=isMainThread?process.argv.slice(2):workerData.args;
const [codeArg,storeArg,locale='zh-CN',reportPath]=args;
const code=resolve(codeArg),store=resolve(storeArg),base=`/jp/${locale}/`;
const selectedStory=workerData?.story;
globalThis.location=new URL('https://audit.invalid'+base+(selectedStory?`stories/episodes/${selectedStory}/`:''));
globalThis.__OURNOTES_BASE__=base;
const pointer=JSON.parse(await readFile(join(store,'jp/current.json'),'utf8'));
const manifest=JSON.parse(await readFile(join(store,pointer.manifest.slice(9)),'utf8'));
const fetches=new Set(),issues=new Set(),urls=new Set(),links=new Set();
globalThis.fetch=async input=>{
 const u=new URL(input,location);fetches.add(u.pathname);
 if(u.origin!==location.origin||!u.pathname.startsWith('/content/'))throw Error('Unexpected fetch '+u);
 if(u.pathname!='/content/jp/current.json'&&!u.pathname.startsWith(manifest.root))throw Error('Foreign content '+u);
 try{return new Response(await readFile(join(store,u.pathname.slice(9))))}catch{return new Response('',{status:404})}
};
globalThis[Symbol.for('ournotes.content-root.v1')]=manifest.root;
const app=JSON.parse(await readFile(join(code,'compiled/manifest.json'),'utf8'));
app.root=pathToFileURL(join(code,'compiled')+'/').href;
const shell=await readFile(join(code,'index.html'),'utf8');
const boot=shell.match(/src="\/app\/releases\/[a-f0-9]+\/([^"]+)"/)[1];
const {renderToString,renderContext}=await import(new URL(boot,app.root));
const results=[];
async function render(route,page,entry){
 const path=route.pattern.replace(/\[(?:\.\.\.)?([^\]]+)\]/g,(_,k)=>entry.params[k]);
 globalThis.location=new URL('https://audit.invalid'+base+(path?path+'/':''));
 try{
 const html=await renderToString(renderContext(location,entry.params,app),page.default,entry.props??{},{},true);
 if(html instanceof Response)return {path,status:'redirect',location:html.headers.get('location')};
 if(!html.includes(route.pattern.startsWith('database/details/')?'data-db-detail':'<main'))throw Error('Missing page content');
 for(const m of html.matchAll(/(?:src|href|poster|data-url|data-src)="([^"<>]+)"/g)){
 const v=m[1].replaceAll('&amp;','&');if(v.startsWith('/content/'))urls.add(v);
 if(v.startsWith(base))links.add(v.split(/[?#]/)[0]);
 }
 for(const m of html.matchAll(/\/content\/releases\/[a-f0-9]{24}\//g))if(m[0]!==manifest.root)issues.add(`foreign root: ${path}: ${m[0]}`);
 const status=html.includes('data-scoring-unavailable')?'intentionally_unavailable':'passed';
 return {path,status,bytes:html.length};
 }catch(e){return {path,status:'failed',error:String(e.stack)}}
}
for(const route of app.routes){
 if(Boolean(selectedStory)!=(route.pattern==='stories/episodes/[id]'))continue;
 globalThis.location=new URL('https://audit.invalid'+base+(selectedStory?`stories/episodes/${selectedStory}/`:route.pattern.replace(/\[.*?\]/g,'index')+'/'));
 try{
 const page=await import(new URL(route.module,app.root));
 const entries=page.getStaticPaths?await page.getStaticPaths({}):[{params:{},props:{}}];
 const selected=selectedStory?entries.filter(e=>e.params.id===selectedStory):entries;
 if(!selected.length)results.push({route:route.pattern,status:'empty',entries:entries.length});
 for(const entry of selected)results.push({route:route.pattern,...await render(route,page,entry)});
 }catch(e){results.push({route:route.pattern,status:'failed',error:String(e.stack)})}
}
if(isMainThread){
 const ids=Object.keys(manifest.locales[locale].files).filter(k=>k.startsWith('projection/story-text/')).map(k=>k.split('/').at(-1).slice(0,-5));
 let next=0;
 async function lane(){while(next<ids.length){const story=ids[next++];const r=await new Promise((ok,bad)=>{const w=new Worker(new URL(import.meta.url),{workerData:{args,story}});w.on('message',ok);w.on('error',bad);w.on('exit',c=>{if(c)bad(Error('Worker exit '+c))})});results.push(...r.results);r.urls.forEach(v=>urls.add(v));r.links.forEach(v=>links.add(v));r.issues.forEach(v=>issues.add(v));r.fetches.forEach(v=>fetches.add(v));}}
 await Promise.all([lane(),lane()]);
 for(const url of urls){if(!url.startsWith(manifest.root)){issues.add('foreign url: '+url);continue}try{await stat(join(store,decodeURI(url.split(/[?#]/)[0]).slice(9)))}catch{issues.add('missing resource: '+url)}}
 const valid=new Set(results.filter(r=>r.path!==undefined).map(r=>base+(r.path?r.path+'/':'')));
 for(const url of links)if(!valid.has(url)&&!url.includes('/search-index.json')){try{await stat(join(code,'compiled',url.slice(base.length)))}catch{issues.add('unresolved internal link: '+url)}}
 const report={locale,code:codeArg,pointer,counts:results.reduce((a,r)=>(a[r.status]=(a[r.status]??0)+1,a),{}),resources:urls.size,fetches:[...fetches],issues:[...issues],results};
 await writeFile(reportPath,JSON.stringify(report,null,2));console.log(JSON.stringify({locale,counts:report.counts,resources:urls.size,issues:[...issues].slice(0,30),failures:results.filter(r=>r.status==='failed').slice(0,10)}));
 if(issues.size || results.some(r=>r.status==='failed'))process.exitCode=1;
}else parentPort.postMessage({results,urls:[...urls],links:[...links],issues:[...issues],fetches:[...fetches]});
