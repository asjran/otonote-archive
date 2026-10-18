# 日服客户端自动升级实施与验收

状态：设计先提交后实现；本地实现与相关回归完成，交付至 `codex/release-2026-10-18`；生产验收仍待正式发布。设计见 `docs/designs/2026-10-18-jp-client-auto-upgrade.md`。

## 实施顺序

1. 固定任务基线和独立 worktree；先提交设计及本计划。
2. 为 JP 强制升级和推荐版本变化添加回归测试，实现地区专属升级信号；保持 Global 行为。
3. 实现与旧可信 metadata 锚定的动态客户端绑定，覆盖版本/摘要、解密重定位、认证字段唯一匹配、材料变化和损坏回执。
4. 扩展新包获取和 seed 更新：有界下载、精确版本与递增 versionCode、全部分包验签、metadata/Unity 校验、三个真实解密样本、新客户端 RPC、失败回滚。
5. 将动态绑定接入远端客户端、资源解密、生产门禁和轻量恢复；升级信号必须触发完整恢复，回执覆盖全部新增私有输入。
6. 工作流删除固定 1.0.5 刷新，使用完整探测和既有日本出口；新测试加入 CI。核对运行时依赖，记录是否需要新镜像。
7. 运行针对性测试、相关完整 Python 回归、工作流契约检查、源码边界扫描及 diff 检查。真实输入可用时做只读/隔离包验收；记录未完成的云端和页面验收。
8. 自审调用链、失败路径、状态恢复和秘密输出。将结果更新到本文件；提交任务分支。
9. 读取集成分支最新 HEAD、工作区状态和其他任务变更，先将最新集成分支合入任务分支并做相关回归，再合入 `codex/release-2026-10-18`。不得覆盖未提交修改或直接合并 main。

## 必测行为

- 强制升级（失败 gRPC）和推荐升级（成功响应）都正确识别；403/维护不被当作升级。
- 无变化不下载 APK；版本变化不能被轻量缓存吞掉。
- 新版本包正确且材料相同时成功；旧包、超前包、降级、错签名、缺少/重复分包、超限 ZIP/下载失败均拒绝。
- 解密字段和认证字符串唯一重定位成功；密钥/认证变化、多个匹配、metadata 格式变化、资源样本不足或解密失败均拒绝。
- 新 seed 发布前验证新 RPC；失败保存旧 seed/workspace；替换中异常回滚。
- 升级后的 profile 参与输入指纹、私有库存、轻量恢复及 checkpoint；缓存损坏不能走 unchanged。
- Global 现有升级、无变化以及两服公开发布门禁继续通过。

## 验证记录

- 设计与计划先提交：`da9ba8f`；实现提交：`4d1558a`，只在独立任务 worktree 进行。
- 新增 `jp_client_profile.py` 与 `jp_client_upgrade.py`；升级信号、资源解析、完整/轻量门禁、私有回执和 CI 已接通。旧固定版本刷新不再位于生产工作流；保留为旧 seed 初始化工具。
- 自动升级的两个关键失败回归先观察为红：日服商店链接被 Global APK 规则拒绝；新版本复用相同 metadata 时被错误识别成旧客户端。实现后均通过。
- Python 3.11 独立环境：35 个相关模块、363 项测试通过。包含 18 项新增行为测试，覆盖真实结构的合成 metadata、独立 AES-CTR 密文、三分包验证调用、坏签名/旧版/超前版拒绝、损坏/不足的解密样本、重复 ZIP 成员、下载域名边界、失败回滚、升级信号转完整恢复、新 checkpoint 轻量恢复与无变化。
- 回归模块：所有 `tests/test_jp*.py`、`tests/test_r2*.py`，以及 bundle_decoder、current_client_upgrade、global_remote_sync、global_update、global_state_retention、update_health、current_resources、deployment_preservation、runtime_bundle。
- `npm exec --yes --package=node@22.22.0 -- node --test site/tests/r2-content-gateway.test.mjs`：17/17 通过。最初误用本机默认 Node 18 出现 9 项失败；同一未修改网关在项目指定 Node 22 全部通过，不将初次失败计为实现回归。Node 24 的补充检查也通过。
- `tools.repository_hygiene scan --root . --scope working`：1749 个文件通过；`git diff --check` 与修改文件语法检查通过。提交时再次按 staged 清单检查。
- 从干净实现提交 `4d1558a` 构建并再次验证不可变运行时包：374 个文件，包含新增 JP 模块与 `VerifyApk.java`；manifest SHA-256 `7b88c885338ae7c62bb4d2598e1fad69c18a11823622f5fc8445c33fa5ff5c03`。产物仅位于隔离验证目录，未部署。
- 合入前重新检查集成分支为 `4c8911b`，任务分支同步结果为 already up to date。集成 checkout 中已有未跟踪的 `docs/plans/2026-10-18-global-account-login-research.md`，保持不加入本任务；合并后复核其摘要与工作区状态。
- 自审覆盖：官方推荐版本与实际包版本精确绑定、每个分包密码学验签、旧 metadata 摘要锚、绑定只存位置不存密钥、下载重定向前校验、临时 seed 与回滚备份保留、checkpoint 中的 profile/anchor 摘要、旧客户端兼容、所有现有公开晋级门禁。

## 真实客户端验证

- 旧 1.0.5 / 10059：对本机已保存的真实 XAPK 完整运行新校验器，三个分包验签、metadata 重定位和三个实际加密 bundle 均通过。新逻辑结果与原可信 metadata/包摘要相同；不是用模拟测试代替真实签名。
- 官方旧客户端 Version RPC 已返回推荐 **1.0.6**，说明本次真实强制升级已可观察。
- 隔离复制的旧 seed 自动下载本次新包并通过准备阶段；最后的新客户端官方探测返回 `RPC grpc-status 2: under maintenance`。流程因此保留旧 seed，未执行内容生产、R2 上传或指针切换。
- 另一次保留证据的真实 1.0.6 / **10064** 检查：三个分包验签通过、三个加密样本通过、Unity `6000.3.12f1`；包集合 SHA-256 `fc89433848cbf12601e0c2345c651a0a55373a45fbc63619e82c934921529c61`，metadata SHA-256 `e4ad7d6d5e6f408a4c882afb4ed96b45170f6fefb307991355396c90e9c192de`。新客户端官方 RPC 仍返回维护中，结果保存在 `real-106.json`。
- 脱敏本地记录目录 `/private/tmp/otonote-jp-upgrade-validation`。旧包验证回执 `real-105.json`；首次真实自动升级记录 `live-106-8oed9ak1/result.json`。记录目录和游戏二进制均不提交。
- 本次没有更改运行时依赖；现有受审镜像已含 Python、UnityPy、pyelftools、Java、curl、OpenSSL。只给 CI 增加了已有解析库的安装，不要求为本改动重建生产镜像。
- 远端 CI、维护结束后的新客户端成功 RPC、完整云端 shadow、公开 promote 和双服页面切换仍待验收；本地测试及新包解密不能代替这些结论。

## 生产验收（开发合并后独立执行）

- 审核发布代码与运行时依赖，按需要发布固定 digest 镜像。
- 使用正式发布策略允许的源码运行 JP shadow；不临时放宽默认分支和生产凭据门禁。
- 核对新客户端版本/签名、解密样本、完整候选、双语功能与索引、R2 读回、checkpoint、公开指针未改变。
- promote 后核对公开 current、manifest、双服 HTML 交叉引用与真实页面。
- 记录升级恢复耗时；GitHub 原生 cron 空窗单列，不能承诺维护结束即完成切换。
