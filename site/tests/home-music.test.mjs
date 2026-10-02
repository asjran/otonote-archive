import test from 'node:test';
import assert from 'node:assert/strict';
import { homeMusic, challengeSongLabel } from '../src/lib/home-music.mjs';

const song = { id: 'music-100109', masterId: 100109, title: '夢我夢中', startAt: '2026/10/08 21:00:00' };
const oldSong = { id: 'music-100056', masterId: 100056, startAt: '2026/01/01 0:00:00' };
const event = {
  mode: 'challenge_live',
  schedule: { startAt: '2026/09/30 18:00:00', endAt: '2026/10/08 20:59:59' },
  challengeSongs: [{ musicId: 100109, startAt: null, endAt: null }, { musicId: 100056, startAt: null, endAt: null }]
};
const at = value => Date.parse(value + '+09:00');
const during = at('2026-10-02T12:00:00');

test('a challenge debut is already added before its free live opening, without changing the source date', () => {
  const { recent, upcoming } = homeMusic([oldSong, song], [event], 'jp', during);
  assert.deepEqual(recent.map(row => row.track.id), [song.id, oldSong.id]);
  assert.equal(recent[0].addedAt, event.schedule.startAt);
  assert.equal(recent[0].addedStart, at('2026-09-30T18:00:00'));
  assert.equal(recent[0].freeLiveStart, at('2026-10-08T21:00:00'));
  assert.equal(challengeSongLabel(recent[0], during), '挑战演出限定');
  assert.equal(challengeSongLabel(recent[0], during, true), 'Challenge Live only');
  assert.equal(recent[1].challengeDebut, false);
  assert.deepEqual(upcoming, []);
  assert.equal(song.startAt, '2026/10/08 21:00:00');
});

test('upcoming challenge songs enter the recent list at the exact event opening', () => {
  const opening = at('2026-09-30T18:00:00');
  assert.equal(homeMusic([song], [event], 'jp', opening - 1).recent.length, 0);
  assert.equal(homeMusic([song], [event], 'jp', opening - 1).upcoming[0].addedAt, event.schedule.startAt);
  assert.equal(homeMusic([song], [event], 'jp', opening).recent.length, 1);
});

test('expired challenge access stays added and changes its label when free live opens', () => {
  const earlyEnd = { ...event, schedule: { ...event.schedule, endAt: '2026/10/07 20:00:00' } };
  const ended = at('2026-10-07T20:00:00');
  const row = homeMusic([song], [earlyEnd], 'jp', ended).recent[0];
  assert.equal(challengeSongLabel(row, ended - 1), '挑战演出限定');
  assert.equal(challengeSongLabel(row, ended), '挑战演出已结束');
  assert.equal(challengeSongLabel(row, at('2026-10-08T21:00:00')), '挑战演出先行');
  assert.equal(homeMusic([song], [event], 'jp', at('2026-10-09T00:00:00')).recent[0].addedAt, event.schedule.startAt);
});

test('individual challenge windows are bounded by the event schedule', () => {
  const limited = { ...event, challengeSongs: [{ musicId: 100109, startAt: '2026/10/02 18:00:00', endAt: '2026/10/04 18:00:00' }] };
  assert.equal(homeMusic([song], [limited], 'jp', during).recent.length, 0);
  const row = homeMusic([song], [limited], 'jp', at('2026-10-03T12:00:00')).recent[0];
  assert.equal(row.addedAt, '2026/10/02 18:00:00');
  assert.equal(challengeSongLabel(row, at('2026-10-04T18:00:00')), '挑战演出已结束');
  const wider = { ...event, challengeSongs: [{ musicId: 100109, startAt: '2026/09/29 18:00:00', endAt: '2026/10/09 18:00:00' }] };
  assert.equal(homeMusic([song], [wider], 'jp', during).recent[0].addedAt, event.schedule.startAt);
});

test('repeated events preserve the first debut and recognize later active windows', () => {
  const first = { ...event, schedule: { startAt: '2026/09/28 18:00:00', endAt: '2026/09/29 18:00:00' } };
  const row = homeMusic([song], [event, first], 'jp', during).recent[0];
  assert.equal(row.addedAt, first.schedule.startAt);
  assert.equal(challengeSongLabel(row, during), '挑战演出限定');
});

test('unrelated, invalid, and non-challenge events do not release a song early', () => {
  const invalidEvents = [
    { ...event, mode: 'other' },
    { ...event, challengeSongs: [{ musicId: 1, startAt: null, endAt: null }] },
    { ...event, schedule: { startAt: '', endAt: null } },
    { ...event, schedule: { startAt: '2026/10/02 18:00:00', endAt: '2026/10/01 18:00:00' } }
  ];
  const { recent, upcoming } = homeMusic([song], invalidEvents, 'jp', during);
  assert.equal(recent.length, 0);
  assert.equal(upcoming[0].addedAt, song.startAt);
  assert.equal(upcoming[0].challengeDebut, false);
});

test('ordinary songs retain ordering, regional time zones, and list limits', () => {
  const songs = Array.from({ length: 12 }, (_, i) => ({ masterId: i, startAt: `2026/10/${String(i + 1).padStart(2, '0')} 18:00:00` }));
  const now = at('2026-10-08T18:00:00');
  const jp = homeMusic(songs, [], 'jp', now);
  assert.equal(jp.recent.length, 8);
  assert.deepEqual(jp.upcoming.map(row => row.track.masterId), [8, 9, 10]);
  assert.equal(homeMusic(songs, [], 'global', now).recent.length, 7);
  assert.deepEqual(homeMusic([{ masterId: 1, startAt: '' }], [], 'jp', now), { recent: [], upcoming: [] });
});
