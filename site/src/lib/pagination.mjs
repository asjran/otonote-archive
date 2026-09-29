// Short directories are continuous; large directories reveal a growing prefix.
export const SHOW_ALL_LIMIT = 96;

function positiveInteger(value, fallback) {
  const number = Number(value);
  return Number.isSafeInteger(number) && number > 0 ? number : fallback;
}

export function progressiveRecords(records, { shown = 24, batchSize = 24 } = {}) {
  const batch = positiveInteger(batchSize, 24);
  const total = records.length;
  const count = total <= SHOW_ALL_LIMIT
    ? total
    : Math.min(total, Math.max(batch, positiveInteger(shown, batch)));
  return {
    records: records.slice(0, count),
    shown: count,
    total,
    remaining: total - count,
    nextCount: Math.min(batch, total - count)
  };
}

export function progressiveStateFromParams(params, batchSize = 24) {
  const batch = positiveInteger(batchSize, 24);
  const legacySize = [12, 24, 48].includes(Number(params.get("pageSize")))
    ? Number(params.get("pageSize")) : batch;
  const legacyPage = positiveInteger(params.get("page"), 1);
  // Old page links reveal everything through that page, never a middle slice.
  const legacyShown = positiveInteger(legacyPage * legacySize, batch);
  return positiveInteger(params.get("shown"), Math.max(batch, legacyShown));
}

export function progressiveParams(baseParams, result, batchSize = 24) {
  const params = new URLSearchParams(baseParams);
  for (const key of ["page", "pageSize", "shown"]) params.delete(key);
  if (result.total > SHOW_ALL_LIMIT && result.shown > batchSize) {
    params.set("shown", String(result.shown));
  }
  return params;
}

export function progressLabel(result, locale = "zh-CN") {
  const { shown, total, remaining } = result;
  if (locale === "en") return remaining ? `Showing ${shown} of ${total}` : `All ${total} items shown`;
  if (locale === "ja") return remaining ? `${total} 件中 ${shown} 件を表示` : `全 ${total} 件を表示しました`;
  if (locale === "zh-TW") return remaining ? `已顯示 ${shown} / ${total} 項` : `已展示全部 ${total} 項`;
  return remaining ? `已显示 ${shown} / ${total} 项` : `已展示全部 ${total} 项`;
}
