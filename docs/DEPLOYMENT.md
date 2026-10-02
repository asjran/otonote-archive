# 当前部署入口

正式代码发布统一使用 `scripts/publish-web-client.sh`，参数、验证回执及外置配置契约见 [开发与发布流程](DEVELOPMENT_WORKFLOW.md)。发布直接晋级已验收产物，不重新构建。实际配置以线上当前生效行为为迁移基线，配置值不提交，见 [配置政策](CONFIGURATION_POLICY.md)。

网站代码、内容快照、运行程序和预渲染分别记录身份及回滚目标。新建 Query 服务、改变公网路由仍需独立验收，不随代码规范化自动启用。

下文保留旧静态站维护说明；旧命令不能替代现行正式代码交付入口。

2026-09-28 新增代码与内容独立发布流程：见 [独立更新操作说明](INDEPENDENT_CODE_CONTENT.md)。该方式在本机构建并发布代码，服务器仅更新数据和媒体；以下完整静态站发布流程保留用于旧站回退。

本地仅保留正式 Global 网站和测试包 AnonTokyo，两者使用独立命令。构建输入和本地预览见根目录 README。

- `tools/deploy_site.sh`：检查工作区、测试、构建新的 Global 候选，生成 SiteRelease 清单，上传并原子切换服务器版本。`rollback` 子命令回到上一版本。
- `tools/deploy_anontokyo.sh`：生成 `output/anontokyo/site/`，同步 `/anontokyo/` 和 `/media/anontokyo/`；默认目标为 `aliyun:/srv/ournotes/current`。
- `--skip-build` 只用于已经核验过的对应候选。正式候选默认位置是 `output/release-builds/global-production-current/site`，可用 `OURNOTES_DIST_DIR` 指定其他候选。
- 正式包的媒体索引与 release-index 位于候选的 `global/zh-CN/data/`。部署不再调用旧双服矩阵构建器。

Nginx、Worker、Query 的配置保留在 `deploy/`；Query 和真实资源采集的启用仍需要独立验证。可使用 `tools/sync_server_data.py --dry-run` 核对 `config/server-sync.local.toml` 中的备份范围，再执行同步。

本轮本地清理没有修改远端目录、执行部署、重启服务或迁移数据。

## Query 的独立启用条件

Query 使用安装后的 `query.service` 单元和容器 UID/GID 10001。完成容量、配置与权限验收并获准启用后，身份目录可用 `install -d -o 10001 -g 10001 /srv/ournotes-data/identity` 准备，服务启动命令为 `systemctl start query.service`。此处仅记录操作契约，本轮没有执行启用。
