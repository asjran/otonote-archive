import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { transitionPreviewHref } from '../src/lib/transition-preview.mjs';

const base = 'https://example.test/global/zh-CN/music/?q=test';
test('preview navigation preserves region, filters and hash while carrying the selected mode', () => {
  assert.equal(transitionPreviewHref('../cards/?rarity=SSR#results', { mode: 'stage', slow: true }, base),
    '/global/zh-CN/cards/?rarity=SSR&transition=stage&transition-speed=slow#results');
});
test('changing effect replaces previous parameters and normal speed removes the slow flag', () => {
  assert.equal(transitionPreviewHref('/catalog/?transition=stage&transition-speed=slow', { mode: 'book' }, base), '/catalog/?transition=book');
});
test('hashes, external destinations, media and unsupported modes are left alone', () => {
  for (const href of ['#main-content', 'https://other.test/music/', 'mailto:test@example.test', '/media/song.mp3', '/art/card.png', '']) {
    assert.equal(transitionPreviewHref(href, { mode: 'beat' }, base), href);
  }
  assert.equal(transitionPreviewHref('/music/', { mode: 'unknown' }, base), '/music/');
});
test('preview selection is available before first render and ordinary URLs keep the selected stage default', () => {
  const layout = readFileSync(new URL('../src/layouts/BaseLayout.astro', import.meta.url), 'utf8');
  const script = layout.match(/<script is:inline data-transition-preview-init>([\s\S]*?)<\/script>/);
  assert.ok(script);
  assert.ok(layout.indexOf(script[0]) < layout.indexOf('</head>'));
  const defaultMode = layout.match(/<html\b[^>]*data-page-transition="([^"]+)"/)?.[1];
  assert.equal(defaultMode, 'stage');
  for (const mode of ['stage', 'book', 'beat', 'fade', 'unknown', '']) {
    const dataset = { pageTransition: defaultMode };
    vm.runInNewContext(script[1], {
      URLSearchParams,
      document: { documentElement: { dataset } },
      window: { location: { search: `?transition=${mode}&transition-speed=slow` } }
    });
    if (['unknown', ''].includes(mode)) assert.deepEqual(dataset, { pageTransition: 'stage' });
    else assert.deepEqual(dataset, { transitionPreview: 'true', pageTransition: mode, transitionSpeed: 'slow' });
  }
});
