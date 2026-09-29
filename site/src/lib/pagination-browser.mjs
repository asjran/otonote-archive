import {
  progressiveRecords,
  progressiveParams,
  progressiveStateFromParams,
  progressLabel
} from "./pagination.mjs";

// Keep the adapter interface shared by the existing catalog/filter controllers.
export function createPaginationAdapter(root, { onChange }) {
  const element = root.querySelector("[data-pagination]");
  if (!(element instanceof HTMLElement)) return null;

  const batchSize = Number(element.dataset.defaultPageSize) === 12 ? 12 : 24;
  const more = element.querySelector("[data-load-more]");
  const amount = element.querySelector("[data-load-more-count]");
  const range = element.querySelector("[data-pagination-range]");
  const locale = element.dataset.paginationLocale || "zh-CN";
  let shown = progressiveStateFromParams(new URLSearchParams(location.search), batchSize);
  let current = progressiveRecords([], { batchSize });

  more?.addEventListener("click", (event) => {
    const previousCount = current.shown;
    shown = previousCount + batchSize;
    onChange("push");
    // Keyboard users continue at the first newly revealed record. Pointer users
    // keep their scroll position, even when the last batch hides the button.
    const record = current.records[previousCount];
    const node = record instanceof HTMLElement ? record : (record?.item ?? record?.node);
    if (event.detail === 0 && node instanceof HTMLElement) {
      node.tabIndex = -1;
      node.focus({ preventScroll: true });
      node.scrollIntoView({ block: "nearest", behavior: "instant" });
    } else if (!current.remaining && range instanceof HTMLElement) {
      range.focus({ preventScroll: true });
    }
  });

  return {
    reset() { shown = batchSize; },
    restore(params) { shown = progressiveStateFromParams(params, batchSize); },
    paginate(records) {
      current = progressiveRecords(records, { shown, batchSize });
      shown = current.shown;
      return current;
    },
    render(result) {
      element.hidden = result.total === 0;
      if (range) range.textContent = progressLabel(result, locale);
      if (amount) amount.textContent = `+${result.nextCount}`;
      if (more instanceof HTMLElement) more.hidden = result.remaining === 0;
    },
    params(baseParams) { return progressiveParams(baseParams, current, batchSize); }
  };
}
