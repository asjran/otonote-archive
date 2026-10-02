import test from 'node:test';
import assert from 'node:assert/strict';
import { recentReleases,releaseTimestamp } from '../src/lib/recent-releases.mjs';
test('sorts both Master date formats and excludes future or missing dates',()=>{
 const items=[{id:'old',startAt:'2026/01/01 0:00:00'},{id:'future',startAt:'2026/09/27 15:00:00'},{id:'new',startAt:'2026-09-26 15:00:00'},{id:'unknown',startAt:''}];
 assert.deepEqual(recentReleases(items,Date.parse('2026-09-27T00:00:00+08:00')).map(i=>i.id),['new','old']);
 assert.equal(releaseTimestamp('2026/09/27 15:00:00'),Date.parse('2026-09-27T07:00:00Z'));
 assert.equal(items[0].id,'old');
});
test('keeps equal-time cards in supplied order without inventing a release order',()=>{
 const items=[{id:9,startAt:'2026-01-01 0:00:00'},{id:1,startAt:'2026/01/01 0:00:00'}];
 assert.deepEqual(recentReleases(items,Date.parse('2026-09-27'),1).map(i=>i.id),[9]);
});
test('homepage keeps newly collected JP cards before their scheduled opening',()=>{
 const items=[{id:51,startAt:'2026/09/25 18:00:00'},{id:61,startAt:'2026/09/30 18:00:00'},{id:62,startAt:'2026/09/30 18:00:00'},{id:63,startAt:'2026/09/30 18:00:00'}];
 assert.deepEqual(recentReleases(items,Date.parse('2026-09-30T02:30:00Z'),6,{region:'jp',includeUpcoming:true}).map(x=>x.id),[61,62,63,51]);
 assert.equal(releaseTimestamp('2026/09/30 18:00:00','jp'),Date.parse('2026-09-30T09:00:00Z'));
});
