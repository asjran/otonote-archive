import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { navigationRoutes } from '../src/lib/navigation.mjs';
import { createSupportCardDetailModel } from '../src/lib/support-card-detail-model.mjs';
const source=path=>readFile(new URL(path,import.meta.url),'utf8');
test('paused lab is absent from navigation and contextual entry points',async()=>{
  assert.ok(!navigationRoutes().includes('/tools/gekisou-lab/'));
  for(const path of ['../src/pages/tools/index.astro','../src/pages/music/[id].astro','../src/components/card-details/CardDetailArchive.astro','../src/pages/database/skills/[id].astro'])
    assert.doesNotMatch(await source(path),/\/tools\/gekisou-lab\//);
  const model=createSupportCardDetailModel({cardId:1,skillSummaries:[]});
  assert.ok(model.imageSidebarTopics.every(topic=>!topic.logicalPath?.includes('gekisou-lab')));
});
test('old lab URL shows a paused notice without loading the interactive laboratory',async()=>{
  const page=await source('../src/pages/tools/gekisou-lab/index.astro');
  assert.match(page,/暂停开放/);assert.match(page,/\/tools\/deck-builder\//);
  assert.doesNotMatch(page,/GekisouBattleLab|gekisou-lab-workbench/);
});
