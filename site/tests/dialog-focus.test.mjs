import test from 'node:test';
import assert from 'node:assert/strict';
import {containModalFocus} from '../src/lib/dialog-focus.mjs';
function fixture(){
 const doc={activeElement:null};
 const field=(extra={})=>({tabIndex:0,getClientRects:()=>[{}],focus(){doc.activeElement=this;},...extra});
 const first=field(),last=field(),disabled=field({disabled:true}),hidden=field({getClientRects:()=>[]});
 const dialog={open:true,modal:true,nested:false,ownerDocument:doc,matches(){return this.modal;},querySelector(){return this.nested;},querySelectorAll:()=>[first,disabled,hidden,last],contains:el=>[first,last].includes(el),focus(){doc.activeElement=this;}};
 function tab(shiftKey=false){const event={key:'Tab',shiftKey,prevented:false,preventDefault(){this.prevented=true;}};containModalFocus(dialog,event);return event;}
 return {doc,first,last,dialog,tab};
}
test('modal Tab and Shift+Tab wrap visible enabled controls',()=>{
 const f=fixture();f.last.focus();assert.equal(f.tab().prevented,true);assert.equal(f.doc.activeElement,f.first);
 assert.equal(f.tab(true).prevented,true);assert.equal(f.doc.activeElement,f.last);
 f.first.focus();assert.equal(f.tab().prevented,false);
});
test('focus outside a modal returns inside; sidebars and parents of open children do not intercept',()=>{
 const f=fixture();f.doc.activeElement={};f.tab();assert.equal(f.doc.activeElement,f.first);
 f.dialog.modal=false;f.last.focus();assert.equal(f.tab().prevented,false);
 f.dialog.modal=true;f.dialog.nested=true;assert.equal(f.tab().prevented,false);
});
test('empty modal handles Tab without moving focus to the page',()=>{
 const f=fixture();f.dialog.querySelectorAll=()=>[];assert.equal(f.tab().prevented,true);assert.equal(f.doc.activeElement,f.dialog);
});
