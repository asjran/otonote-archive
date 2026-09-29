import { activeReleaseContext } from "./release-context";
import { siteHref } from "./site-context";

export const en = activeReleaseContext.locale === "en";
export const say = (zh: string, english: string) => en ? english : zh;
export const databaseHref = (path: string) => import.meta.env.BASE_URL === "/" ? path : siteHref(path, activeReleaseContext);
export const plainDescription = (value: string) => value.replace(/\\r\\n|\\n|\r\n/g, "\n");
// Verified against App.Master.ItemType in the production v39 client metadata.
const itemTypes: Record<number, [string, string]> = {
  1: ["普通道具", "General item"], 2: ["招募券", "Recruitment ticket"],
  3: ["成员经验", "Member EXP"], 4: ["留影经验", "Support EXP"], 5: ["角色经验", "Character EXP"],
  6: ["觉醒材料", "Awakening material"], 7: ["LIVE BOOST", "LIVE BOOST"],
  8: ["技能强化券", "Skill material"], 9: ["成员星辉", "Member piece"], 10: ["留影星辉", "Support piece"],
  11: ["兑换道具", "Exchange item"], 12: ["免费星钻", "Free stars"], 13: ["付费星钻", "Paid stars"],
  14: ["金币", "Coins"], 15: ["广告", "Advertisement"], 16: ["付费货币", "Cash"],
  17: ["乐队星辉", "Band piece"], 18: ["通用星辉", "Universal piece"], 19: ["练习跳过道具", "Practice skip"],
  20: ["激奏支援道具", "Arena support item"], 21: ["乐队强化材料", "Band material"],
  22: ["通行证积分", "Pass points"], 23: ["月卡", "Monthly pass"], 24: ["TGW 积分", "TGW points"]
};
export const itemTypeLabel = (code: number) => itemTypes[code]?.[en ? 1 : 0] ?? say("其他道具", "Other item");
