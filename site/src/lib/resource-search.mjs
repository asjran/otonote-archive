/** Reuse each library's existing search without copying its records. */
export function resourceSearchUrl(href, query) {
  const url = new URL(href);
  const value = String(query ?? '').trim();
  if (value) url.searchParams.set('q', value);
  else url.searchParams.delete('q');
  return url;
}
