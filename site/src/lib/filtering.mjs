export function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase("zh-CN");
}

export function matchesSearch(haystack, query) {
  const normalizedQuery = normalizeText(query);
  if (!normalizedQuery) return true;
  return normalizeText(haystack).includes(normalizedQuery);
}

export function filterRecords(records, filters) {
  return records.filter((record) => {
    if (!matchesSearch(record.search, filters.query)) return false;
    for (const [key, value] of Object.entries(filters.facets ?? {})) {
      if (
        value &&
        value !== "all" &&
        !String(record[key] ?? "")
          .split(",")
          .includes(value)
      ) {
        return false;
      }
    }
    return true;
  });
}

export function sortRecords(records, direction = "asc") {
  const multiplier = direction === "desc" ? -1 : 1;
  return [...records].sort(
    (left, right) =>
      left.label.localeCompare(right.label, "zh-CN", {
        numeric: true,
        sensitivity: "base"
      }) * multiplier
  );
}

export function paramsFromFilters(filters) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  for (const [key, value] of Object.entries(filters.facets ?? {})) {
    if (value && value !== "all") params.set(key, value);
  }
  if (filters.sort && filters.sort !== "asc") params.set("sort", filters.sort);
  return params;
}
