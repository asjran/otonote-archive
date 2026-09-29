import { catalog, getAsset } from "./catalog";
import type { MissionGroup } from "./global-systems";
import { banner, systemHref } from "./system-display";
import missionBanners from "../../public/system-banners/manifest.json";

export function missionVisual(mission: MissionGroup) {
  const native = missionBanners.find(b => b.name === mission.bannerAsset?.split("/").pop());
  if (native) return { image: systemHref(`/system-banners/${native.file}`), logo: undefined, native: true };
  const explicit = banner(mission.bannerAsset || null);
  if (explicit) return { image: explicit, logo: undefined, native: false };
  const cardReward = mission.previewRewards.find(r => r.resourceType === 3 || r.resourceType === 2);
  const rewardedCard = cardReward && (cardReward.resourceType === 3 ? catalog.supportCards : catalog.memberCards).find(c => c.masterId === cardReward.resourceId);
  const band = catalog.bands.find(b => b.masterId === mission.bandId);
  const bandArt = band && catalog.supportCards.find(c => c.rarity === 4 && c.featuredCharacterIds.some(id => band.characterIds.includes(id)));
  const art = rewardedCard || bandArt;
  return { image: art ? getAsset(art.primaryAssetId)?.previewUrl : undefined, native: false,
    logo: band ? getAsset(band.whiteLogoAssetId || band.logoAssetId)?.previewUrl : undefined };
}
