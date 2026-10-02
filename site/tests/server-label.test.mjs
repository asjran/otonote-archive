import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {serverLabelScript} from '../src/lib/server-label.mjs';
function render(url,saved=null,lang='zh-CN',blocked=false){
 const label={textContent:'国际服 · 未选区服'};
 const links=['jp','global-hmt','global-en','global-kr'].map(id=>({dataset:{gameServer:id},setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];}}));
 const switcher={querySelector:()=>label,querySelectorAll:()=>links};
 vm.runInNewContext(serverLabelScript,{document:{documentElement:{lang},querySelectorAll:()=>[switcher]},location:new URL(url),URLSearchParams,localStorage:{getItem(){if(blocked)throw Error('blocked');return saved;}}});
 return {label:label.textContent,selected:links.filter(l=>l['aria-current']).map(l=>l.dataset.gameServer)};
}
test('inline first-paint labels resolve explicit server before deferred scripts',()=>{
 for(const [id,label]of [['global-hmt','港澳台'],['global-en','EN'],['global-kr','韩服']])assert.deepEqual(render('https://test/global/zh-CN/?server='+id),{label,selected:[id]});
 assert.equal(render('https://test/global/en/?server=global-kr',null,'en').label,'Korea');
});
test('saved identities survive document navigation without leaking between editions',()=>{
 assert.equal(render('https://test/global/zh-CN/','global-hmt').label,'港澳台');
 assert.equal(render('https://test/jp/zh-CN/','global-hmt').label,'日服');
 assert.equal(render('https://test/global/zh-CN/?server=global-kr','global-hmt').label,'韩服');
 assert.equal(render('https://test/global/zh-CN/?server=jp','global-hmt').selected.length,0);
 assert.equal(render('https://test/global/zh-CN/',null,'zh-CN',true).selected.length,0);
});
