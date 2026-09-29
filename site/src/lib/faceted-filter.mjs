const normalize = (value) =>
  String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/\s+/g, "");

const matchesQuery = (record, query) => {
  const parts = String(query ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map(normalize);
  const search = normalize(record.search);
  return parts.every((part) => search.includes(part));
};

const matchesSelected = (record, selected, omittedFacet = null) =>
  Object.entries(selected ?? {}).every(([facet, values]) => {
    if (facet === omittedFacet || !Array.isArray(values) || values.length === 0) {
      return true;
    }
    const recordValues = record.facets?.[facet] ?? [];
    return values.some((value) => recordValues.includes(value));
  });

export function evaluateFacets(records, { query = "", selected = {} } = {}) {
  const matching = records.filter(
    (record) =>
      matchesQuery(record, query) &&
      matchesSelected(record, selected)
  );
  const facetValues = {};
  for (const record of records) {
    for (const [facet, values] of Object.entries(record.facets ?? {})) {
      const known = facetValues[facet] ?? new Set();
      values.forEach((value) => known.add(value));
      facetValues[facet] = known;
    }
  }

  const counts = {};
  const disabled = {};
  for (const [facet, values] of Object.entries(facetValues)) {
    const contextual = records.filter(
      (record) =>
        matchesQuery(record, query) &&
        matchesSelected(record, selected, facet)
    );
    counts[facet] = {};
    disabled[facet] = [];
    for (const value of values) {
      const count = contextual.filter((record) =>
        (record.facets?.[facet] ?? []).includes(value)
      ).length;
      counts[facet][value] = count;
      if (count === 0 && !(selected[facet] ?? []).includes(value)) {
        disabled[facet].push(value);
      }
    }
  }
  return { records: matching, counts, disabled };
}

export function selectedFacetsFromParams(params, facetNames) {
  return Object.fromEntries(
    facetNames.map((name) => [
      name,
      (params.get(name) ?? "").split(",").filter(Boolean)
    ])
  );
}

export function facetParams({
  query = "",
  selected = {},
  sort = "",
  defaultSort = "asc"
} = {}) {
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  for (const [facet, values] of Object.entries(selected)) {
    if (Array.isArray(values) && values.length > 0) {
      params.set(facet, values.join(","));
    }
  }
  if (sort && sort !== defaultSort) params.set("sort", sort);
  return params;
}
