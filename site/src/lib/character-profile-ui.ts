const zh = {
  archive: "角色档案", intro: "角色介绍", facts: "个人资料", birthday: "生日",
  height: "身高", constellation: "星座", bloodType: "血型", school: "学校",
  schoolClass: "年级 / 班级", favoriteFood: "喜欢的食物", hobby: "兴趣",
  members: "成员卡", supports: "登场留影", music: "参与演唱", all: "查看全部",
  portraitMissing: "角色立绘待补充", source: "资料来源", sourceNote: "角色资料来自当前所选游戏版本。",
  emptyMembers: "当前版本暂无该角色的成员卡。", emptySupports: "当前版本暂无该角色登场的留影。"
};
const translations: Record<string, typeof zh> = {
  "zh-CN": zh,
  "zh-TW": { ...zh, archive: "角色檔案", intro: "角色介紹", facts: "個人資料", constellation: "星座", school: "學校", schoolClass: "年級 / 班級", favoriteFood: "喜歡的食物", hobby: "興趣", members: "成員卡", supports: "登場留影", music: "參與演唱", all: "查看全部", portraitMissing: "角色立繪待補充", source: "資料來源", sourceNote: "角色資料來自目前所選遊戲版本。", emptyMembers: "目前版本暫無該角色的成員卡。", emptySupports: "目前版本暫無該角色登場的留影。" },
  ja: { archive: "キャラクター", intro: "プロフィール", facts: "基本情報", birthday: "誕生日", height: "身長", constellation: "星座", bloodType: "血液型", school: "学校", schoolClass: "学年 / クラス", favoriteFood: "好きな食べ物", hobby: "趣味", members: "メンバーカード", supports: "登場するスナップ", music: "歌唱楽曲", all: "すべて見る", portraitMissing: "立ち絵は未収録です", source: "出典", sourceNote: "選択中のゲームバージョンに収録されたプロフィールです。", emptyMembers: "このバージョンにメンバーカードはありません。", emptySupports: "このバージョンに登場するスナップはありません。" },
  en: { archive: "Character profile", intro: "About", facts: "Personal details", birthday: "Birthday", height: "Height", constellation: "Zodiac sign", bloodType: "Blood type", school: "School", schoolClass: "Year / Class", favoriteFood: "Favorite food", hobby: "Hobbies", members: "Member cards", supports: "Featured snaps", music: "Vocal tracks", all: "View all", portraitMissing: "Portrait unavailable", source: "Source", sourceNote: "Profile from the selected game version.", emptyMembers: "No member cards in this version.", emptySupports: "No featured snaps in this version." }
};
export const characterProfileUi = (locale: string) => translations[locale] ?? zh;
