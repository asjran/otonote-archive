export function matchesBgm(track, query = '', category = 'all', availableOnly = false) {
  if (category !== 'all' && !track.categoryIds.includes(category)) return false;
  if (availableOnly && track.status !== 'available') return false;
  const haystack = `${track.title} ${track.cueName}`.normalize('NFKC').toLocaleLowerCase();
  return query.normalize('NFKC').trim().toLocaleLowerCase().split(/\s+/).every(term => haystack.includes(term));
}

export function formatBgmTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—';
  const whole = Math.floor(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

export function formatBgmSize(bytes) {
  return bytes < 1024 * 1024 ? `${Math.ceil(bytes / 1024)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
