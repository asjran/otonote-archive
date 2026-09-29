import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import postcss from 'postcss';

const layout = readFileSync(new URL('../src/layouts/BaseLayout.astro', import.meta.url), 'utf8');
const css = postcss.parse(readFileSync(new URL('../src/styles/page-transitions.css', import.meta.url), 'utf8'));

function transitionLifecycle({ motion = 'on', reduced = false } = {}) {
  const script = layout.match(/<script is:inline data-page-transition-init>([\s\S]*?)<\/script>/);
  assert.ok(script, 'register lifecycle listeners before the destination can paint');
  assert.ok(layout.indexOf(script[0]) < layout.indexOf('</head>'));
  const listeners = new Map();
  const dataset = { motion };
  let skips = 0;
  vm.runInNewContext(script[1], {
    document: { documentElement: { dataset } },
    window: {
      matchMedia: () => ({ matches: reduced }),
      addEventListener: (type, listener) => listeners.set(type, listener)
    }
  });
  return {
    dataset,
    get skips() { return skips; },
    fire(type, supported = true) {
      listeners.get(type)({ type, viewTransition: supported ? { skipTransition() { skips++; } } : null });
    }
  };
}

test('normal navigation suppresses duplicate arrival only in the incoming document', () => {
  const state = transitionLifecycle();
  state.fire('pageswap');
  assert.equal(state.dataset.navigationEntry, undefined);
  state.fire('pagereveal');
  assert.equal(state.dataset.navigationEntry, 'true');
  assert.equal(state.skips, 0);
  // Back/forward can reveal the same document again; the marker stays stable.
  state.fire('pagereveal');
  assert.equal(state.dataset.navigationEntry, 'true');
});

for (const settings of [{ motion: 'off' }, { reduced: true }]) {
  test(`motion preference skips both outgoing and incoming transitions: ${JSON.stringify(settings)}`, () => {
    const state = transitionLifecycle(settings);
    state.fire('pageswap');
    state.fire('pagereveal');
    assert.equal(state.skips, 2);
    assert.equal(state.dataset.navigationEntry, undefined);
  });
}

test('initial loads and unsupported browsers preserve normal entry behavior', () => {
  const state = transitionLifecycle();
  state.fire('pagereveal', false);
  state.fire('pageswap', false);
  assert.equal(state.skips, 0);
  assert.equal(state.dataset.navigationEntry, undefined);
});

test('old content remains opaque throughout the handoff, avoiding a blank middle frame', () => {
  const declarations = new Map();
  css.walkRules('::view-transition-old(root)', rule => {
    rule.walkDecls(decl => declarations.set(decl.prop, decl.value));
  });
  assert.equal(declarations.get('animation'), 'none');
  assert.equal(declarations.get('opacity'), '1');
  const interactionCss = readFileSync(new URL('../src/styles/interaction-motion.css', import.meta.url), 'utf8');
  assert.doesNotMatch(interactionCss, /animation:\s*motion-content/);
});

test('native navigation is only opted in when motion is allowed', () => {
  const navigation = [];
  css.walkAtRules('view-transition', rule => {
    navigation.push([rule.parent.params, rule.nodes.find(node => node.prop === 'navigation').value]);
  });
  assert.deepEqual(navigation, [
    ['(prefers-reduced-motion: no-preference)', 'auto'],
    ['(prefers-reduced-motion: reduce)', 'none']
  ]);
});
