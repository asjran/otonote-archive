export function normalizeMusicSearch(value) {
  return String(value).normalize("NFKC").toLocaleLowerCase().replace(/\s+/g, "");
}

function matchesLevel(value, range) {
  return (
    range === "all" ||
    (range === "15" && value <= 15) ||
    (range === "20" && value >= 16 && value <= 20) ||
    (range === "25" && value >= 21 && value <= 25) ||
    (range === "26" && value >= 26)
  );
}

function matchesBpm(value, range) {
  return (
    range === "all" ||
    (range === "slow" && value < 140) ||
    (range === "mid" && value >= 140 && value < 180) ||
    (range === "fast" && value >= 180)
  );
}

export function filterMusicRecords(records, filters) {
  const queryParts = String(filters.query || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map(normalizeMusicSearch);
  return records.filter((record) => {
    const search = normalizeMusicSearch(record.search);
    return (
      queryParts.every((part) => search.includes(part)) &&
      (filters.band === "all" || record.bands.includes(filters.band)) &&
      (filters.category === "all" ||
        record.categories.includes(filters.category)) &&
      matchesLevel(Number(record.level), filters.level) &&
      matchesBpm(Number(record.bpm), filters.bpm)
    );
  });
}

export function sortMusicRecords(records, sort) {
  return [...records].sort((left, right) => {
    if (sort === "title") {
      return left.title.localeCompare(right.title, "ja");
    }
    if (sort === "start") {
      return right.start.localeCompare(left.start);
    }
    if (sort === "order") {
      return Number(left.order) - Number(right.order);
    }
    return Number(right[sort]) - Number(left[sort]);
  });
}

export function musicParams(filters) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  for (const key of ["band", "category", "level", "bpm"]) {
    const value = filters[key];
    if (value && value !== "all") params.set(key, value);
  }
  if (filters.sort && filters.sort !== "order") {
    params.set("sort", filters.sort);
  }
  return params;
}
