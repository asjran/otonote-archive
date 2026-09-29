const zh = {
  select: "选段生成长图", cancel: "退出选段", hint: "点选第一句，再点选最后一句，中间内容会一起选中。",
  chooseEnd: "再点一句确定终点，也可以直接生成单句长图。", chosen: "已选第 {start}–{end} 条 · 共 {count} 条",
  line: "选择第 {n} 条", reset: "重新选段", generate: "生成长图", busy: "正在生成…",
  preview: "剧情长图", save: "保存 PNG", share: "分享图片", close: "关闭预览", edit: "调整选段",
  tip: "保存图片后即可分享；手机上也可以长按图片保存。", excerpt: "剧情节选",
  limit: "每张最多选择 80 条，请缩短选段。", tooTall: "这段内容太长，请减少对白后重试。",
  error: "图片生成失败，请重试或缩短选段。", shareError: "暂时无法直接分享，请先保存图片。",
  avatarFallback: "部分头像未能加载，已用名字代替。", ready: "图片已生成", empty: "还没有选中内容",
};
export type StoryShareCopy = Record<keyof typeof zh, string>;
const en: StoryShareCopy = {
  select: "Create story image", cancel: "Exit selection", hint: "Choose the first line, then the last. Everything between them is included.",
  chooseEnd: "Choose an ending line, or create an image of this single line.", chosen: "Lines {start}–{end} · {count} selected",
  line: "Select line {n}", reset: "Start over", generate: "Create image", busy: "Creating…",
  preview: "Story image", save: "Save PNG", share: "Share image", close: "Close preview", edit: "Edit selection",
  tip: "Save the image to share it. On mobile, you can also touch and hold to save.", excerpt: "Story excerpt",
  limit: "Select up to 80 lines per image. Please shorten your selection.", tooTall: "This excerpt is too long. Select fewer lines and try again.",
  error: "Could not create the image. Try again or select fewer lines.", shareError: "Sharing is unavailable. Save the image instead.",
  avatarFallback: "Some portraits could not load. Names are shown instead.", ready: "Image ready", empty: "No lines selected",
};
const tw: StoryShareCopy = {
  select: "選段生成長圖", cancel: "退出選段", hint: "點選第一句，再點選最後一句，中間內容會一起選中。",
  chooseEnd: "再點一句確定終點，也可以直接生成單句長圖。", chosen: "已選第 {start}–{end} 條 · 共 {count} 條",
  line: "選擇第 {n} 條", reset: "重新選段", generate: "生成長圖", busy: "正在生成…",
  preview: "劇情長圖", save: "儲存 PNG", share: "分享圖片", close: "關閉預覽", edit: "調整選段",
  tip: "儲存圖片後即可分享；手機上也可以長按圖片儲存。", excerpt: "劇情節選",
  limit: "每張最多選擇 80 條，請縮短選段。", tooTall: "這段內容太長，請減少對白後重試。",
  error: "圖片生成失敗，請重試或縮短選段。", shareError: "暫時無法直接分享，請先儲存圖片。",
  avatarFallback: "部分頭像未能載入，已用名字代替。", ready: "圖片已生成", empty: "還沒有選中內容",
};
const ja: StoryShareCopy = {
  select: "会話を画像にする", cancel: "選択を終了", hint: "最初と最後の行を選ぶと、その間の会話も選択されます。",
  chooseEnd: "最後の行を選ぶか、この1行だけで画像を作成できます。", chosen: "{start}–{end} 行 · {count} 行を選択中",
  line: "{n} 行目を選択", reset: "選び直す", generate: "画像を作成", busy: "作成中…",
  preview: "ストーリー画像", save: "PNG を保存", share: "画像を共有", close: "プレビューを閉じる", edit: "選択を変更",
  tip: "保存した画像を共有できます。スマートフォンでは画像を長押しして保存することもできます。", excerpt: "ストーリー抜粋",
  limit: "1枚につき80行まで選択できます。選択範囲を短くしてください。", tooTall: "内容が長すぎます。行数を減らして再試行してください。",
  error: "画像を作成できませんでした。再試行するか行数を減らしてください。", shareError: "直接共有できません。画像を保存してください。",
  avatarFallback: "一部のアイコンを読み込めなかったため、名前で表示しています。", ready: "画像を作成しました", empty: "行が選択されていません",
};
export function getStoryShareCopy(locale: string): StoryShareCopy {
  return ({ "zh-CN": zh, "zh-TW": tw, en, ja })[locale] || en;
}
