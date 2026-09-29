import test from 'node:test';
import assert from 'node:assert/strict';
import { nextBirthday, upcomingBirthdays, calendarDate, birthdayCountdown, birthdayContent, birthdayPoolState, preferredBirthdayPool, preferredBirthdayCard, birthdayPoolLabel } from '../src/lib/birthday-calendar.mjs';

const at = value => Date.parse(value);
const character = (id, month, day) => ({ id, birthday: { month, day } });

test('UTC+8 midnight changes tomorrow into today, independent of the browser timezone', () => {
  const before = at('2026-10-03T15:59:59.999Z');
  const midnight = before + 1;
  assert.equal(calendarDate(before), '2026-10-03');
  assert.equal(calendarDate(midnight), '2026-10-04');
  assert.deepEqual(nextBirthday(10, 4, before), { date: '2026-10-04', days: 1 });
  assert.deepEqual(nextBirthday(10, 4, midnight), { date: '2026-10-04', days: 0 });
  assert.equal(nextBirthday(10, 4, at('2026-10-04T23:59:59+08:00')).days, 0);
  assert.equal(birthdayCountdown(0), '今天生日 · 生日快乐');
  assert.equal(birthdayCountdown(1, true), 'Tomorrow');
});

test('birthdays roll over annually and the next character moves into the lead', () => {
  const people = [character('oct4', 10, 4), character('oct24', 10, 24), character('nov4', 11, 4)];
  assert.deepEqual(upcomingBirthdays(people, at('2026-09-28T12:00:00+08:00')).map(row => row.days), [6, 26, 37]);
  assert.deepEqual(upcomingBirthdays(people, at('2026-10-05T00:00:00+08:00')).map(row => row.character.id), ['oct24', 'nov4', 'oct4']);
  assert.deepEqual(nextBirthday(1, 1, at('2026-12-31T12:00:00+08:00')), { date: '2027-01-01', days: 1 });
});

test('invalid dates are omitted and February 29 uses the next real leap day', () => {
  const now = at('2026-02-28T00:00:00+08:00');
  for (const [month, day] of [[0, 1], [13, 1], [4, 31], [2, 30], [1, 0], [1, 1.5]]) assert.equal(nextBirthday(month, day, now), null);
  assert.equal(nextBirthday(2, 29, now).date, '2028-02-29');
  assert.equal(nextBirthday(2, 29, at('2097-03-01T00:00:00+08:00')).date, '2104-02-29');
  assert.deepEqual(upcomingBirthdays([character('missing', 0, 0)], now), []);
});

test('same-day birthdays are all retained, and sorting does not mutate source data', () => {
  const people = [character('later', 12, 10), character('first', 10, 4), character('second', 10, 4)];
  assert.deepEqual(upcomingBirthdays(people, at('2026-10-04T00:00:00+08:00')).map(row => row.character.id), ['first', 'second', 'later']);
  assert.equal(people[0].id, 'later');
});

test('birthday links require explicit birthday copy or a birthday pool with the character in UP', () => {
  const cards = [
    { id: 'normal', characterId: 'a', masterId: 1, subtitle: 'An ordinary day' },
    { id: 'pickup', characterId: 'a', masterId: 2, subtitle: 'A special moment' },
    { id: 'named', characterId: 'a', masterId: 3, localizedText: { ja: 'バースデー' } },
    { id: 'other', characterId: 'b', masterId: 4, subtitle: 'Happy Birthday' }
  ];
  const pools = [
    { id: 10, categories: ['birthday'], pickupMemberCardIds: [2] },
    { id: 11, categories: ['birthday'], pickupMemberCardIds: [4], prizes: [{ resourceId: 1 }] },
    { id: 12, categories: ['event'], pickupMemberCardIds: [1] }
  ];
  const content = birthdayContent('a', cards, pools);
  assert.deepEqual(content.cards.map(card => card.id), ['pickup', 'named']);
  assert.deepEqual(content.pools.map(pool => pool.id), [10]);
  assert.deepEqual(birthdayContent('missing', cards, pools), { cards: [], pools: [] });
});

test('ordinary character cards never become birthday cards merely because a birthday is nearby', () => {
  assert.deepEqual(birthdayContent('a', [{ characterId: 'a', masterId: 1, subtitle: 'Normal SSR' }], []), { cards: [], pools: [] });
});

test('a future birthday card does not displace the card in the currently selected birthday pool', () => {
  const cards = [{ masterId: 2027 }, { masterId: 2026 }, { masterId: 2025 }];
  assert.equal(preferredBirthdayCard(cards, { pickupMemberCardIds: [2026] }).masterId, 2026);
  assert.equal(preferredBirthdayCard(cards, undefined).masterId, 2027);
  assert.equal(preferredBirthdayCard([], undefined), undefined);
});

test('pool windows use UTC+8 with inclusive boundaries and do not claim live for unknown dates', () => {
  const pool = { startAt: '2026/10/04 00:00:00', endAt: '2026/10/05 23:59:59' };
  assert.equal(birthdayPoolState(pool, at('2026-10-03T15:59:59Z')), 'upcoming');
  assert.equal(birthdayPoolState(pool, at('2026-10-03T16:00:00Z')), 'active');
  assert.equal(birthdayPoolState(pool, at('2026-10-05T15:59:59Z')), 'active');
  assert.equal(birthdayPoolState(pool, at('2026-10-05T16:00:00Z')), 'ended');
  assert.equal(birthdayPoolState({ startAt: pool.startAt, endAt: null }, at('2026-10-04T12:00:00Z')), 'unknown');
  assert.equal(birthdayPoolState({ startAt: pool.endAt, endAt: pool.startAt }), 'unknown');
  assert.match(birthdayPoolLabel(pool, at('2026-11-01T00:00:00Z')), /已结束/);
});

test('prefer a live birthday pool, then the soonest upcoming pool, then the latest archive', () => {
  const pools = [
    { id: 'old', startAt: '2025/10/04 00:00:00', endAt: '2025/10/05 23:59:59' },
    { id: 'future', startAt: '2027/10/04 00:00:00', endAt: '2027/10/05 23:59:59' },
    { id: 'current', startAt: '2026/10/04 00:00:00', endAt: '2026/10/05 23:59:59' }
  ];
  assert.equal(preferredBirthdayPool(pools, at('2026-09-28T00:00:00Z')).id, 'current');
  assert.equal(preferredBirthdayPool(pools, at('2026-10-04T00:00:00Z')).id, 'current');
  assert.equal(preferredBirthdayPool(pools, at('2026-10-06T00:00:00Z')).id, 'future');
  assert.equal(preferredBirthdayPool(pools, at('2028-01-01T00:00:00Z')).id, 'future');
  assert.equal(preferredBirthdayPool([], Date.now()), undefined);
});
