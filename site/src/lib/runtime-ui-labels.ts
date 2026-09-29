type TeamIssueCode =
  | "invalid_draft"
  | "unsupported_schema"
  | "unknown_rule_set"
  | "invalid_slots"
  | "invalid_slot"
  | "unknown_member_card"
  | "unknown_support_card"
  | "unknown_song"
  | "invalid_tgw_card_rank"
  | "invalid_modifiers"
  | "unsupported_difficulty";

type TraceCode =
  | "snapshot_hashed"
  | "mechanism_structure_identified"
  | "unverified_formula_not_executed"
  | "exact_integer_reconciliation_required"
  | "release_mismatch"
  | "rule_set_mismatch"
  | "unsupported_snapshot_schema";

export type RuntimeUiLabels = {
  locale: string;
  highScore: {
    currentEmpty: string;
    targetViewMode: string;
    enterCurrentRating: string;
    targetAchieved: string;
    scoreRateGap: string;
    noReward: string;
    copied: string;
    copyFailed: string;
  };
  teamDraft: {
    copied: string;
    copyFailed: string;
    unknownPrefix: string;
    selectMember: string;
    selectSupport: string;
    complete: string;
    incomplete: string;
    member: string;
    support: string;
    emptySkills: string;
    tgwBonus: string;
    tgwDefault: string;
    slot: string;
    memberSlot: string;
    supportSlot: string;
    validDraft: string;
    draftIssues: string;
    validDraftNote: string;
    issues: Record<TeamIssueCode, string>;
  };
  scoringResearch: {
    fixed: string;
    blankDraft: string;
    notSelected: string;
    power: string;
    invalidInput: string;
    chartUnavailable: string;
    song: {
      invalidShare: string; unavailable: string; breakdown: string;
      scenario: string; factors: string; topology: string; skill: string;
      gekisouUnavailable: string; gekisouPower: string; gekisouSection: string;
      gekisouEstimate: string; gekisouSectionScore: string;
    };
    fields: {
      track: string;
      difficulty: string;
      cards: string;
      tgwCard: string;
      noteObjects: string;
      fullCombo: string;
    };
    trace: Record<TraceCode, string>;
    issues: Record<TeamIssueCode, string>;
  };
  scoreWorkbench: {
    seconds: string;
    terms: {
      time: string;
      combo: string;
      lane: string;
      position: string;
      width: string;
      direction: string;
      timeSignature: string;
    };
    direction: { left: string; right: string; none: string };
    fever: { inside: string; outside: string };
  };
  characterMedia: {
    records: string;
    metadataOnly: string;
    loading: string;
    ready: string;
    active: string;
    errorRetry: string;
    cancelled: string;
    notLoaded: string;
    showLoaded: string;
    loadAndShow: string;
    cancelLoading: string;
    playIdle: string;
    motion: string;
    motionDirection: string;
    playMotion: string;
    stopMotion: string;
    motionReady: string;
    motionLoading: string;
    motionPlaying: string;
    motionStopped: string;
    motionFinished: string;
    motionFailed: string;
    noWebModel: string;
    loadingDetailBefore: string;
    loadingDetailAfter: string;
    readyDetail: string;
    activeDetail: string;
    errorDetail: string;
    idleDetail: string;
    activating: string;
    dynamicLive2d: string;
    characterFallback: string;
    costume: string;
    staticAsset: string;
    finishedModelPreview: string;
    profilePoster: string;
    previewPending: string;
    defaultCostume: string;
    completeModel: string;
    available: string;
    pendingConversion: string;
    staticDisplay: string;
  };
  autoStage: {
    combo: string;
    playDemo: string;
    pauseDemo: string;
    readingChart: string;
    noPlayableAudio: string;
    chartLoadFailed: string;
    playbackDenied: string;
    states: {
      idle: string;
      loading: string;
      ready: string;
      playing: string;
      paused: string;
      seeking: string;
      ended: string;
      error: string;
    };
    skin: {
      realBackground: string;
      realLane: string;
      realNotes: string;
      formalArrows: string;
      staticEffects: string;
      cssStage: string;
    };
  };
};

const zhTeamIssues: Record<TeamIssueCode, string> = {
  invalid_modifiers: "加成设置格式无效，请重置成长与加成设置",
  invalid_draft: "TeamDraft 必须是对象",
  unsupported_schema: "草稿 schemaVersion 不受支持",
  unknown_rule_set: "草稿 ruleSetVersion 未知",
  invalid_slots: "草稿必须包含五个编成槽位",
  invalid_slot: "槽位结构无效",
  unknown_member_card: "成员卡不属于当前 Release",
  unknown_support_card: "留影不属于当前 Release",
  unknown_song: "歌曲不属于当前 Release",
  invalid_tgw_card_rank: "T.G.W CARD 等级不属于当前 Release",
  unsupported_difficulty: "难度不受当前工具支持"
};

const enTeamIssues: Record<TeamIssueCode, string> = {
  invalid_modifiers: "Invalid modifiers; reset growth and bonus settings",
  invalid_draft: "TeamDraft must be an object",
  unsupported_schema: "Draft schemaVersion is unsupported",
  unknown_rule_set: "Draft ruleSetVersion is unknown",
  invalid_slots: "Draft must contain five formation slots",
  invalid_slot: "Slot structure is invalid",
  unknown_member_card: "Member card is not in the current Release",
  unknown_support_card: "Snap is not in the current Release",
  unknown_song: "Track is not in the current Release",
  invalid_tgw_card_rank: "T.G.W CARD rank is not in the current Release",
  unsupported_difficulty: "Difficulty is unsupported by this tool"
};

const zhCN: RuntimeUiLabels = {
  locale: "zh-CN",
  highScore: {
    currentEmpty: "尚未填写",
    targetViewMode: "目标查看模式",
    enterCurrentRating: "填写当前 Rating 后计算",
    targetAchieved: "目标已达成",
    scoreRateGap: "High Score Rate 差额",
    noReward: "该阶段没有奖励记录",
    copied: "目标链接已复制",
    copyFailed: "复制失败，请从地址栏复制"
  },
  teamDraft: {
    copied: "已复制",
    copyFailed: "浏览器未授权剪贴板，请从下方 JSON 手动复制",
    unknownPrefix: "未识别：",
    selectMember: "选择成员卡",
    selectSupport: "选择留影",
    complete: "编队完整 · 5 张成员卡 + 5 张留影",
    incomplete: "编队未完成",
    member: "成员",
    support: "支援",
    emptySkills: "选择卡牌后显示技能摘要。",
    tgwBonus: "等级 {rank}：所有能力值提升 {percent}%（{bp} BP），以成员能力、评级和回忆为基数，逐槽位、逐维取整。",
    tgwDefault: "未填写时按等级 1 计算，T.G.W CARD 能力加成为 0。",
    slot: "槽位",
    memberSlot: "成员卡",
    supportSlot: "留影",
    validDraft: "草稿结构有效",
    draftIssues: "个草稿问题",
    validDraftNote:
      "此结论只验证当前 Release 的 ID 和草稿结构，不代表正式游戏编成规则已通过。",
    issues: zhTeamIssues
  },
  scoringResearch: {
    fixed: "已固定",
    blankDraft: "空白草稿",
    notSelected: "未选择",
    power: "综合能力 · 代码复算",
    invalidInput: "输入无效",
    chartUnavailable: "谱面未加载，仅有目录摘要",
    song: {
      invalidShare: "分享链接包含无效输入，请返回编成页修正。",
      unavailable: "暂无法计算",
      gekisouUnavailable: "完整分数尚不可计算",
      gekisouPower: "综合力 {power}。激奏技能状态、抽选与区段结算顺序仍待闭合，不能套用普通演出分数。",
      gekisouSection: "第 {index} 段 {mission}：{start}–{end} 秒；第 1–5 名额外奖励分别为区段得分的 {percents}%。",
      gekisouEstimate: "逐帧条件模拟 · 综合力 {power} · {samples} 次；样本范围 {min}–{max}，均分抽样标准误 {error}（不含模型误差）。激奏奖励占比 {share}%。",
      gekisouSectionScore: "第 {index} 段 {mission}：音符分 {notes}＋名次奖励 {bonus}（平均名次 {rank}），占总分 {share}%；JUST 判定 {just} 次，激奏 COMBO {combo}，LUCK 点 {luck}。",
      breakdown: "不含演出技能 {base}；技能平均增加 {gain}。120 种随机顺序范围：{min}–{max}。",
      scenario: "计算情景：普通非活动演出、全 Perfect、满生命、无辅助模式。",
      factors: "综合能力 {power}；难度倍率 {factor}；换算音符数 {notes}（按权重计算，不以 FC 计数代替）。",
      topology: "计分事件 {events}；正式 Master 连击数 {master}。",
      skill: "槽位 {slot}：成员技能 Lv.{member}，留影技能 Lv.{support}（0 = 无此技能），演出技能延长 {duration} ms。"
    },
    fields: {
      track: "歌曲",
      difficulty: "难度",
      cards: "卡牌",
      tgwCard: "T.G.W CARD",
      noteObjects: "谱面对象",
      fullCombo: "FC 计数"
    },
    trace: {
      snapshot_hashed: "输入已按稳定字段排序并生成哈希",
      mechanism_structure_identified: "已关联本地 Master 与 IL2CPP 机制证据",
      unverified_formula_not_executed:
        "谱面已按正式包重建；整曲仍按理想输入假设提供明确标注的估算结果。",
      exact_integer_reconciliation_required: "核验标准为正式包代码与独立整数复算；无需真实打一盘。",
      release_mismatch: "输入 Release 与证据 Release 不一致",
      rule_set_mismatch: "输入规则版本与当前规则版本不一致",
      unsupported_snapshot_schema: "输入快照版本不受支持"
    },
    issues: zhTeamIssues
  },
  scoreWorkbench: {
    seconds: "秒",
    terms: {
      time: "时间",
      combo: "当前 Combo",
      lane: "逻辑轨",
      position: "位置",
      width: "宽度",
      direction: "方向",
      timeSignature: "拍号"
    },
    direction: { left: "左", right: "右", none: "无" },
    fever: { inside: "区间内", outside: "区间外" }
  },
  characterMedia: {
    records: "条记录",
    metadataOnly: "仅元数据",
    loading: "正在加载",
    ready: "资源已就绪",
    active: "当前展示中",
    errorRetry: "加载失败 · 可重试",
    cancelled: "已取消",
    notLoaded: "尚未加载",
    showLoaded: "展示已加载模型",
    loadAndShow: "加载并展示",
    cancelLoading: "取消加载",
    playIdle: "播放 Idle 动作",
    motion: "动作",
    motionDirection: "朝向",
    playMotion: "播放动作",
    stopMotion: "停止动作",
    motionReady: "请选择动作；动作文件仅在播放时加载。",
    motionLoading: "正在加载动作",
    motionPlaying: "正在播放",
    motionStopped: "动作已停止；角色保持自然待机。",
    motionFinished: "动作已完成；角色保持自然待机。",
    motionFailed: "动作加载失败，动态立绘仍可继续使用。",
    noWebModel: "该服装源包缺少完整 Web 模型，当前使用成品静态预览。",
    loadingDetailBefore: "正在后台读取该服装的 Live2D 文件（",
    loadingDetailAfter: "）；切换服装或关闭弹层会取消当前读取。",
    readyDetail: "Live2D 文件已就绪，返回这套服装时会直接建立展示。",
    activeDetail: "动态 Live2D 已运行：当前启用自动眨眼、呼吸与指针视线。",
    errorDetail: "该服装加载失败，其他服装不受影响；可点击重试。",
    idleDetail: "该服装支持动态 Live2D；加载状态会在服装之间独立保留。",
    activating: "资源已就绪，正在建立浏览器 Live2D 展示…",
    dynamicLive2d: "动态 Live2D",
    characterFallback: "角色",
    costume: "服装",
    staticAsset: "静态素材",
    finishedModelPreview: "完整模型预览",
    profilePoster: "构建期角色海报（非服装渲染）",
    previewPending: "成品预览待补充",
    defaultCostume: "默认服装",
    completeModel: "完整模型成品",
    available: "可用",
    pendingConversion: "待转换",
    staticDisplay: "静态展示"
  },
  autoStage: {
    combo: "当前 Combo",
    playDemo: "播放演示",
    pauseDemo: "暂停演示",
    readingChart: "正在读取标准化谱面…",
    noPlayableAudio: "当前曲目无可播放音频",
    chartLoadFailed: "谱面数据加载失败，请刷新后重试。",
    playbackDenied: "浏览器未允许播放，请先使用上方音频控件播放一次。",
    states: {
      idle: "等待播放",
      loading: "正在加载音频",
      ready: "谱面就绪",
      playing: "Auto 演示中",
      paused: "已暂停",
      seeking: "正在定位",
      ended: "演示结束",
      error: "音频播放失败"
    },
    skin: {
      realBackground: "真实背景",
      realLane: "真实轨道",
      realNotes: "真实音符",
      formalArrows: "正式箭头 / 图标",
      staticEffects: "静态特效",
      cssStage: "CSS 舞台"
    }
  }
};

const en: RuntimeUiLabels = {
  locale: "en",
  highScore: {
    currentEmpty: "Not entered",
    targetViewMode: "Target view",
    enterCurrentRating: "Enter current Rating to calculate",
    targetAchieved: "Target achieved",
    scoreRateGap: "High Score Rate gap",
    noReward: "No reward is recorded for this tier",
    copied: "Target link copied",
    copyFailed: "Copy failed; copy the URL from the address bar"
  },
  teamDraft: {
    copied: "Copied",
    copyFailed: "Clipboard access was denied; copy the JSON below",
    unknownPrefix: "Unknown: ",
    selectMember: "Select member card",
    selectSupport: "Select snap",
    complete: "Team complete · 5 member cards + 5 snaps",
    incomplete: "Team incomplete",
    member: "Members",
    support: "Snaps",
    emptySkills: "Select cards to show skill summaries.",
    tgwBonus: "Rank {rank}: all power +{percent}% ({bp} BP), applied to member power, ranks and memories, floored per slot and component.",
    tgwDefault: "Defaults to rank 1 with zero T.G.W power bonus.",
    slot: "Slot",
    memberSlot: "Member card",
    supportSlot: "Snap",
    validDraft: "Draft structure is valid",
    draftIssues: "draft issues",
    validDraftNote:
      "This validates IDs and draft structure for the current Release; it does not verify official formation rules.",
    issues: enTeamIssues
  },
  scoringResearch: {
    fixed: "Fixed",
    blankDraft: "Blank draft",
    notSelected: "Not selected",
    power: "Formation power from code",
    invalidInput: "Invalid input",
    chartUnavailable: "Chart not loaded; catalog summary only",
    song: {
      invalidShare: "The shared link has invalid input. Return to the deck builder to correct it.",
      unavailable: "Cannot calculate yet",
      gekisouUnavailable: "Full score not available",
      gekisouPower: "Power {power}. Gekisou skill state, lottery and section settlement order remain incomplete; ordinary scores do not apply.",
      gekisouSection: "Section {index}, {mission}: {start}–{end} s. Additional rewards for ranks 1–5: {percents}% of section score.",
      gekisouEstimate: "Conditional frame replay · power {power} · {samples} samples; observed range {min}–{max}, sampling standard error {error} (excluding model error). Ranking bonus share {share}%.",
      gekisouSectionScore: "Section {index}, {mission}: notes {notes} + ranking bonus {bonus} (mean rank {rank}), {share}% of total; JUST judgements {just}, Gekisou combo {combo}, LUCK points {luck}.",
      breakdown: "Without live skills: {base}; average skill gain: {gain}. Range across 120 random orders: {min}–{max}.",
      scenario: "Scenario: ordinary non-event live, all Perfect, full life, no assist mode.",
      factors: "Power {power}; difficulty factor {factor}; converted notes {notes} (weighted, not the FC count).",
      topology: "Scoring events {events}; production Master combo count {master}.",
      skill: "Slot {slot}: member skill Lv.{member}, support skills Lv.{support} (0 = absent), live skill extended by {duration} ms."
    },
    fields: {
      track: "Track",
      difficulty: "Difficulty",
      cards: "Cards",
      tgwCard: "T.G.W CARD",
      noteObjects: "Note objects",
      fullCombo: "FC count"
    },
    trace: {
      snapshot_hashed: "Input was sorted by stable fields and hashed",
      mechanism_structure_identified:
        "Local Master and IL2CPP mechanism evidence is linked",
      unverified_formula_not_executed:
        "Chart events are reconstructed from production code; whole-song estimates explicitly assume ideal input.",
      exact_integer_reconciliation_required:
        "Verification uses production code and independent integer calculation; no played match is required.",
      release_mismatch: "Input Release does not match the evidence Release",
      rule_set_mismatch:
        "Input rule version does not match the current rule version",
      unsupported_snapshot_schema: "Input snapshot version is unsupported"
    },
    issues: enTeamIssues
  },
  scoreWorkbench: {
    seconds: "sec",
    terms: {
      time: "Time",
      combo: "Current Combo",
      lane: "Logical lane",
      position: "Position",
      width: "Width",
      direction: "Direction",
      timeSignature: "Time signature"
    },
    direction: { left: "Left", right: "Right", none: "None" },
    fever: { inside: "Inside range", outside: "Outside range" }
  },
  characterMedia: {
    records: "records",
    metadataOnly: "Metadata only",
    loading: "Loading",
    ready: "Resources ready",
    active: "Currently displayed",
    errorRetry: "Load failed · retry available",
    cancelled: "Cancelled",
    notLoaded: "Not loaded",
    showLoaded: "Show loaded model",
    loadAndShow: "Load and show",
    cancelLoading: "Cancel loading",
    playIdle: "Play Idle motion",
    motion: "Motion",
    motionDirection: "Direction",
    playMotion: "Play motion",
    stopMotion: "Stop motion",
    motionReady: "Choose a motion; its file loads only when played.",
    motionLoading: "Loading motion",
    motionPlaying: "Playing",
    motionStopped: "Motion stopped; the character remains naturally idle.",
    motionFinished: "Motion finished; the character remains naturally idle.",
    motionFailed: "Motion loading failed; the dynamic portrait remains available.",
    noWebModel:
      "This costume package has no complete Web model; the finished static preview is shown.",
    loadingDetailBefore: "Reading this costume's Live2D files in the background (",
    loadingDetailAfter:
      "); switching costumes or closing the dialog cancels the current read.",
    readyDetail:
      "Live2D files are ready; returning to this costume will create the display immediately.",
    activeDetail:
      "Dynamic Live2D is running with automatic blinking, breathing, and pointer gaze.",
    errorDetail:
      "This costume failed to load; other costumes are unaffected and this one can be retried.",
    idleDetail:
      "This costume supports dynamic Live2D and keeps independent load state.",
    activating: "Resources ready; creating the browser Live2D display…",
    dynamicLive2d: "Dynamic Live2D",
    characterFallback: "Character",
    costume: "Costume",
    staticAsset: "Static asset",
    finishedModelPreview: "Complete model preview",
    profilePoster: "Build-time character poster (not a costume render)",
    previewPending: "Finished preview pending",
    defaultCostume: "Default costume",
    completeModel: "Complete model",
    available: "Available",
    pendingConversion: "Pending conversion",
    staticDisplay: "Static display"
  },
  autoStage: {
    combo: "Current Combo",
    playDemo: "Play demo",
    pauseDemo: "Pause demo",
    readingChart: "Loading normalized chart…",
    noPlayableAudio: "No playable audio is available for this track",
    chartLoadFailed:
      "Chart data failed to load. Refresh the page and try again.",
    playbackDenied:
      "Playback was blocked. Start the audio once with the player above.",
    states: {
      idle: "Waiting to play",
      loading: "Loading audio",
      ready: "Chart ready",
      playing: "Auto demo playing",
      paused: "Paused",
      seeking: "Seeking",
      ended: "Demo ended",
      error: "Audio playback failed"
    },
    skin: {
      realBackground: "Authentic background",
      realLane: "Authentic lane",
      realNotes: "Authentic notes",
      formalArrows: "Official arrows / icons",
      staticEffects: "Static effects",
      cssStage: "CSS stage"
    }
  }
};

export const runtimeUiLabels = { "zh-CN": zhCN, en } as const;

export const getRuntimeUiLabels = (locale: string | undefined) =>
  locale === "en" ? runtimeUiLabels.en : runtimeUiLabels["zh-CN"];
