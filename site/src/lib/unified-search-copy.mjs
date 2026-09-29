const zh = {
  title: "全局搜索", description: "从一个名字，找到相关的歌曲、卡牌与故事。", placeholder: "搜索名称、角色、乐队或编号…",
  close: "关闭搜索", clear: "清空关键词", all: "全部", filter: "搜索分类", results: "搜索结果",
  loading: "正在准备搜索…", error: "暂时无法加载搜索内容", errorHint: "请检查网络连接，再试一次。", retry: "重新加载",
  empty: "想找些什么？", emptyHint: "支持名称、别名和编号，也可以用空格组合多个关键词。", suggestions: "试试搜索",
  noResults: "没有找到匹配内容", noResultsHint: "试试缩短关键词，或换一个名称、别名。", otherTypes: "其他分类还有 {count} 条结果。", showAll: "查看全部分类",
  summary: "找到 {total} 条结果", partial: "已显示 {shown} / {total} 条结果", ready: "搜索歌曲、角色、卡牌、剧情、道具与技能",
  more: "加载更多结果", choose: "选择", open: "打开", dismiss: "关闭", composing: "正在输入…",
  types: { music: "歌曲", character: "角色", member_card: "成员卡", support_card: "留影", story: "剧情", item: "道具", skill: "技能" }
};
const en = {
  title: "Search the archive", description: "One name. Connected songs, cards and stories.", placeholder: "Search names, characters, bands or IDs…",
  close: "Close search", clear: "Clear query", all: "All", filter: "Search categories", results: "Search results",
  loading: "Preparing search…", error: "Search is unavailable", errorHint: "Check your connection and try again.", retry: "Try again",
  empty: "What are you looking for?", emptyHint: "Search names, aliases or IDs. Combine keywords with spaces.", suggestions: "Try searching",
  noResults: "No matching results", noResultsHint: "Try a shorter query, another name or an alias.", otherTypes: "There are {count} results in other categories.", showAll: "Search all categories",
  summary: "{total} results found", partial: "Showing {shown} of {total} results", ready: "Search music, characters, cards, stories, items and skills",
  more: "Load more results", choose: "Select", open: "Open", dismiss: "Close", composing: "Typing…",
  types: { music: "Music", character: "Characters", member_card: "Member cards", support_card: "Snaps", story: "Stories", item: "Items", skill: "Skills" }
};
const tw = { ...zh, title: "全域搜尋", description: "從一個名字，找到相關的歌曲、卡牌與故事。", placeholder: "搜尋名稱、角色、樂隊或編號…",
  close: "關閉搜尋", clear: "清空關鍵詞", filter: "搜尋分類", results: "搜尋結果", loading: "正在準備搜尋…", error: "暫時無法載入搜尋內容", errorHint: "請檢查網路連線，再試一次。", retry: "重新載入",
  empty: "想找些什麼？", emptyHint: "支援名稱、別名和編號，也可以用空格組合多個關鍵詞。", suggestions: "試試搜尋", noResults: "沒有找到符合的內容", noResultsHint: "試試縮短關鍵詞，或換一個名稱、別名。", otherTypes: "其他分類還有 {count} 條結果。", showAll: "查看全部分類", summary: "找到 {total} 條結果", partial: "已顯示 {shown} / {total} 條結果", ready: "搜尋歌曲、角色、卡牌、劇情、道具與技能", more: "載入更多結果", choose: "選擇", open: "開啟", dismiss: "關閉", composing: "正在輸入…", types: { ...zh.types, member_card: "成員卡", story: "劇情" } };
const ja = { ...en, title: "アーカイブ検索", description: "名前から、楽曲・カード・物語を探そう。", placeholder: "名前・キャラクター・バンド・IDを検索…",
  close: "検索を閉じる", clear: "キーワードを消去", all: "すべて", filter: "検索カテゴリ", results: "検索結果", loading: "検索を準備中…", error: "検索を読み込めませんでした", errorHint: "接続を確認して、もう一度お試しください。", retry: "再読み込み",
  empty: "何を探していますか？", emptyHint: "名前・別名・IDに対応。空白で複数のキーワードを組み合わせられます。", suggestions: "検索してみる", noResults: "一致する結果がありません", noResultsHint: "短いキーワードや別名で検索してみてください。", otherTypes: "他のカテゴリに {count} 件の結果があります。", showAll: "すべてのカテゴリで検索", summary: "{total} 件見つかりました", partial: "{total} 件中 {shown} 件を表示", ready: "楽曲・キャラクター・カード・ストーリー・アイテム・スキルを検索", more: "もっと見る", choose: "選択", open: "開く", dismiss: "閉じる", composing: "入力中…", types: { music: "楽曲", character: "キャラクター", member_card: "メンバー", support_card: "スナップ", story: "ストーリー", item: "アイテム", skill: "スキル" } };
export function searchCopy(locale) { return ({ "zh-CN": zh, "zh-TW": tw, en, ja })[locale] ?? zh; }
