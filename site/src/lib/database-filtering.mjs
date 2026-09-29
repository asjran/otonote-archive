import { matchesFilter } from "./filter-controls.mjs";
import { SKILL_FILTER_NAMES } from "./card-skill-filtering.mjs";
function selected(value) {
  return value && value !== "all";
}

export function normalizeDatabaseSearch(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("zh-CN")
    .replace(/\s+/g, "");
}

function matchesDatabaseSearch(haystack, query) {
  const search = normalizeDatabaseSearch(haystack);
  return String(query ?? "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map(normalizeDatabaseSearch)
    .every((part) => search.includes(part));
}

export function filterSkills(skills, filters) {
  return skills.filter((skill) => {
    if (!matchesDatabaseSearch(skill.search, filters.query)) return false;
    return matchesFilter(skill.kind, filters.kind)
      && matchesFilter(skill.effects, filters.effect)
      && matchesFilter(skill.targets, filters.target)
      && matchesFilter(skill.conditional ? "yes" : "no", filters.conditional)
      && matchesFilter(skill.status, filters.status)
      && SKILL_FILTER_NAMES.every(name => matchesFilter(skill.facets?.[name] ?? [], filters[name]));
  });
}

export function sortSkills(skills, sort = "id") {
  return [...skills].sort((left, right) => {
    if (sort === "cards") return right.cards - left.cards;
    if (sort === "name") {
      return left.name.localeCompare(right.name, "ja", {
        numeric: true,
        sensitivity: "base"
      });
    }
    return left.id.localeCompare(right.id, "en", {
      numeric: true,
      sensitivity: "base"
    });
  });
}

export function skillParams(filters) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  for (const key of [
    "kind",
    "effect",
    "target",
    "conditional",
    "status",
    ...SKILL_FILTER_NAMES
  ]) {
    if (selected(filters[key])) params.set(key, filters[key]);
  }
  if (filters.sort && filters.sort !== "id") {
    params.set("sort", filters.sort);
  }
  return params;
}

export function filterItems(items, filters) {
  return items.filter((item) => {
    if (!matchesDatabaseSearch(item.search, filters.query)) return false;
    return matchesFilter(item.type, filters.type)
      && matchesFilter(item.usages, filters.usage)
      && matchesFilter(item.icon, filters.icon)
      && matchesFilter(item.availability, filters.availability);
  });
}

export function sortItems(items, sort = "order") {
  return [...items].sort((left, right) => {
    if (sort === "cards") return right.cards - left.cards;
    if (sort === "name") {
      return left.name.localeCompare(right.name, "ja", {
        numeric: true,
        sensitivity: "base"
      });
    }
    if (sort === "id") {
      return left.id.localeCompare(right.id, "en", {
        numeric: true,
        sensitivity: "base"
      });
    }
    return left.order - right.order;
  });
}

export function itemParams(filters) {
  const params = new URLSearchParams();
  if (filters.query) params.set("q", filters.query);
  for (const key of ["type", "usage", "icon", "availability"]) {
    if (selected(filters[key])) params.set(key, filters[key]);
  }
  if (filters.sort && filters.sort !== "order") {
    params.set("sort", filters.sort);
  }
  return params;
}
