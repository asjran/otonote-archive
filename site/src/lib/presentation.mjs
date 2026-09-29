const LANDSCAPE_MIN_RATIO = 1.5;
const PORTRAIT_MAX_RATIO = 0.86;

/** @typedef {import("./catalog").Asset} Asset */
/** @typedef {"primary" | "portrait" | "square" | "banner"} FeaturedSlot */

/** @param {{ width: number, height: number }} asset */
export function assetShape(asset) {
  const ratio = asset.width / Math.max(asset.height, 1);
  if (ratio >= LANDSCAPE_MIN_RATIO) return "landscape";
  if (ratio <= PORTRAIT_MAX_RATIO) return "portrait";
  return "square";
}

/**
 * @param {Asset[]} assets
 * @returns {Array<{ asset: Asset, slot: FeaturedSlot }>}
 */
export function selectFeaturedAssets(assets) {
  /** @type {Set<string>} */
  const used = new Set();
  /** @type {Array<{ asset: Asset, slot: FeaturedSlot }>} */
  const featured = [];

  /** @type {Array<{
   *   slot: FeaturedSlot,
   *   shape: "landscape" | "portrait" | "square",
   *   targetRatio: number,
   *   matches: (asset: Asset) => boolean
   * }>} */
  const slots = [
    {
      slot: "primary",
      shape: "landscape",
      targetRatio: 16 / 9,
      matches: (asset) =>
        asset.kind === "card" && assetShape(asset) === "landscape"
    },
    ...Array.from({ length: 3 }, () => ({
      slot: "portrait",
      shape: "portrait",
      targetRatio: 3 / 4,
      matches: (asset) =>
        asset.kind === "card" && assetShape(asset) === "portrait"
    })),
    ...Array.from({ length: 2 }, () => ({
      slot: "square",
      shape: "square",
      targetRatio: 4 / 3,
      matches: (asset) =>
        asset.kind === "background" && assetShape(asset) === "square"
    })),
    {
      slot: "banner",
      shape: "landscape",
      targetRatio: 2.7,
      matches: (asset) =>
        asset.kind === "banner" && assetShape(asset) === "landscape"
    }
  ];

  for (const definition of slots) {
    const byRatio = (left, right) => {
      const leftRatio = left.width / Math.max(left.height, 1);
      const rightRatio = right.width / Math.max(right.height, 1);
      const ratioDifference =
        Math.abs(leftRatio - definition.targetRatio) -
        Math.abs(rightRatio - definition.targetRatio);
      return (
        ratioDifference ||
        right.width * right.height - left.width * left.height
      );
    };
    const exact = assets
      .filter(
        (asset) => !used.has(asset.id) && definition.matches(asset)
      )
      .sort(byRatio)[0];
    const shapeFallback = assets
      .filter(
        (asset) =>
          !used.has(asset.id) && assetShape(asset) === definition.shape
      )
      .sort(byRatio)[0];
    const fallback = assets.find((asset) => !used.has(asset.id));
    const asset = exact ?? shapeFallback ?? fallback;
    if (!asset) continue;

    used.add(asset.id);
    featured.push({ asset, slot: definition.slot });
  }

  return featured;
}
