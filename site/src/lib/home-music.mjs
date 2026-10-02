import { releaseTimestamp } from './recent-releases.mjs';

/**
 * Derive homepage dates from the selected edition's validated events, preserving Master startAt.
 * @template {{masterId: number, startAt: string}} T
 * @param {T[]} tracks
 * @param {Array<{mode: string, schedule: {startAt: string|null, endAt: string|null}, challengeSongs: Array<{musicId: number, startAt: string|null, endAt: string|null}>}>} events
 * @param {string} region
 */
export function homeMusic(tracks, events, region, now = Date.now()) {
  /** @type {Map<number, Array<{start: number, end: number|null, startAt: string}>>} */
  const challenges = new Map();
  for (const event of events) {
    if (event.mode !== 'challenge_live') continue;
    const eventStart = releaseTimestamp(event.schedule.startAt, region);
    const eventEnd = releaseTimestamp(event.schedule.endAt, region);
    if (eventStart === null) continue;
    for (const song of event.challengeSongs) {
      const songStart = releaseTimestamp(song.startAt, region);
      const songEnd = releaseTimestamp(song.endAt, region);
      const start = Math.max(eventStart, songStart ?? eventStart);
      const ends = [eventEnd, songEnd].filter(value => value !== null);
      const end = ends.length ? Math.min(...ends) : null;
      if (end !== null && end <= start) continue;
      const periods = challenges.get(song.musicId) ?? [];
      periods.push({ start, end, startAt: songStart !== null && songStart > eventStart ? song.startAt : event.schedule.startAt });
      challenges.set(song.musicId, periods);
    }
  }
  const rows = tracks.map(track => {
    const freeLiveStart = releaseTimestamp(track.startAt, region);
    const challengePeriods = (challenges.get(track.masterId) ?? []).sort((a, b) => a.start - b.start);
    const first = challengePeriods[0];
    const challengeDebut = Boolean(first && (freeLiveStart === null || first.start < freeLiveStart));
    return {
      track, freeLiveStart, challengePeriods, challengeDebut,
      addedAt: challengeDebut ? first.startAt : track.startAt,
      addedStart: challengeDebut ? first.start : freeLiveStart
    };
  }).filter(row => row.addedStart !== null);
  return {
    recent: rows.filter(row => row.addedStart <= now).sort((a, b) => b.addedStart - a.addedStart).slice(0, 8),
    upcoming: rows.filter(row => row.addedStart > now).sort((a, b) => a.addedStart - b.addedStart).slice(0, 3)
  };
}

/** A historical debut remains added even between challenge access and free live opening. */
export function challengeSongLabel({ freeLiveStart, challengePeriods }, now = Date.now(), en = false) {
  if (freeLiveStart !== null && now >= freeLiveStart) return en ? 'Challenge debut' : '挑战演出先行';
  if (challengePeriods.some(period => period.start <= now && period.end !== null && now < period.end)) {
    return en ? 'Challenge Live only' : '挑战演出限定';
  }
  if (challengePeriods.length && challengePeriods.every(period => period.end !== null && period.end <= now)) {
    return en ? 'Challenge Live ended' : '挑战演出已结束';
  }
  return en ? 'Challenge debut' : '挑战演出先行';
}
