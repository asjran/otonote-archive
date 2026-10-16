# 技能发动顺序与详情验收

日期：2026-10-16。分支 `codex/skill-activation`，起点 `3861c0f153e2ca9cfcf8c662c848f7cfd364ba54`。工作目录 `/Users/stone/.codex/worktrees/skill-activation/otonote`。

## 交付范围

- 配队推荐、活动收益配队、挑战配队的结果区外显技能顺序。按用户选择，链上仅显示成员头像与发动次序，不增加时刻或姓名正文；悬停与辅助文本保留成员和站位身份。无效/缺失顺序不生成摘要，图片失败显示站位。
- 摘要直接复用已有评分结果，保留最高分、随机样本、指定回放与粗筛的不同含义；平均分没有单一顺序。普通推荐的技能详情移出二层折叠，仍按需启动回放。
- 卡片技能小弹窗合并标题/养成说明、压缩留白，保留正文、等级、未生效的队长提示与 11px 正文字号。
- 回放对话框用独立样式限定宽高、减少留白。保留时间轴、当前效果、统计、条件与覆盖音符；窄屏音轨独占一行。未修改共享对话框、选卡交互或配色主题文件。
- 修复成员/留影效果 ID 跨表重复导致的条件展示错误。

## 真实问题与回归

成员卡 2 / 留影卡 2 的最高技能下，成员得分效果 ID=5、类型=2000；留影未满足的延长效果也为 ID=5、类型=15000。旧展示只按 ID 取记录，把成员的 active=true 套给留影，错误显示 +1.5 秒也生效。

最小回归先确认失败，再将匹配收紧为 ID + 效果类型。原始评分回放验证：留影延长仍为 3000ms；详情生效项只有 +3 秒，+1.5 秒进入未满足条件，实际得分窗口仍为 25–33 秒。当前已审计的成员与留影效果类型不重叠，因此不需要变更共享回放记录格式。

评分公式、120 种顺序的枚举、概率权重、搜索上界与证书均未修改。本轮没有客户端原生执行或实战验证。

## 共享接口与整合注意

`formation-candidate-evaluator.mjs` 只新增透传 `bestOrder`、`worstOrder`、`randomSampling`、`randomSources`，不保留逐音符记录，不增加评分调用。与搜索性能任务整合时需保留这些字段。`skillActivation(..., {summary: row})` 是显式启用的可选展示参数，原有调用不自动扩张歌曲计算或排行榜的紧凑操作栏。

样式集中于新增的 `skill-order.css`、`skill-replay-compact.css`，经 `skill-activation.css` 导入；卡片说明只涉及 `calculator-card-ui.mjs` 和 `card-skill-popover.css`。整合配色及选卡弹窗任务时保留此处布局和内容语义。

## 验证

Node 22.22.0；复用本机现有依赖和只读快照，未下载或更改游戏数据。

| 检查 | 结果 |
| --- | --- |
| 技能、挑战 UI、挑战优化、实用推荐、惰性加载定向回归 | 36/36 通过 |
| 全量 `node --test site/tests/*.test.mjs` | 1159/1165 通过；4 个新增测试通过，6 个既有失败 |
| Astro check | 14 条错误，按文件、行列、错误码、消息与发布诊断逐条相同，新增 0 条 |
| 独立客户端最终构建 | `e70edee33c4d59290422105a`，54 路由 / 58 脚本 / 337 文件 |
| `git diff --check` | 通过 |

定向命令：

```sh
node --test site/tests/skill-activation.test.mjs site/tests/challenge-optimizer-ui.test.mjs site/tests/challenge-optimizer.test.mjs site/tests/practical-optimizer.test.mjs site/tests/tools-loading.test.mjs
```

既有 6 个失败分别为：舞台皮肤贴图缺失、卡片身份测试的 import.meta.glob 夹具、两项沉浸场景资源、激奏 4004 效果行、养成素材清单。详见原发布记录；本轮未以空资源替代它们。

本机日志：`/private/tmp/otonote-skill-targeted-verified.log`、`/private/tmp/otonote-skill-full-node-verified.log`、`/private/tmp/otonote-skill-astro-verified.log`。

## 浏览器验收

使用独立客户端和只读内容快照 `67a80be70928ed663f9af1ec`，真实浏览器测试黑色生日 EXPERT、五人队伍。验证普通配队摘要常驻、头像加载、最高/最低回放切换、下一次发动、条件分组、Esc 关闭与焦点返回。最终构建中原始错误分支已正确归为未生效。

| 布局测量 | 调整前 | 调整后 |
| --- | --- | --- |
| 同一卡片、同等级技能小弹窗 | 320 × 254.23px | 320 × 224.23px，面积减少约 11.8% |
| 1280 × 720 下主回放对话框 | 1020 × 672px | 900 × 660px，面积减少约 13.3% |
| 同谱面五人回放内容高度 | 1399px | 1248px，减少约 10.8% |
| 320px 窄屏顺序链 | — | 容器 234px，链 230px；页面无横向溢出 |
| 320px 窄屏主回放 | — | 290px 对话框、232px 音轨；内容无横向溢出 |
| 320px 窄屏技能小弹窗 | — | 左 12px、右 308px、宽 296px；三段正文完整，11px 字号 |

以上窗口面积是布局比较；不同本地预览域的账号存储可能不同，不将浏览器截图里的分数当作模型 A/B 证据。分数、顺序与完整分布的一致性由同输入回归断言验证。

本机截图保存在 `output/playwright/skill-activation/`：`order-desktop-verified.jpg`、`order-320-final.jpg`、`popover-desktop.jpg`、`popover-mobile.jpg`、`replay-before-desktop.jpg`、`replay-after-desktop.jpg`、`replay-mobile.jpg`、`conditions-fixed.jpg`。

## 保留边界

尚未重新核对客户端随机概率或原生执行；沿用现有评分模型与可达顺序范围。最高分顺序仍是随机情况下的有利顺序，激奏与玩家波动仍按样本表达。未来若成员/留影新增相同效果类型，需要为记录增加明确来源身份，不能继续假定类型分离。

未推送、未创建 PR、未部署；交由发布整合对话合入，并针对与搜索/激奏/配色任务的最终组合重新回归。

## 浏览器验收细化：行内入口与置顶播放台

用户在第一轮页面验收后提出：进一步减少不必要的换行；播放进度与分数置顶；入口并入顺序区；美化头像顺序简图。本轮基于 `346a2c6` 追加提交，保留前一提交不变。

- 顺序区改为紧凑谱带，头像以左上角次序签和轻量连接符组成整体；右侧为小号「回放」按钮。窄屏入口与标题同排，头像链独占下一排；保留随机性说明。
- 行内按钮复用原有 disclosure/modal 的打开路径；原折叠入口隐藏。Worker、缓存、回放时钟不变。Enter 打开、Esc 关闭、焦点返回和展开状态均经真实浏览器验证。
- 顺序切换、综合力、累计分/最终分、短读数与播放进度合为顶部播放台。普通演出隐藏不适用的名次奖励读数；有激奏段时仍保留奖励与段落状态。滚动查看条件或音符明细时，播放台贴在弹窗标题下方。
- 成员身份、留影、时刻、窗口统计及效果来源改为尽量同排，合并重复标题与说明；保留未生效条件与音符明细。

### 本轮验证

| 项目 | 结果 |
| --- | --- |
| 1280 × 720、900px 宽回放的内容高度 | 由第一轮 1248px 降至 887px，约减少 29% |
| 桌面播放台高度 | 117.5px；滚动后顶边与对话框标题底边一致 |
| 320px 播放台 | 183.2px，最终累计分增至 1,286,988 时高度不变；无横向溢出 |
| 窄屏末尾回放 | 109.55s，累计分与本样本最终分一致 |
| 外部窄屏顺序区 | 标题与回放入口同排，五个头像与次序完整可见，无页面横向溢出 |
| 操作 | 跳到下一次发动、最高/最低切换、音符展开、键盘打开与关闭、返回焦点通过 |
| 定向 Node | 36/36 通过 |
| 全量 Node | 1159/1165 通过，剩余同样 6 项基线失败 |
| Astro | 同样 14 条错误，逐条比较新增 0 条 |
| 独立构建 | `fa6afc7fdf3fffbac3b8fe60`，54 路由 / 58 脚本 / 337 文件 |

本轮只调整 `skill-activation-view.mjs`、`skill-order.css`、`skill-replay-compact.css` 及文档，不改评分器或共享弹窗逻辑。上述界面状态在普通配队中做了真实浏览器验收；激奏评分回归沿用 Node 检查，没有新增原生客户端或激奏实战验收声明。

日志：`/private/tmp/otonote-skill-console-targeted.log`、`/private/tmp/otonote-skill-console-full-node.log`、`/private/tmp/otonote-skill-console-astro.log`。截图在 `output/playwright/skill-activation-console/`，包括 `order-current.jpg`、`order-mobile.jpg`、`console-desktop.jpg`、`console-desktop-sticky.jpg`、`console-mobile-sticky.jpg`。
