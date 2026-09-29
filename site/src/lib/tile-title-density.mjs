/**
 * @param {unknown} title
 * @returns {"regular" | "long" | "extra-long"}
 */
export function classifyTileTitleDensity(title) {
  const length = [...String(title ?? "")].length;
  if (length >= 21) return "extra-long";
  if (length >= 13) return "long";
  return "regular";
}
