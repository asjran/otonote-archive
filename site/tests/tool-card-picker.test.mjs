import test from 'node:test';
import assert from 'node:assert/strict';
import {filterQuickCards} from '../src/lib/tool-card-picker.mjs';
const cards=[{id:'a',displayName:'高松灯｜闪耀舞台',attributeCode:1},{id:'b',displayName:'千早爱音｜闪耀舞台',attributeCode:2},{id:'c',displayName:'高松灯｜起点',attributeCode:2}];
test('card search intersects words, attribute and owned scope',()=>{
 assert.deepEqual(filterQuickCards(cards,{query:'高松灯 舞台',ownedOnly:true,owned:['a','c']}).map(c=>c.id),['a']);
 assert.deepEqual(filterQuickCards(cards,{query:'高松灯',attribute:'2'}).map(c=>c.id),['c']);
 assert.deepEqual(filterQuickCards(cards,{ownedOnly:true,owned:[]}),[]);
 assert.deepEqual(filterQuickCards(cards,{query:'不存在'}),[]);
 assert.equal(filterQuickCards(cards).length,3);
});
test('clearing one condition retains the others and never mutates card data',()=>{
 const before=structuredClone(cards);
 assert.deepEqual(filterQuickCards(cards,{query:'高松灯',ownedOnly:true,owned:['a']}).map(c=>c.id),['a']);
 assert.deepEqual(cards,before);
});
