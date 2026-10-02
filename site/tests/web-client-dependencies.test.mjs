import test from 'node:test';
import assert from 'node:assert/strict';
import {attachDataProfiles} from '../../tools/web_client_dependencies.mjs';

test('page inputs follow shared static imports, deduplicate profiles and exclude lazy players', () => {
  const manifest = {buildRoot:'/code', routes:[{module:'page.js'}, {module:'page2.js'}]};
  const edge = path => ({path, kind:'import-statement'});
  const outputs = {
    '/code/page.js':{inputs:{'content:projection/catalog.json':{}}, imports:[edge('/code/shared.js'), {path:'/code/player.js', kind:'dynamic-import'}]},
    '/code/page2.js':{inputs:{'content:projection/catalog.json':{}}, imports:[edge('/code/shared.js')]},
    '/code/shared.js':{inputs:{'/src/cards.ts':{}, 'content:projection/media-index.json':{}}, imports:[edge('/code/shared.js')]},
    '/code/player.js':{inputs:{'content:supplemental/models.json':{}}, imports:[]}
  };
  attachDataProfiles(manifest, {outputs}, new Map([['/src/cards.ts', ['@projection-data/database-shards/member-cards/*.json']]]));
  assert.equal(manifest.dataProfiles.length, 1);
  assert.deepEqual(manifest.dataProfiles[0], {files:['projection/catalog.json', 'projection/media-index.json'], groups:['@projection-data/database-shards/member-cards/*.json']});
  assert.equal(manifest.routes[0].dataProfile, manifest.routes[1].dataProfile);
  assert.equal(manifest.buildRoot, undefined);
});
