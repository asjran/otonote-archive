export const SEARCH_TYPES = ["music", "character", "member_card", "support_card", "story", "item", "skill"];

export function normalizeSearchQuery(value) {
  return String(value ?? "").normalize("NFKC").trim().replace(/\s+/g, "").toLocaleLowerCase();
}

export function searchTerms(value) {
  return [...new Set(String(value ?? "").normalize("NFKC").trim().toLocaleLowerCase().split(/\s+/).filter(Boolean))].slice(0, 12);
}

function scoreEntry(entry, query, terms) {
  const title = normalizeSearchQuery(entry.title);
  const subtitle = normalizeSearchQuery(entry.subtitle);
  const searchable = normalizeSearchQuery(`${entry.id} ${entry.searchableText ?? ""}`);
  if (title === query) return 0;
  if (title.startsWith(query)) return 1;
  if (title.includes(query)) return 2;
  if (subtitle.includes(query)) return 3;
  if (searchable.includes(query)) return 4;
  // Every word must match, but words may occur in different fields and order.
  if (terms.every(term => [title, subtitle, searchable].some(field => field.includes(term)))) {
    return 5 + terms.filter(term => !title.includes(term)).length;
  }
  return null;
}

export function searchUnified(entries, { query = "", type = "all", limit = 24 } = {}) {
  const normalized = normalizeSearchQuery(query);
  const counts = Object.fromEntries(SEARCH_TYPES.map(kind => [kind, 0]));
  if (!normalized) return { matches: [], total: 0, counts, totalAll: 0 };
  const terms = searchTerms(query);
  const ranked = entries.map(entry => ({ entry, score: scoreEntry(entry, normalized, terms) }))
    .filter(result => result.score !== null)
    .sort((a, b) => a.score - b.score || a.entry.title.localeCompare(b.entry.title) || a.entry.id.localeCompare(b.entry.id));
  for (const { entry } of ranked) counts[entry.type] = (counts[entry.type] || 0) + 1;
  const selected = ranked.filter(({ entry }) => type === "all" || entry.type === type);
  return { matches: selected.slice(0, limit).map(({ entry }) => entry), total: selected.length, totalAll: ranked.length, counts };
}

export function filterUnifiedSearch(entries, options) {
  return searchUnified(entries, options).matches;
}

// Offsets refer to the original string, so full-width characters and whitespace
// are preserved. Consumers create text nodes and <mark>, never HTML strings.
export function highlightParts(value, query) {
  const text = String(value ?? "");
  let normalized = "";
  const positions = [];
  let offset = 0;
  for (const char of text) {
    const unit = normalizeSearchQuery(char);
    for (let i = 0; i < unit.length; i++) positions.push([offset, offset + char.length]);
    normalized += unit;
    offset += char.length;
  }
  const ranges = [];
  const terms = [...new Set([normalizeSearchQuery(query), ...searchTerms(query)])].filter(Boolean);
  for (const term of terms) {
    let start = normalized.indexOf(term);
    while (start !== -1) {
      ranges.push([positions[start][0], positions[start + term.length - 1][1]]);
      start = normalized.indexOf(term, start + term.length);
    }
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const range of ranges) {
    const last = merged.at(-1);
    if (last && range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push([...range]);
  }
  const parts = [];
  let end = 0;
  for (const [start, stop] of merged) {
    if (start > end) parts.push({ text: text.slice(end, start), match: false });
    parts.push({ text: text.slice(start, stop), match: true });
    end = stop;
  }
  if (end < text.length) parts.push({ text: text.slice(end), match: false });
  return parts;
}
