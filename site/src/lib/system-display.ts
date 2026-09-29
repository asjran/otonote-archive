import { catalog, getAsset, getCardRarity } from "./catalog";
import { activeReleaseContext } from "./release-context";
import { siteHref } from "./site-context";
import type { SystemReward } from "./global-systems";
import rewardImages from "../../public/mission-rewards/manifest.json";

export const en = activeReleaseContext.locale === "en";
export const say = (zh: string, english: string) => en ? english : zh;
export const systemHref = (path: string) => import.meta.env.BASE_URL === "/" ? path : siteHref(path, activeReleaseContext);
export const categories: Record<string, string> = {
  permanent: say("常驻", "Permanent"), limited: say("限时", "Limited"), event: say("活动", "Event"),
  birthday: say("生日", "Birthday"), ticket: say("招募券", "Ticket"), pass: say("通行证", "Pass"), ad: say("广告", "Ad"),
  daily: say("每日", "Daily"), beginner: say("新手", "Beginner"), character: say("角色", "Character"),
  secret: say("隐藏", "Hidden"), music: say("乐曲解锁", "Song unlock"), home: say("主页解锁", "Home unlock"),
  comeback: say("回归", "Comeback"), circle: say("社群", "Circle"), invitation: say("邀请", "Invitation"), other: say("其他", "Other")
};
const assets = new Map(catalog.assets.map(a => [a.containerPath, a]));
const archivedRewards = new Map(rewardImages.map(image => [image.imagePath, image.file]));
export const banner = (path: string | null) => path ? assets.get(`Assets/AddressableResources/${path}.png`)?.previewUrl : undefined;
export function rewardView(reward: SystemReward) {
  const card = reward.resourceType === 2 ? catalog.memberCards.find(c => c.masterId === reward.resourceId)
    : reward.resourceType === 3 ? catalog.supportCards.find(c => c.masterId === reward.resourceId) : undefined;
  const asset = card ? getAsset(card.thumbnailAssetId ?? card.primaryAssetId)
    : reward.imagePath ? assets.get(`Assets/AddressableResources/${reward.imagePath}.png`) : undefined;
  const music = reward.resourceType === 8 ? catalog.musicTracks.find(track => track.masterId === reward.resourceId) : undefined;
  const archived = reward.imagePath ? archivedRewards.get(reward.imagePath) : undefined;
  return { ...reward, name: card?.displayName || reward.name,
    image: asset?.thumbnailUrl || asset?.previewUrl || (archived ? systemHref(`/mission-rewards/${archived}`) : undefined),
    href: card ? systemHref(`/cards/${reward.resourceType === 2 ? "members" : "supports"}/${card.id}/`) : music ? systemHref(`/music/${music.id}/`) : undefined };
}
export const rarityLabel = (rarity: number) => getCardRarity(rarity)?.label || "—";
