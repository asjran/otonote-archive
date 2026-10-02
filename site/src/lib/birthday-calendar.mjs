import { releaseTimestamp } from './recent-releases.mjs';

const DAY = 86_400_000;
const OFFSET = 8 * 3_600_000;
const birthdayText = /生日|birthday|バースデー|誕生日/i;

/** The homepage calendar follows the Global server's UTC+8 calendar day. */
export function calendarDate(now = Date.now()) {
  return new Date(now + OFFSET).toISOString().slice(0, 10);
}

export function nextBirthday(month, day, now = Date.now()) {
  if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1) return null;
  const leapDate = new Date(Date.UTC(2000, month - 1, day));
  if (leapDate.getUTCMonth() !== month - 1 || leapDate.getUTCDate() !== day) return null;
  const today = Math.floor((now + OFFSET) / DAY) * DAY;
  const year = new Date(today).getUTCFullYear();
  // A February 29 birthday uses its next actual calendar occurrence.
  for (let nextYear = year; nextYear <= year + 8; nextYear++) {
    const date = new Date(Date.UTC(nextYear, month - 1, day));
    if (date.getUTCMonth() !== month - 1 || date.getTime() < today) continue;
    return { date: date.toISOString().slice(0, 10), days: (date.getTime() - today) / DAY };
  }
  return null;
}

/** @template {{birthday: {month: number, day: number}}} T @param {T[]} characters */
export function upcomingBirthdays(characters, now = Date.now()) {
  return characters.flatMap(character => {
    const next = nextBirthday(character.birthday.month, character.birthday.day, now);
    return next ? [{ character, ...next }] : [];
  }).sort((a, b) => a.days - b.days);
}

export function birthdayCountdown(days, en = false) {
  if (days === 0) return en ? 'Happy birthday!' : '生日快乐';
  if (days === 1) return en ? 'Tomorrow' : '明天生日';
  return en ? `In ${days} days` : `还有 ${days} 天`;
}

export function birthdayProximity(days) {
  return days === 0 ? 'today' : days > 0 && days <= 7 ? 'soon' : 'later';
}

/** Match birthday pools through UP member cards, never the entire prize list. */
export function birthdayContent(characterId, memberCards, pools) {
  const characterCards = memberCards.filter(card => card.characterId === characterId);
  const memberIds = new Set(characterCards.map(card => card.masterId));
  const birthdayPools = pools.filter(pool => pool.categories?.includes('birthday')
    && pool.pickupMemberCardIds?.some(id => memberIds.has(id)));
  const pickupIds = new Set(birthdayPools.flatMap(pool => pool.pickupMemberCardIds));
  const cards = characterCards.filter(card => pickupIds.has(card.masterId)
    || birthdayText.test([card.subtitle, card.displayName, ...Object.values(card.localizedText ?? {})].join(' ')))
    .sort((a, b) => (releaseTimestamp(b.startAt) ?? 0) - (releaseTimestamp(a.startAt) ?? 0));
  return { cards, pools: birthdayPools };
}

export function birthdayPoolState(pool, now = Date.now()) {
  const start = releaseTimestamp(pool.startAt);
  const end = releaseTimestamp(pool.endAt);
  if (start !== null && end !== null && end < start) return 'unknown';
  if (end !== null && now > end) return 'ended';
  if (start !== null && now < start) return 'upcoming';
  if (start !== null && end !== null && now >= start && now <= end) return 'active';
  return 'unknown';
}

export function preferredBirthdayPool(pools, now = Date.now()) {
  const priority = { active: 0, upcoming: 1, unknown: 2, ended: 3 };
  return [...pools].sort((a, b) => {
    const stateA = birthdayPoolState(a, now);
    const stateB = birthdayPoolState(b, now);
    const order = priority[stateA] - priority[stateB];
    if (order) return order;
    const dateA = releaseTimestamp(a.startAt) ?? 0;
    const dateB = releaseTimestamp(b.startAt) ?? 0;
    return stateA === 'upcoming' ? dateA - dateB : dateB - dateA;
  })[0];
}

/** Keep the card shortcut aligned with the selected pool when multiple years exist. */
export function preferredBirthdayCard(cards, pool) {
  return cards.find(card => pool?.pickupMemberCardIds?.includes(card.masterId)) ?? cards[0];
}

export function birthdayPoolLabel(pool, now = Date.now(), en = false) {
  const state = birthdayPoolState(pool, now);
  const labels = en
    ? { active: 'Birthday pool · Live', upcoming: 'Birthday pool · Soon', ended: 'Birthday pool · Ended', unknown: 'Birthday pool · Schedule unconfirmed' }
    : { active: '生日招募 · 进行中', upcoming: '生日招募 · 待开放', ended: '生日招募 · 已结束', unknown: '生日招募 · 时间待确认' };
  return labels[state];
}
