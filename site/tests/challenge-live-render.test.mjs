import test from 'node:test';
import assert from 'node:assert/strict';
import {setupChallengeOptimizer} from '../src/lib/challenge-optimizer-ui.mjs';

function harness(t){
 class Node {
  constructor(){this.dataset={};this.children=[];this.listeners={};this.attrs={};this.value='';}
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  removeChild(node){this.children.splice(this.children.indexOf(node),1);}
  insertBefore(node,anchor){if(this.children.includes(node))this.removeChild(node);this.children.splice(anchor?this.children.indexOf(anchor):this.children.length,0,node);}
  before(node){this.progress=node;}
  setAttribute(k,v){this.attrs[k]=v;}
  removeAttribute(k){delete this.attrs[k];}
  addEventListener(k,fn){this.listeners[k]=fn;}
  querySelectorAll(selector){return this.children.flatMap(n=>[...(n.className?.split(' ').includes(selector.slice(1))?[n]:[]),...n.querySelectorAll(selector)]);}
 }
 const prior={document:globalThis.document,Worker:globalThis.Worker},nodes=new Map(),workers=[];
 globalThis.document={documentElement:{lang:'zh-CN'},createElement:()=>new Node()};
 globalThis.Worker=class extends Node {constructor(){super();workers.push(this);}postMessage(input){this.input=input;}terminate(){this.terminated=true;}};
 t.after(()=>{for(const [k,v] of Object.entries(prior)){if(v===undefined)delete globalThis[k];else globalThis[k]=v;}});
 const node=k=>{if(!nodes.has(k))nodes.set(k,new Node());return nodes.get(k);},q=k=>node(`[data-challenge-opt-${k}]`);
 node('mode').value='challenge';node('event').value='3';q('scope').value='reference';q('objective').value='maximum_song_score';
 const draft={slots:[],selectedSongId:'music-100114',selectedDifficulty:'expert',modifiers:{}};
 const tool={q:node,querySelector:node,draft,data:{rules:{tables:{LiveMusic:[]}},tracks:[{id:draft.selectedSongId,title:'挑战曲'}],charts:[{trackId:draft.selectedSongId,difficulty:'expert',analysisDataUrl:'/chart.json'}]}};
 const optimizer=setupChallengeOptimizer(tool);optimizer.sync();q('run').listeners.click();t.after(()=>optimizer.destroy());
 assert.equal(workers.length,1);
 const send=data=>workers.at(-1).listeners.message({data});
 const snapshot=(value=1000,type='snapshot')=>({type,result:{objective:'maximum_song_score',searchScope:'reference',status:type==='snapshot'?'budget_exhausted':'completed',practical:{finalists:6},certifiedSearch:{expanded:24,evaluated:2,frontier:20,bestProven:type==='result'},results:['one','two'].map((id,i)=>({id,value:value-i,maximumScore:value-i,minimumScore:value-10-i,expectedScore:value-5-i,power:100,draft:{...draft,slots:[{memberCardId:id,supportCardId:id}]}}))}});
 const articles=()=>q('results').querySelectorAll('.challenge-opt-result');
 const tabs=()=>q('results').children.find(n=>n.attrs['aria-label']==='冲榜候选队伍');
 return {q,node,optimizer,send,snapshot,workers,articles,tabs};
}

test('challenge snapshots coalesce and preserve selected teams and playback through proof updates and completion',async t=>{
 const {q,send,snapshot,articles,tabs}=harness(t);
 send(snapshot());const initial=articles();tabs().children[1].listeners.click();
 const next=snapshot();next.result.certifiedSearch.expanded=100;send(next);
 assert.equal(articles()[0],initial[0]);
 await new Promise(r=>setTimeout(r,780));
 assert.equal(articles()[0],initial[0]);assert.equal(articles()[1],initial[1]);assert.equal(initial[1].hidden,false);
 send(snapshot(1000,'result'));
 assert.equal(articles()[0],initial[0]);assert.equal(articles()[1],initial[1]);assert.equal(initial[1].hidden,false);
 assert.equal(q('status').progress.dataset.state,'complete');
 assert.match(initial[0].children[0].textContent,/最佳配队/);
});

test('challenge pause flushes latest candidates and resume restores busy feedback without losing the frontier',async t=>{
 const {q,send,snapshot,workers,articles}=harness(t);
 send(snapshot());send(snapshot(1200));q('cancel').listeners.click();
 assert.equal(workers[0].input.type,'pause');
 const paused=snapshot(1200,'result');paused.result.status='paused';paused.result.certifiedSearch.bestProven=false;send(paused);
 assert.match(articles()[0].children[0].textContent,/1,200/);
 const settled=articles()[0];
 await new Promise(r=>setTimeout(r,780));
 assert.equal(articles()[0],settled);assert.equal(q('status').progress.dataset.state,'stopped');
 q('run').listeners.click();assert.equal(workers.length,1);assert.equal(workers[0].input.type,'resume');
 assert.equal(q('status').progress.dataset.state,'running');
});

test('late progress cannot overwrite completion, errors or invalidated conditions',async t=>{
 const {q,send,snapshot,optimizer,articles}=harness(t);
 send({type:'progress',stage:'准备配队',completed:1,total:10});
 send({type:'progress',stage:'准备配队',completed:2,total:10});
 send(snapshot());send(snapshot(1400));send({type:'error',message:'测试故障'});
 assert.match(articles()[0].children[0].textContent,/1,400/);
 await new Promise(r=>setTimeout(r,780));
 assert.equal(q('status').progress.dataset.state,'error');assert.match(q('status').textContent,/测试故障/);
 q('run').listeners.click();send(snapshot());send(snapshot(1600));optimizer.invalidate();
 await new Promise(r=>setTimeout(r,780));
 assert.equal(articles().length,0);assert.equal(q('status').progress.hidden,true);
});
