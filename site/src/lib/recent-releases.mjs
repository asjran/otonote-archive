/** Interpret a Master's wall clock in the selected resource edition. */
export function releaseTimestamp(value, region = 'global') {
  if (typeof value !== 'string') return null;
  const match = value.trim().match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [,year,month,day,hour,minute,second] = match;
  const iso = `${year}-${month.padStart(2,'0')}-${day.padStart(2,'0')}T${hour.padStart(2,'0')}:${minute}:${second}${region === 'jp' ? '+09:00' : '+08:00'}`;
  const timestamp = Date.parse(iso);
  return Number.isFinite(timestamp) ? timestamp : null;
}
/** @template {{startAt: string}} T @param {T[]} items @returns {T[]} */
export function recentReleases(items, now = Date.now(), limit = 6, {region = 'global', includeUpcoming = false} = {}) {
  return items.map((item,index)=>({item,index,time:releaseTimestamp(item.startAt, region)}))
    .filter(row=>row.time !== null && (includeUpcoming || row.time <= now))
    .sort((a,b)=>b.time-a.time || a.index-b.index).slice(0,limit).map(row=>row.item);
}
export function releaseDateLabel(value) { return value?.split(/[ T]/)[0]?.replaceAll('/','-') ?? ''; }
