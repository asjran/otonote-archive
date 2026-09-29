import test from 'node:test';
import assert from 'node:assert/strict';
import { createTracker, OPT_OUT_KEY } from '../src/lib/site-analytics.mjs';

function setup(overrides={}) {
  const values=new Map(),sent=[];let count=0,day=new Date('2026-09-28T01:00:00Z');
  const storage={getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};
  const tracker=createTracker({site:'site',location:{origin:'https://example.com',hostname:'example.com',pathname:'/music/'},
    navigator:{sendBeacon:(url,body)=>{sent.push({url,body});return true;}},storage,
    uuid:()=>String(++count).padStart(32,'0'),now:()=>day,referrer:'https://search.example/results?secret=private',...overrides});
  return{tracker,sent,values,advance:value=>day=new Date(value)};
}
test('page analytics excludes URL queries and sends only source hostname',async()=>{
  const {tracker,sent}=setup();tracker.send('page_view');
  const payload=JSON.parse(await sent[0].body.text());assert.equal(payload.path,'/music/');assert.equal(payload.referrer,'search.example');assert.ok(payload.visitor);assert.equal(sent[0].url,'/_stats/events');
});
test('daily visitor rotates, opt-out clears identity and blocks further sends',async()=>{
  const t=setup();t.tracker.send('page_view');const first=JSON.parse(await t.sent[0].body.text()).visitor;
  t.advance('2026-09-28T17:00:00Z');t.tracker.send('page_view');assert.notEqual(JSON.parse(await t.sent[1].body.text()).visitor,first);
  t.tracker.setDisabled(true);assert.equal(t.values.get(OPT_OUT_KEY),'1');assert.equal(t.values.has('ournotes.analytics.visitor.site'),false);assert.equal(t.tracker.send('page_view'),false);assert.equal(t.sent.length,2);
});
test('DNT, external endpoints and failed storage do not break page actions',()=>{
  const a=setup({navigator:{doNotTrack:'1',sendBeacon:()=>{throw Error('must not send');}}});assert.equal(a.tracker.send('page_view'),false);
  assert.equal(setup({endpoint:'https://evil.test/collect'}).tracker.send('page_view'),false);
  const b=setup({storage:{getItem(){throw Error('denied');},setItem(){throw Error('denied');}}});assert.doesNotThrow(()=>b.tracker.send('page_view'));
  b.tracker.setDisabled(true);assert.equal(b.tracker.disabled(),true);assert.equal(b.tracker.send('page_view'),false);
  const c=setup({navigator:{sendBeacon(){throw Error('offline');}}});assert.equal(c.tracker.send('page_view'),false);
});
