/**
 * @template T
 * @param {"dialog-close" | "explicit-reset"} event
 * @param {T} current
 * @param {T} initial
 * @returns {T}
 */
export function nextGrowthDialogState(event, current, initial) {
  return structuredClone(event === "explicit-reset" ? initial : current);
}
