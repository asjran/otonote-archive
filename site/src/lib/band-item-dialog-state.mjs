/**
 * @param {string} search
 * @param {Map<string, number[]>} levelsByItem
 */
export function parseBandItemDialogState(search, levelsByItem) {
  const params = new URLSearchParams(search);
  const itemId = params.get("item");
  const levels = itemId ? levelsByItem.get(itemId) : undefined;
  if (!itemId || !levels?.length) {
    return { itemId: null, level: null };
  }

  const requested = Number(params.get("level"));
  const level = levels.includes(requested)
    ? requested
    : Math.max(...levels);
  return { itemId, level };
}

/**
 * @param {string} path
 * @param {string | null} itemId
 * @param {number | null} level
 */
export function bandItemDialogHref(path, itemId, level = null) {
  const url = new URL(path, "https://archive.local");
  if (!itemId) return url.pathname;

  const params = new URLSearchParams({ item: itemId });
  if (Number.isInteger(level)) params.set("level", String(level));
  return `${url.pathname}?${params}`;
}
