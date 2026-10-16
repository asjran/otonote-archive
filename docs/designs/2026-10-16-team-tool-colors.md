# 配队工具主题配色调整与本地验收

日期：2026-10-16。任务分支：`codex/team-tool-colors`。

## 范围与设计

从 `codex/release-2026-10-16` 的 `3861c0f153e2ca9cfcf8c662c848f7cfd364ba54` 创建独立 worktree：`/Users/stone/.codex/worktrees/team-tool-colors/otonote`。未在本对话修改发布分支，未推送、创建 PR 或部署。

查看发布基线的真实浏览器页面，并核对 `global.css`、`site-shell.css`、`tool-studio.css`、`task-prototype-theme.css` 和既有共享队伍设计。发现：

- 工具覆写了全站背景与侧栏颜色，灰蓝、淡紫、酒红混用。
- 淡紫边框不足以区分普通卡、选中卡和队长；选卡预览需要颜色之外的选中标记。
- 卡面图标容易受图片背景干扰；同属性／同乐队关系颜色层级接近，部分缺图后的乐队文字挤在固定圆形按钮内。
- 主操作、确认按钮、分数与辅助说明缺少统一层级，小字号来源信息较淡。

选择沿用现有站点纸白／墨色／酒红的方案。仅替换按钮颜色会留下明显的背景和卡面差异；全站替换共享工具样式则会扩大到其他任务，因此采用配队页独立样式。

核心配色：纸底 `#f0eee8`、面板 `#fffdf7`、正文 `#11131b`、辅助文字 `#655e63`、主色 `#7a3155`、焦点 `#315f73`。布局与字体沿用既有页面。

实现：

- 页面、侧栏和弹窗使用纸白与中性边框；选中按钮使用酒红边框、内描边与加粗文字。
- 选中卡片保留原有 `aria-pressed`，增加视觉勾选；队长保留文字并使用酒红标题条。
- 属性／乐队图标放在不透明浅底上，关系标签分别使用蓝／酒红，任务关系为绿色；游戏本身的图标、属性码、乐队身份与 COMBO／LUCK／JUST 颜色不变。
- 图片失败时，乐队名称回退为可伸展的文字按钮，避免固定圆形按钮造成重叠。
- 生成、应用、保存、替换和完成按钮统一为酒红；保留禁用态和明显的键盘焦点。
- 结果区域上沿与主要分数突出，卡名及养成来源提高可读性，原有说明与搜索状态原样保留。

## 改动文件与整合边界

- `site/src/pages/tools/deck-builder/index.astro`：增加一条样式导入。
- `site/src/styles/team-tool-colors.css`：配队页面限定的主题样式。
- 本文：设计、验证与遗留事项。

共享弹窗位于工具容器之外，因此用 `body:has(.tool-studio.task-studio[data-tool-kind="deck-builder"])` 限定。内部规则提高优先级以覆盖既有原型主题；没有修改共享弹窗模块、全站 CSS、搜索器、Worker、评分器或数据文件。

活动曲实际属性覆盖、候选范围、评分模型、最优性证明与技能发动逻辑均未变更。完成状态和“参考”说明不作新的最优性承诺。最终产物中 `--team-surface` 仅出现于配队页 CSS，不进入歌曲排行榜、歌曲计算或活动收益页的 CSS。

整合弹窗交互任务时保留本文件及配队页导入即可；若交互任务更名现有 `.tw-*`、`.ux-card-*` 或 `.task-*` 类名，应联合复核对应样式。没有共享评分接口变动。

## 验证

环境：macOS，本地 Node `22.22.0`，真实 Chromium 浏览器。系统默认 Node 18 未用于验证。

1. 现有定向 Node 回归 **28/28 通过**：

   ```sh
   node --test site/tests/team-card-view.test.mjs site/tests/team-card-picker-ui.test.mjs site/tests/team-planning-ui.test.mjs site/tests/challenge-optimizer-ui.test.mjs site/tests/challenge-best-search.test.mjs
   ```

2. 最终完整独立客户端构建通过：

   ```sh
   node tools/build_web_client.mjs output/team-tool-colors-code-final
   ```

   code ID：`ed29f782d10893ca38235e39`；54 路由、58 脚本、337 文件。最初复用的依赖目录缺少 OpenCV，换用本机完整依赖目录后完成构建；没有为此修改依赖清单。

3. `astro check`：14 错误、0 warnings、37 hints。按 file／line／column／code／message 提取，与 `docs/releases/2026-10-16-astro-diagnostics.json` 的 release 错误逐条相同；新增 **0**。仍不把该检查标为通过。
4. `git diff --check` 通过。未重跑全部 1161 项 Node 测试，发布记录中的 6 项已有失败保持原有结论。
5. 浏览器视觉验收覆盖：1440×1000 桌面、390×844 手机；初始空编成、选卡预览及选中勾选、属性／乐队图标与缺图文字回退、键盘焦点、队长标记、主次按钮、禁用态和实际计算结果。手机队伍沿用局部横向滚动。
6. 实际结果样例：EN 区服，`music-100001`（迷星叫）EASY；成员与留影 ID 均为 1–5；成员 level 30／rank 1／awake 1／skillLevel 1／gekisouSkillLevel 1，留影 level 30／rank 1；手选卡、普通自由演出、参考发挥、平均分。点击生成后显示 `322,637.67`，本次比较 4 组候选。仅作为结果 UI 的验收输入，不作为全局最优或实战分数证据。
7. 浏览器计算样式确认：背景 `rgb(240,238,232)`；主按钮、选中边框和分数为 `rgb(122,49,85)`；桌面无整页横向溢出。
8. 核心文本对比度：白字／酒红 8.76:1，辅助文字／浅面板 6.19:1，正文／浅面板 18.22:1，焦点蓝／浅面板 6.85:1，养成提示琥珀／浅面板 6.38:1。这是对应静态配色的计算值，未宣称全站无障碍审计通过。

## 本地视觉证据

保存在此任务 worktree 的 `output/playwright/team-tool-colors/`（构建／截图不入 Git）：

- `results-before.png`、`results-desktop.png`：同一结果状态的配色前后；before 仅在浏览器临时禁用本次新增样式，随后恢复。
- `selected-desktop.png`、`selected-mobile.png`：卡图预览与选中勾选。
- `results-mobile.png`：手机结果卡组和分数层级。
- `browser-evidence.json`、`astro-comparison.json`、`node-tests.log`、`build.log`：检查证据。

## 遗留与验收限制

- 本地未保存媒体库。验收浏览器通过临时路由读取网站公开内容版本 `856eb982b9af67f4f261e1bc` 的卡图；产品代码未增加代理或在线依赖。旧本地内容版本的部分属性／成长／乐队图标在该公开版本中缺失，仍有媒体 404；已验证文字回退，未把浏览器控制台说成无错误。整合后应以完整匹配媒体库再确认全部游戏图标。
- 本次本地视觉与定向回归不能替代部署后的验收。评分模型、搜索性能和历史 8 分差均不属于本任务修复范围。
- 界面仍沿用既有紧凑字号与手机局部横向卡组；弹窗完整交互由对应任务负责。
