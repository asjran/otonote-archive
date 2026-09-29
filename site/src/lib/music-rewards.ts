import type { MusicRewardEntry } from "./catalog";
import { getAsset } from "./catalog";
import { getItem } from "./game-database";
import { activeReleaseContext } from "./release-context";

const rewardLabels = activeReleaseContext.locale === "en"
  ? new Map([[1, "Stars"], [3, "Coins"]])
  : new Map([[1, "星石"], [3, "金币"]]);
export const rewardView = (entry: MusicRewardEntry) => {
  const item = entry.resourceType === 1
    ? getItem(`item-${entry.resourceId}`)
    : undefined;
  return {
    item,
    asset: getAsset(item?.iconAssetId),
    label: rewardLabels.get(entry.resourceId)
      ?? item?.name
      ?? `资源 ${entry.resourceType}:${entry.resourceId}`,
    href: item
      ? `/database/items/${item.id}/`
      : `/database/items/?q=${entry.resourceId}`
  };
};
