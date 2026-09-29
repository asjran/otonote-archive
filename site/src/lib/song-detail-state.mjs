export const SONG_VIEWS = ['playback', 'analysis', 'rewards'];
export function songViewFromLocation(search, hash = '') {
  const requested = new URLSearchParams(search).get('view');
  if (SONG_VIEWS.includes(requested)) return requested;
  if (['#score-track', '#chart-analysis'].includes(hash)) return 'analysis';
  if (hash === '#track-rewards') return 'rewards';
  return null;
}
export function songDifficultyFromLocation(search, available) {
  const requested = new URLSearchParams(search).get('difficulty');
  return available.includes(requested) ? requested : available.includes('expert') ? 'expert' : available[0];
}
