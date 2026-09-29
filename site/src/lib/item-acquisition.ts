import { catalog } from "./catalog";
import { globalSystems, type SystemReward } from "./global-systems";
import { say } from "./database-display";

export interface AcquisitionGroup { title: string; entries: { name: string; detail: string; href?: string }[] }
const index = new Map<number, Map<string, AcquisitionGroup>>();
function add(id: number, category: string, name: string, detail: string, href?: string) {
  const groups = index.get(id) ?? new Map<string, AcquisitionGroup>();
  const group = groups.get(category) ?? { title: category, entries: [] };
  if (!group.entries.some(entry => entry.name === name && entry.detail === detail && entry.href === href)) group.entries.push({ name, detail, href });
  groups.set(category, group); index.set(id, groups);
}
const itemRewards = (rewards: SystemReward[]) => rewards.filter(reward => reward.resourceType === 1 && reward.count > 0);
for (const mission of globalSystems.missions ?? []) {
  const rewards = [...mission.completeRewards, ...mission.stages.flatMap(stage => stage.rewards)];
  for (const id of new Set(itemRewards(rewards).map(reward => reward.resourceId))) {
    const dates = [mission.startAt, mission.endAt].filter(Boolean).join(" → ");
    add(id, say("任务奖励", "Mission rewards"), mission.title,
      [say("完成对应任务领取，数量与条件见任务详情", "Complete matching missions; see mission details for conditions"), dates].filter(Boolean).join(" · "), "/missions/");
  }
}
for (const unit of globalSystems.studioUnits) {
  for (const rewards of Object.values(unit.itemRewards)) {
    for (const reward of itemRewards(rewards)) {
      // Group by band and actual reward; level ranges are shown in the studio itself.
      add(reward.resourceId, say("录音室练习", "Studio practice"), unit.name,
        say("练习奖励中随机获得，可掉落等级与概率见录音室", "Random practice reward; see the studio for levels and rates"), "/database/global-systems/#studio");
    }
  }
  for (const [id, field] of [[3, "rawEarnCoin"], [5, "rawEarnMemberExp"], [6, "rawEarnSupportExp"]] as const) {
    if (unit.levels.some(level => level[field] > 0)) add(id, say("录音室练习", "Studio practice"), unit.name,
      say("随练习时间累积，收益随录音室等级变化", "Accumulates during practice; yield depends on studio level"), "/database/global-systems/#studio");
  }
}
for (const rank of globalSystems.vipRanks) {
  for (const reward of itemRewards(rank.rankUpRewards)) add(reward.resourceId, say("TGW 奖励", "TGW rewards"), `TGW Rank ${rank.rank}`,
    `${say("升级奖励", "Rank-up reward")} × ${reward.count.toLocaleString()}`, "/database/global-systems/#tgw");
  for (const reward of rank.dailyRewards ?? []) if (reward.resourceType === 1 && reward.count > 0) add(reward.resourceId, say("TGW 奖励", "TGW rewards"), `TGW Rank ${rank.rank}`,
    `${say("每日领取", "Daily reward")} · ${say("第", "Day ")}${reward.day}${say("天", "")} × ${reward.count.toLocaleString()}`, "/database/global-systems/#tgw");
}
for (const track of catalog.musicTracks) {
  for (const id of new Set([...(track.soloRewards?.scoreRewards ?? []), ...(track.soloRewards?.comboRewards ?? [])]
    .filter(reward => reward.entry.resourceType === 1 && reward.entry.resourceCount > 0).map(reward => reward.entry.resourceId))) {
    add(id, say("乐曲奖励", "Song rewards"), track.title, say("达成指定分数或连击目标领取", "Reach the required score or combo target"), `/music/${track.id}/`);
  }
}
export const getItemAcquisition = (id: number): AcquisitionGroup[] => [...(index.get(id)?.values() ?? [])];
