import test from 'node:test';
import assert from 'node:assert/strict';
import { toolRoute } from '../src/lib/tool-route.mjs';

test('tool links retain server and language while leaving the shared draft intact', () => {
  const target = '/tools/song-calculator/?member=member-card-1&difficulty=expert';
  for (const region of ['jp', 'global']) {
    for (const locale of ['zh-CN', 'en', 'ja', 'zh-TW']) {
      assert.equal(toolRoute(target, `/${region}/${locale}/tools/deck-builder/`), `/${region}/${locale}${target}`);
    }
  }
  assert.equal(toolRoute(target, '/tools/deck-builder/'), target);
  assert.equal(toolRoute(target, '/global/english/tools/'), target);
});
