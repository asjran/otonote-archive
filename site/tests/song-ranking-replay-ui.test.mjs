import test from 'node:test';
import assert from 'node:assert/strict';
import {setupSongRankingReplay} from '../src/lib/song-ranking-replay-ui.mjs';
import {songSkillProfileKey} from '../src/lib/song-skill-profile.mjs';
import {SCORE_MODEL_VERSION} from '../src/lib/scoring-rules/model-version.mjs';

const skills=Array.from({length:5},()=>({percent:100,seconds:5}));
const row={id:'a',sourceId:'chart-a',trackId:'global--song-a',title:'Song',difficulty:'expert',benchmark:{power:100000},expectedScore:90,replaySource:{releaseId:'release-a'}};
const replay={mode:'ordinary',precision:'replay',modelVersion:SCORE_MODEL_VERSION,chartId:'chart-a',trackId:'song-a',difficulty:'expert',power:100000,
  sourceReleaseId:'release-a',skills,frameRate:60,profileKey:songSkillProfileKey(skills),baseScore:80,distribution:{mean:100,minimum:90,maximum:110,p10:95}};
class Field extends EventTarget {
  value=''; hidden=false; disabled=false; textContent=''; children=[]; attrs={};
  append(...children){this.children.push(...children);}
  replaceChildren(...children){this.children=children;}
  setAttribute(name,value){this.attrs[name]=value;}
}
function fixture(t,{failStart=false,rows=[row]}={}) {
  const previous={document:globalThis.document,Worker:globalThis.Worker};
  t.after(()=>{for(const [key,value] of Object.entries(previous))if(value===undefined)delete globalThis[key];else globalThis[key]=value;});
  const fields=Object.fromEntries(['cancel','run','panel','status','errors','scope','method','fps','description'].map(key=>[key,new Field()]));
  fields.scope.value='top';fields.method.value='linear';fields.fps.value='60';
  globalThis.document={documentElement:{lang:'zh-CN'},createElement:()=>new Field()};
  const workers=[];
  globalThis.Worker=class extends EventTarget {
    stopped=false;
    constructor(){super();if(failStart)throw Error('blocked');workers.push(this);}
    terminate(){this.stopped=true;}
    postMessage(message){this.input=message;}
    message(data){const event=new Event('message');event.data=data;this.dispatchEvent(event);}
  };
  let changes=0;
  const ui=setupSongRankingReplay({querySelector:selector=>fields[selector.match(/data-replay-(\w+)/)[1]]},()=>{changes++;ui.sync({skills,rows,mode:'ordinary'});});
  ui.sync({skills,rows,mode:'ordinary'});
  t.after(()=>ui.destroy());
  return {ui,fields,workers,changes:()=>changes,run:()=>fields.run.dispatchEvent(new Event('click'))};
}
test('replay progress, partial failure and retry keep only validated completed rows',t=>{
  const {ui,fields,workers,run}=fixture(t,{rows:[row,{...row,id:'bad'}]});
  run();const worker=workers[0];
  assert.equal(fields.panel.attrs['aria-busy'],'true');assert.equal(fields.run.disabled,true);
  assert.equal(fields.method.value,'replay');
  worker.message({type:'row',id:'a',result:replay});worker.message({type:'progress',done:1});
  assert.match(fields.status.textContent,/1 \/ 2/);assert.equal(ui.rows([row])[0].expectedScore,100);
  worker.message({type:'done',failures:[{title:'Other',message:'Missing data'}]});
  ui.sync({skills,rows:[row],mode:'ordinary'});
  assert.equal(fields.run.disabled,false);assert.equal(fields.panel.attrs['aria-busy'],'false');assert.equal(fields.errors.hidden,false);
  assert.match(fields.errors.children[0].textContent,/未完成，可重试/);
  assert.equal(ui.rows([row])[0].expectedScore,100);
  run();assert.equal(workers.length,2);
});
test('stop retains completed results and ignores late messages from the stopped worker',t=>{
  const {ui,fields,workers,run}=fixture(t);
  run();workers[0].message({type:'row',id:'a',result:replay});
  fields.cancel.dispatchEvent(new Event('click'));
  ui.sync({skills,rows:[row],mode:'ordinary'});
  assert.equal(workers[0].stopped,true);assert.equal(fields.cancel.hidden,true);
  assert.match(fields.status.textContent,/保留 1 张/);
  workers[0].message({type:'row',id:'a',result:{...replay,distribution:{mean:999}}});
  assert.equal(ui.rows([row])[0].expectedScore,100);
});
test('frame rate changes cancel work and clear incompatible completed results',t=>{
  const {ui,fields,workers,run}=fixture(t);
  run();workers[0].message({type:'row',id:'a',result:replay});
  fields.fps.value='120';ui.sync({skills,rows:[row],mode:'ordinary'});
  assert.equal(workers[0].stopped,true);assert.equal(fields.method.value,'linear');assert.deepEqual(ui.rows([row]),[]);
});
test('invalid input cancels work and disables replay; recovery and reset are usable',t=>{
  const {ui,fields,workers,run}=fixture(t);
  run();ui.invalidate();
  assert.equal(workers[0].stopped,true);assert.equal(fields.run.disabled,true);assert.equal(fields.panel.attrs['aria-busy'],'false');
  ui.sync({skills,rows:[row],mode:'ordinary'});assert.equal(fields.run.disabled,false);
  run();workers[1].message({type:'row',id:'a',result:replay});ui.reset();
  assert.deepEqual(ui.rows([row]),[]);assert.equal(fields.method.value,'linear');assert.equal(workers[1].stopped,true);
});
test('worker load errors preserve completed data and allow retry',t=>{
  const {ui,fields,workers,run}=fixture(t);
  run();workers[0].message({type:'row',id:'a',result:replay});workers[0].dispatchEvent(new Event('error'));
  ui.sync({skills,rows:[row],mode:'ordinary'});
  assert.match(fields.status.textContent,/加载失败/);assert.equal(fields.run.disabled,false);assert.equal(ui.rows([row]).length,1);
  assert.deepEqual(ui.rows([{...row,replaySource:{releaseId:'other'}}]),[],'a different content release cannot borrow a replay');
});
test('unsupported worker start and Gekisou mode expose a recoverable state',t=>{
  const {ui,fields,run}=fixture(t,{failStart:true});run();
  ui.sync({skills,rows:[row],mode:'ordinary'});
  assert.match(fields.status.textContent,/无法开始逐谱精算/);assert.equal(fields.method.value,'linear');assert.equal(fields.run.disabled,false);
  ui.sync({skills,rows:[row],mode:'gekisou'});assert.equal(fields.panel.hidden,true);assert.equal(fields.run.disabled,true);
});
test('no linked data and empty selections explain why replay is disabled',t=>{
  const {ui,fields}=fixture(t,{rows:[{...row,replaySource:null}]});
  assert.equal(fields.run.disabled,true);assert.match(fields.status.textContent,/没有绑定完整谱面/);
  ui.sync({skills,rows:[],mode:'ordinary'});
  assert.equal(fields.run.disabled,true);assert.match(fields.status.textContent,/没有可计算的谱面/);
});
