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

import {toolNavigationHref} from '../src/lib/tool-route.mjs';
import {createTeamDraft, parseTeamDraftSearch} from '../src/lib/team-draft.mjs';

test('task tabs carry large team settings in a fragment, keeping the HTTP request small', () => {
  const draft=createTeamDraft({slots:[{memberCardId:'member-card-1',supportCardId:'support-card-1'}],selectedSongId:'music-1',selectedDifficulty:'expert',modifiers:{performanceScenario:{note:'a'.repeat(16000)},growth:{'member-card-1':{level:50},unused:{level:99}}}});
  for(const region of ['global','jp'])for(const locale of ['zh-CN','en']) {
    const current=new URL(`https://example.test/${region}/${locale}/tools/deck-builder/?server=${region==='jp'?'jp':'global-hmt'}`);
    const target=new URL(toolNavigationHref('/tools/song-calculator/',draft,current),current);
    assert.equal(target.pathname,`/${region}/${locale}/tools/song-calculator/`);
    assert.equal(target.search,current.search);
    assert.ok(target.pathname.length+target.search.length<150);
    assert.ok(target.hash.startsWith('#team-draft='));
    const restored=parseTeamDraftSearch(target.search,{},target.hash).draft;
    assert.deepEqual(restored.slots,draft.slots);
    assert.equal(restored.selectedSongId,'music-1');
    assert.equal(restored.selectedDifficulty,'expert');
    assert.deepEqual(restored.modifiers.performanceScenario,draft.modifiers.performanceScenario);
    assert.deepEqual(restored.modifiers.growth,{'member-card-1':{level:50}});
  }
});
test('explicit query draft fields take precedence and unrelated fragments are ignored',()=>{
  assert.equal(parseTeamDraftSearch('?song=music-2',{},'#team-draft='+encodeURIComponent('?song=music-1')).draft.selectedSongId,'music-2');
  assert.equal(parseTeamDraftSearch('',{},'#song=music-1').draft.selectedSongId,null);
});
