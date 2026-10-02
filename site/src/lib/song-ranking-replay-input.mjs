/** Immutable chart/rules records from the same edition snapshot as the row.
 * The worker never guesses a chart URL from an ID or mixes current releases. */
export function songRankingReplaySource(manifest, row, locale, releaseId) {
  if (!releaseId || manifest?.contentReleaseId !== releaseId || !['global', 'jp'].includes(row.sourceEdition)
    || (manifest.region ?? manifest.contentReleaseId?.split('-')[0]) !== row.sourceEdition
    || !/^\/content\/releases\/[a-f0-9]{24}\/$/.test(manifest.root)) return null;
  const files = manifest.locales?.[locale]?.files;
  const record = key => {
    const value = files?.[key];
    if (!value || typeof value.path !== 'string' || value.path.startsWith('/') || value.path.split('/').some(part => !part || part === '..')
      || /[%?#\\]/.test(value.path) || !/^[a-f0-9]{64}$/.test(value.sha256)) return null;
    return { url: manifest.root + value.path, sha256: value.sha256 };
  };
  const chart = record(`projection/music-charts/${row.sourceId}.json`);
  const rules = record('supplemental/formal-scoring-rules.json');
  return chart && rules ? { releaseId, chart, rules } : null;
}
