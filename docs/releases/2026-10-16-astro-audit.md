# 2026-10-16 Astro 错误归因核对

结论：发布分支的 14 个 Astro 错误全部能在发布基线复现，本次配队优化和乐器修复整合新增 **0** 个。没有为消除已有诊断而修改业务逻辑或放宽类型检查。

## 同条件对比

| 版本 | 提交 | 错误数 | 与基线逐条比较 |
| --- | --- | --- | --- |
| 发布基线 | `2cabfc2` | 14 | 基线 |
| 乐器修复整合前 | `5ab5c63` | 14 | 完全一致 |
| 发布分支 | `4ee1597` | 14 | 完全一致 |

从各提交 `git archive` 创建隔离源码副本，与发布分支使用同一个 Node 22.22.0、同一依赖安装、相同 `site/src/data` 和本地 public 文件；各自生成 Astro 类型并使用独立的 Astro/Vite 缓存目录。未用新生成的空清单代替缺失资源。

命令为各源码根目录的 `site/` 下执行：

```sh
PATH=/Users/stone/.nvm/versions/node/v22.22.0/bin:$PATH \
OURNOTES_ASTRO_CACHE_DIR=/private/tmp/ASTRO_AUDIT_VARIANT_CACHE \
OURNOTES_VITE_CACHE_DIR=/private/tmp/ASTRO_AUDIT_VARIANT_VITE \
ASTRO_TELEMETRY_DISABLED=1 node_modules/.bin/astro check
```

三个进程均完成检查并返回失败。去除终端颜色后，按文件、行、列、错误码、消息逐条比较；三组 14 条记录完全相同。结构化结果、提交完整 SHA、依赖版本及共享输入摘要见 [诊断证据](2026-10-16-astro-diagnostics.json)。原始日志在本次本地会话的 `/private/tmp/otonote-astro-audit-20261016/` 下，不作为持久化文件依赖。

## 14 条诊断

以下路径相对于 `site/`，全部为原有问题。

| 文件 | 位置 | 错误码 | 具体问题 |
| --- | --- | --- | --- |
| `src/components/SharedTeamWorkspace.astro` | 33:9 | TS7034 | 声明 `workspace` 时无法确定类型 |
| `src/components/SharedTeamWorkspace.astro` | 39:22 | TS7053 | 用 prerender 的 Symbol 索引 globalThis，未声明对应类型 |
| `src/components/SharedTeamWorkspace.astro` | 40:20 | TS7053 | 用 code-root 的 Symbol 索引 globalThis，未声明对应类型 |
| `src/components/SharedTeamWorkspace.astro` | 41:52 | TS7053 | 用 code-manifest 的 Symbol 索引 globalThis，未声明对应类型 |
| `src/components/SharedTeamWorkspace.astro` | 65:14 | TS7005 | 读取 `workspace` 时缺少可推断类型 |
| `src/components/SharedTeamWorkspace.astro` | 68:41 | TS7006 | 动态加载模块回调参数 `m` 隐式为 any |
| `src/lib/mission-display.ts` | 4:28 | TS2307 | 缺少 public/system-banners/manifest.json |
| `src/lib/mission-display.ts` | 7:38 | TS7006 | 清单查找回调参数 `b` 隐式为 any |
| `src/lib/system-display.ts` | 5:26 | TS2307 | 缺少 public/mission-rewards/manifest.json |
| `src/lib/system-display.ts` | 18:50 | TS7006 | 奖励图片映射回调参数 `image` 隐式为 any |
| `src/pages/database/global-systems/index.astro` | 10:23 | TS2307 | 缺少 public/growth/manifest.json |
| `src/pages/database/global-systems/index.astro` | 58:267 | TS7006 | 乐队段位映射回调参数 `rank` 隐式为 any |
| `src/pages/tools/event-efficiency/index.astro` | 29:292 | TS7006 | 奖励来源筛选回调参数 `s` 隐式为 any |
| `src/pages/tools/event-efficiency/index.astro` | 29:384 | TS7006 | 奖励来源筛选回调参数 `s` 隐式为 any |

三份资源清单缺失及相应的三个回调参数诊断共 6 条，属于当前本地资源不完整时即可在基线触发的诊断；未将其当作本次业务代码回归。其余 8 条在相同条件下同样原已存在。

本次只补充归因记录，不修复范围外的原有问题。分支仍未推送、未创建 PR、未部署。
