/** Master timestamps have no offset: use an explicit edition display convention. */
export function eventTimestamp(value, edition, timeZone = null) {
  if (!value) return null;
  if (/(?:Z|[+-]\d\d:\d\d)$/.test(value)) {
    const result = Date.parse(value);
    return Number.isFinite(result) ? result : null;
  }
  const zone = timeZone || ({jp:'Asia/Tokyo', global:'Asia/Taipei'})[edition];
  const offset = ({UTC:0, 'Asia/Tokyo':540, 'Asia/Taipei':480, 'Asia/Shanghai':480, 'Asia/Hong_Kong':480, 'Asia/Seoul':540})[zone] ?? null;
  const match = /^(\d{4})[/-](\d{1,2})[/-](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (offset == null || !match) return null;
  const [year, month, day, hour, minute, second = 0] = match.slice(1).map(value => Number(value ?? 0));
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59) return null;
  const local = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
  if (local.getUTCMonth() !== month - 1 || local.getUTCDate() !== day) return null;
  return local.getTime() - offset * 60000;
}
export function eventCountdown(start, end, now, en = false) {
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return {state:'unknown',label:en ? 'Schedule unavailable' : '时间待确认'};
  const state = now < start ? 'upcoming' : now <= end ? 'active' : 'ended';
  if (state === 'ended') return {state,label:en ? 'Ended' : '已结束'};
  const remaining = (state === 'upcoming' ? start : end) - now;
  const minutes = Math.ceil(remaining / 60000);
  const days = Math.floor(minutes / 1440), hours = Math.floor(minutes % 1440 / 60), mins = minutes % 60;
  const duration = days > 0 ? (en ? `${days}d ${hours}h` : `${days}天 ${hours}小时`) : hours > 0 ? (en ? `${hours}h ${mins}m` : `${hours}小时 ${mins}分`) : (en ? `${Math.max(1,mins)}m` : `${Math.max(1,mins)}分钟`);
  return {state,label:state === 'upcoming' ? (en ? `Starts in ${duration}` : `距开始 ${duration}`) : (en ? `${duration} remaining` : `剩余 ${duration}`)};
}
