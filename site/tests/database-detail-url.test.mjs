import test from 'node:test';
import assert from 'node:assert/strict';
let Dialog;
globalThis.HTMLElement=class {};
globalThis.customElements={get:()=>undefined,define:(_name,type)=>{Dialog=type;}};
await import('../src/lib/database-detail-dialog.mjs');

for(const base of ['/jp/en/database/details/items/?server=jp','/global/zh-CN/database/details/items/?server=global-hmt','/global/en/database/details/items/']) {
  test(`detail request preserves the selected server: ${base}`,async()=>{
    globalThis.location={href:'https://example.test'+base,hash:'#detail=item-1'};
    let requested;
    globalThis[Symbol.for('ournotes.page-resource.v1')]=async url=>{
      requested=new URL(url,location.href);
      return new Response('',{status:404});
    };
    const dialog=Object.create(Dialog.prototype);
    Object.assign(dialog,{dataset:{detailBase:base},cache:new Map(),content:{replaceChildren(){}},dialog:{open:true,removeAttribute(){}},querySelector:()=>({hidden:false})});
    await dialog.sync();
    const expected=new URL(base,location.href);
    assert.equal(requested.pathname,expected.pathname+'item-1/');
    assert.equal(requested.search,expected.search);
    assert.equal(requested.hash,'');
  });
}
