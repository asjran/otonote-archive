# 双服新增非可玩角色导致内容生产失败

## 证据与设计

Global `39103446346`、JP `39103454999` 均在 `Produce and seal local content` 的图片提取阶段报错：`no unique resource for character-image_assets_character-image-1001everythinginitialdownload_`；未进入上传、checkpoint 或公开晋级。

隔离获取日服 1.0.6 的当前目录和 1.0.0.700 Master，校验 Master 文件摘要并解密：MasterCharacter 从 25 条增为 26 条，新增 1001 的 `_isNonPlayable` 明确为 `true`；目录仍只有 25 组角色图片。旧提取器错误地为所有 MasterCharacter 生成三张可玩角色图片目标。客户端升级和 Master 解密已通过，故障属于两服共用的图片提取规则。

最小修复：`core_image_targets` 仅在 `_isNonPlayable is True` 时跳过该角色的 thumbnail、sprite、face_icon 三个目标。不按 ID 范围猜测，不删除 Master 行，不改变目录匹配或图片完整性检查。字段缺省或为 false 的角色继续要求三张图片；可玩角色缺失/歧义仍报错。NPC 的剧情和其他资源提取保持现有流程。

## 实施与验收

1. 使用实际 CurrentResources / PhoneResources 解析路径构造回归：NPC 无角色图片时生成目标成功；未标记的同 ID 角色缺图仍失败。先观察红测，再修改提取条件。
2. 回放当前真实 Master 与目录，检查所有核心图片目标能唯一定位；同时检查历史数据兼容。
3. 运行图片、角色、日服与国际服相关回归；经今日集成分支、PR 和 CI 后发布，重新触发双服 R2 更新。
4. 线上生成、上传读回、checkpoint、公开晋级是独立验收门，不用本地测试代替；原始游戏文件和秘密不提交。

## 本地验证结果

- 两个新增回归在修复前复现同一角色 1001 错误，修复后通过；覆盖 Global/JP 实际资源匹配方法、明确 true、缺省/false/字符串值及低 ID NPC，不以编号判断。
- 国际服官方当前客户端 1.0.6 的 Master 同样新增 `_id=1001, _isNonPlayable=true`；真实当前 Master 与目录回放：Global 541、JP 539 个核心图片目标全部唯一解析，各有 75 张可玩角色图片。角色 Master 行保持 26 条，未丢弃 NPC 数据。
- 102 项测试通过：current_resources、character_profile、character_media、story_catalog、game_database、current_content_media、jp_phone_inputs、global_update、jp_update、r2_production_gate。最初误写不存在的 test_master_catalog 导致测试加载失败，改为实际 character_profile 模块后整组通过。
- 原始目录、Master 与临时诊断脚本保存在 `/private/tmp/otonote-resource-resolution`，不提交；密钥仅在内存解析并验证，没有写入回执或日志。
- 新的线上完整生产和公开晋级仍待重跑验证；旧失败任务没有公开切换。
