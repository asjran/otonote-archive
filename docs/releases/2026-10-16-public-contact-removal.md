# 公开联系方式移除交接

核对日期：2026-10-16。仅本地修改并提交，未推送、创建 PR、部署或修改 GitHub 内容。

## 分支与边界

- 基线：`codex/release-2026-10-16`，`3861c0f153e2ca9cfcf8c662c848f7cfd364ba54`。
- 独立任务分支：`codex/remove-public-qq-alt`。
- 用户以页面明确标注的“小号”确认目标；按原有公开联系配置中的对应值精确匹配。本记录不保存该值。
- 供发布整合对话统一合入；本任务未切换或写入发布分支。

## 已本地修正

| 文件 | 修改 |
| --- | --- |
| `site/src/lib/site-contact.mjs` | 删除 QQ 小号配置，保留邮箱和源码仓库 URL。 |
| `site/src/components/SiteFooter.astro` | 删除共用页脚的小号联系行及中英文小号标签。 |
| `site/src/pages/about/index.astro` | 删除关于页面的小号联系行及专用样式，保留邮箱和 Issues 入口。 |
| `site/src/styles/site-footer.css` | 清理删除联系行后不再使用的样式。 |
| `README.md` | 删除小号联系方式。 |
| `docs/USER_GUIDE.md` | 删除反馈段落中的小号联系方式。 |

`CONTRIBUTING.md` 只有邮箱联系入口，保持原样。与联系方式无关的 QQBot、QQ 身份绑定和“小号字体”等内容保持原样。

## 核查与验证

- 修改后扫描基线跟踪的 1718 个文件，未再命中目标的原文、Base64、数字 HTML 实体及逐字符百分号编码；另经 HTML 实体与 URL 解码核对。未在报告中输出匹配值。
- 核对 `SITE_CONTACT` 的引用，页脚和关于页均只保留已允许的联系项。配置运行时导出只有 `email`、`repositoryUrl`。
- 核对 README、贡献指南、使用指南、联系配置及两个模板中的邮箱和 GitHub 引用数量，与基线一致。
- 跟踪图片只有 3 个品牌 SVG，已读取核对，无二维码；未发现指向该小号的 QQ 链接或二维码引用。此结论限本地跟踪文件，不涵盖外部网页或未入库图片。
- codebase-memory 的发布工作区索引早于基线，且文档、静态资源存在排除范围；本次以当前任务工作区的文件扫描和源码读取补充核查。
- Node `v22.22.0`：使用本机主仓库现有 `@astrojs/compiler`，对修改后的页脚及关于页执行 `transform`，无编译错误；没有安装或修改共享依赖。
- `python3 -B -m unittest tests.test_repository_hygiene -q`：16 项通过。
- `git diff --check`：通过。
- 未执行完整站点构建、浏览器视觉或线上验收；本次结果不替代完整发布验证，也不改变交接文件记录的既有全量测试／Astro 检查基线。

## GitHub 只读核查及待远端事项

使用 GitHub API 只读核对下列明确目标，未执行任何远端写入。

| 位置 | 核查结果 | 后续处理 |
| --- | --- | --- |
| [仓库 README](https://github.com/stonesver/otonote/blob/main/README.md) | 远端当前仍含目标联系项。 | 已在本地 README 修正，等待发布整合后获准推送生效，不单独在线编辑。 |
| [仓库简介与主页字段](https://github.com/stonesver/otonote) | 简介未含目标；主页字段为空。 | 本次无需修改。 |
| [作者公开简介](https://github.com/stonesver) | 简介未含目标，公开邮箱与博客字段为空。 | 本次无需修改。 |
| 作者资料仓库 README | API 返回 404，未读取到公开资料 README。 | 未作修改，不视为已检查其内容。 |
| [本仓库 Issues／PR](https://github.com/stonesver/otonote/issues) | 分页核对 99 条正文／标题，目标命中 0，未发现内嵌图片；普通评论 0，PR 行内评论 0。 | 已核查对象无需修改。 |
| 本仓库 Discussions | 仓库未开启。 | 无此展示入口。 |
| [本仓库 Releases](https://github.com/stonesver/otonote/releases) | 发布条目 0。 | 无此展示内容。 |

线上网站仍需统一构建及发布后才会更新。本次未改写历史提交，未核查 GitHub Wiki、其他仓库、外链内容或搜索缓存；如后续发现非 Git 文件位置，需先确认具体 URL、目标字段与允许的远端修改范围。
