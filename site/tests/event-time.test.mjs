import test from 'node:test';
import assert from 'node:assert/strict';
import {eventTimestamp,eventCountdown} from '../src/lib/event-time.mjs';
import {releaseTimestamp} from '../src/lib/recent-releases.mjs';
test('Global event directories use the same UTC+8 clock as home events',()=>{
 const value='2026/09/30 18:00:00';
 const start=eventTimestamp(value,'global');
 assert.equal(start,Date.parse('2026-09-30T10:00:00Z'));
 assert.equal(start,releaseTimestamp(value,'global'));
 assert.equal(eventCountdown(start,eventTimestamp('2026/10/08 23:59:59','global'),start).state,'active');
 assert.equal(eventTimestamp(value,'jp'),Date.parse('2026-09-30T09:00:00Z'));
});
test('explicit time zones win and invalid dates remain unavailable',()=>{
 assert.equal(eventTimestamp('2026/09/30 18:00:00','global','UTC'),Date.parse('2026-09-30T18:00:00Z'));
 assert.equal(eventTimestamp('2026/09/30 18:00:00','jp','Asia/Taipei'),Date.parse('2026-09-30T10:00:00Z'));
 assert.equal(eventTimestamp('2026-09-30T18:00:00+08:00','jp'),Date.parse('2026-09-30T10:00:00Z'));
 for(const value of [null,'','unknown','2026/02/30 00:00:00'])assert.equal(eventTimestamp(value,'global'),null);
 assert.equal(eventTimestamp('2026/09/30 18:00:00','global','unknown'),null);
});
