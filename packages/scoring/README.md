# 共享计分

此目录是计分算法和公开排行计算的实现来源。纯模块不依赖网站目录、DOM、部署配置或网络；输入的规则、谱面和编成由调用方提供。服务器仍在内容更新时生成公共派生数据，浏览器和 Web Worker 仍计算个人配队，不新增计算 API。

- `scoring-engine.mjs`、`scoring-rules/*.mjs`：稳定快照、编成、谱面重建、普通及激奏计分和回放。
- `song-ranking*.mjs`、`song-skill-windows.mjs`：显式输入的排行计算和排序。
- `server/song-ranking-data.mjs`：仅 Node 可用的文件读取、校验及缓存适配器。调用方必须传入 `publicRoot` 和 `cacheRoot`；默认按此包的实际源码计算缓存指纹。
- `data/`：已审计的公开规则及 native 审计元数据基线，不是运行配置或账号资料。内容生产将当前 Master 参数绑定为版本化规则产物。`tools/build_formal_scoring_rules.py` 同步生成基线和旧网站 JSON 投影。

网站原 `site/src/lib` 路径保留薄转发入口，便于逐步迁移调用方。区服上下文、分享 URL 和页面代码留在网站层。Node 专用入口不能由浏览器导入。

算法版本由 `scoring-rules/model-version.mjs` 声明；规则文件另有 `ruleSetVersion` 和 `sourceReleaseId`。内容清单和排行缓存指纹覆盖实际共享实现。目录迁移没有改变算法版本或数值行为。

离线边界验证：`node --test site/tests/shared-scoring-package.test.mjs`。现有计分、原生回放和 Worker 测试继续通过网站兼容入口验证同一份实现。
