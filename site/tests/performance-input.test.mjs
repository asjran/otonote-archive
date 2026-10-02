import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createPerformanceTemplate} from '../src/lib/scoring-rules/formal-performance-replay.mjs';
import {parsePerformanceInput,setupPerformanceInput} from '../src/lib/performance-input.mjs';
const rules=JSON.parse(readFileSync(new URL('../src/data/formal-scoring-rules.json',import.meta.url)));
const chart=JSON.parse(readFileSync(new URL('../public/data/music-charts/music-chart-10000103.json',import.meta.url)));

test('import binds every judgement to the selected chart and rejects malformed or partial records',()=>{
  const template=createPerformanceTemplate(rules,chart);
  assert.equal(parsePerformanceInput(JSON.stringify(template),rules,chart).judgements.length,768);
  assert.throws(()=>parsePerformanceInput('{',rules,chart),/JSON/);
  assert.throws(()=>parsePerformanceInput(' '.repeat(8*1024*1024+1),rules,chart),/8 MB/);
  assert.throws(()=>parsePerformanceInput(JSON.stringify({...template,chartHash:'different'}),rules,chart));
  assert.throws(()=>parsePerformanceInput(JSON.stringify({...template,judgements:template.judgements.slice(1)}),rules,chart));
});

function page() {
  const nodes=new Map(); let current=chart, calculations=0;
  const find=name=>{if(!nodes.has(name))nodes.set(name,{value:'',textContent:'',listeners:{},addEventListener(k,fn){this.listeners[k]=fn;}});return nodes.get(name);};
  const root={querySelector:selector=>find(selector.match(/data-performance-(.*?)\]/)[1])};
  const input=setupPerformanceInput(root,{rules,getChart:()=>current,recalculate:()=>calculations++});
  input.sync(chart);
  return {input,find,setChart:value=>{current=value;input.sync(value);},calculations:()=>calculations};
}

test('invalid replacement stops old inputs and changing charts resets the applied performance',()=>{
  const f=page(), template=createPerformanceTemplate(rules,chart);
  f.find('json').value=JSON.stringify(template); f.find('apply').listeners.click();
  assert.equal(f.input.value.chartId,chart.id);
  f.find('json').value='{}'; f.find('apply').listeners.click();
  assert.throws(()=>f.input.value,/JSON/);
  f.find('json').value=JSON.stringify(template); f.find('apply').listeners.click();
  f.setChart({...chart,id:'different'});
  assert.equal(f.input.value,null);assert.equal(f.find('json').value,'');
});

test('a slow file read cannot apply after the selected chart changes',async()=>{
  const f=page();let finish;
  f.find('file').files=[{size:100,text:()=>new Promise(resolve=>{finish=resolve;})}];
  const pending=f.find('file').listeners.change();
  f.setChart({...chart,id:'different'});
  finish(JSON.stringify(createPerformanceTemplate(rules,chart)));await pending;
  assert.equal(f.input.value,null);assert.equal(f.find('json').value,'');assert.equal(f.calculations(),0);
});
