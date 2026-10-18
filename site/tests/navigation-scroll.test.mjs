import assert from 'node:assert/strict';
import test from 'node:test';
import {restoreNavigationScroll, revealCurrentNavigation} from '../src/lib/navigation-scroll.mjs';

function fixture({stored = null, currentTop = 1000, hidden = false, blocked = false} = {}) {
  const listeners = {};
  const writes = [];
  const navigation = {
    scrollTop: 0,
    clientHeight: hidden ? 0 : 600,
    getBoundingClientRect: () => ({top:68, bottom:hidden ? 68 : 668}),
    querySelector: () => ({getBoundingClientRect: () => ({top:currentTop-navigation.scrollTop, bottom:currentTop+34-navigation.scrollTop})}),
    addEventListener: (name, fn) => {listeners[name] = fn;}
  };
  const storage = {getItem() {if(blocked)throw Error('blocked');return stored;}, setItem: (...args) => writes.push(args)};
  return {navigation, storage, listeners, writes};
}

test('a direct load reveals the selected tool inside the sidebar without scrolling the document', () => {
  const f=fixture();restoreNavigationScroll(f.navigation, f.storage);
  assert.ok(f.navigation.scrollTop >= 366);
});
test('a saved sidebar position is retained when the current link is already visible', () => {
  const f=fixture({stored:'700'});restoreNavigationScroll(f.navigation,f.storage);
  assert.equal(f.navigation.scrollTop,700);
  f.navigation.scrollTop=500;f.listeners.scroll();
  assert.equal(f.writes.at(-1)[1],'500');
});
test('saved scroll cannot hide a newly selected link above the viewport', () => {
  const f=fixture({stored:'700',currentTop:100});restoreNavigationScroll(f.navigation,f.storage);
  assert.ok(f.navigation.scrollTop <= 32);
});
test('blocked storage and a hidden mobile drawer stay usable', () => {
  const f=fixture({blocked:true});assert.doesNotThrow(()=>restoreNavigationScroll(f.navigation,f.storage));
  assert.ok(f.navigation.scrollTop>0);
  const m=fixture({hidden:true});restoreNavigationScroll(m.navigation,m.storage);
  assert.equal(m.navigation.scrollTop,0);
  m.navigation.clientHeight=600;m.navigation.getBoundingClientRect=()=>({top:68,bottom:668});
  revealCurrentNavigation(m.navigation);assert.ok(m.navigation.scrollTop>0);
});
