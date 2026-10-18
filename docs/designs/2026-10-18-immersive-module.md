# 沉浸式主页模块接入

日期：2026-10-18。用户补充要求覆盖沉浸式主页模块，不能只实现首页大厅。本记录接续 `2026-10-18-immersive-home.md`，取代其中“仅大厅开放”的阶段性边界。

## 交付范围

在 `codex/immersive-home`、独立 worktree `immersive-home/otonote` 上继续提交。前置提交为 `fab5cd40d77ca35924e0ce94e9c015fef249afd2`，发布基点仍为 `8cbef449665280dd1a1cb4361ed20c338e8517df`。整合时应保留两次提交的顺序；本次没有写发布分支、推送、PR 或部署。

已接入国际服五支乐队的全部 39 个场景：MyGO 9、Ave Mujica 8、梦限大MewType 8、millsage 7、一家Dumb Rock! 7。目录的可播放标识、乐队／可用筛选、详情切换、首页共用组件和中英文界面使用同一能力判断。每场从零播放一次并停在结束姿态，使用自己的客户端镜头与背景设置；所有可见人物及配角均可通过姓名／描述按钮或画面点击单独重播。仍然是已有入场动作，不包含点击后的完整剧情。

成员主表有 147 次场景出场记录；额外补齐三个可见配角，总共 150 个可独立控制的出场角色：30002 的像素小人、30003 的白色吉祥物、40001 的泽海奏多。后者 situation prefab 中的 Kanata 锚点写了 `_characterId=6`，但该场景主表没有 6，当前 MasterCharacter 6 是三角初华。浏览器使用独立的 `scene-kanata` 身份，姓名直接取现有 MasterText 的 `Character_Name_Kanata`（泽海奏多／Kanata Sawami），不擅自改成初华或汐见萤，不修改 Master 数据。另两个配角使用描述性名称和各自网页身份。

## 客户端与资源证据

沿用首轮审计的 Global 1.0.1 (25) 原生播放方法；本轮逐一读取 39 份 situation prefab 的镜头字段、角色锚点和动画控制器。metadata SHA-256 `4cbc7d02989c6af496cc33966d03ab01e1200579b1be479c433a8cf61d4b2e0b`，catalog SHA-256 `39b5d81ff337bfe0ef0af668f5b473a18e20aa1f8ce6d1c18ca4d6ffe0583c65`。先核对 metadata、catalog、预制体摘要，再在内存中读取解码内容；不将密钥或解码素材写入仓库。

新增 `tools/build_immersive_client_profiles.py` 生成 `site/src/lib/immersive-client-profiles.json`：39 份配置、40 个已核对的包装版本、9 层共用骨架，实际核验 816 个文件／摘要组合。输入是外置的 `global-current-complete-104-v4/supplemental/public/immersive` 与旧 `site-public/immersive`。运行时继续校验 scene.json、Spine、atlas 和贴图的实际字节；仅目录名相同不能启用配置。未知字节保留原图并给出失配提示，不改外置内容或发布指针。

生成器需要现有解码环境（UnityPy、catalog 适配器和本项目 decoder）；命令为：

```sh
python tools/build_immersive_client_profiles.py \
  --resources-root /path/to/resources \
  --package-root /path/to/global-formal/public/immersive \
  --package-root /path/to/legacy/public/immersive \
  --output site/src/lib/immersive-client-profiles.json \
  --report output/verification/immersive-module/profiles.json
```

相机终点按原生 `SetParameter` / `CalculateOrbitPosition` 重建：`defaultPositionOffset - normalize(originalOffset - defaultPositionOffset) * orbitRatio`，以 originalOffset 为目标，转换 Unity / Three 的 Z 方向；所有 39 场景原生 ease 均为 OutCubic (9)。背景使用 Unity 的 YXZ 欧拉顺序，移除旧咖啡厅包装的启发式初始缩放。移动端仍保留完整人物的适配视野，不声称与手机原生裁切完全一致。

## 共用骨架与物理动态

多个场景把二到四个人装在同一个 Spine 中。不能仅重置整个 SkeletonMesh，也不能只按骨骼名称切动画轨道：共享祖先、IK、加权网格和形变会一起受影响。现在每个人独立采样一份完整 Skeleton，按已核对的 slot 归属，在原生 drawOrder 中组合；仍只使用一个显示网格，保留前后遮挡。环境 slot 跟随全场时间。30006 的后层虽然控制器名含 ArareRitsu，实际只含阿拉蕾的 slot，生成器会剔除并不存在的律后层绑定。

5 份 Spine JSON 含物理约束，分布在 30001、30002、30006。`immersive-pose.mjs` 以固定 60 Hz 推进次级动态，分数帧只应用物理姿态，回退时从初态重建；不会因多次渲染同一帧再次积分。人物重播不重置别人的物理状态，导出及取消可稳定回到各自原来的姿态。没有进行原生客户端逐帧并排验收，不宣称像素级完全复刻。

同时修复两个时间轴问题：暂停通知不能覆盖用户刚选择的时间；滑块上限向上取到百分秒，避免 4.0333 秒等片段因 step=0.01 而永远到不了最后一帧。

## 最终验证

使用 Node 22.22.0 和本地既有外置数据；交付独立客户端构建 `51a5fe5c69758f21af83d1ba`，54 路由、58 脚本、337 文件，路径 `output/immersive-module-release`。

| 验证 | 结果 |
| --- | --- |
| 沉浸式 Node 定向 | 30/30，包括 39 场景素材完整性、共用骨架约束／遮挡、独立时钟、物理姿态回退和导出恢复 |
| 配置生成器 Python | 5/5；覆盖身份冲突、未绑定成员、共享祖先、约束和附属层 |
| 全量 Node | 1120/1151 通过、31 失败；相同依赖／素材条件的前置 `fab5cd4` 为 1115/1146、相同 31 失败，新增失败 0 |
| Astro | 14 errors / 0 warnings / 41 hints；错误路径、行列与文本均与前置检查一致，新增 0 |
| 实际 Chrome 全场景 | 39/39 载入并可拖到结束定格；150/150 角色逐个重播，其他角色进度保持 100% |
| 共用骨架画面检查 | 10001、20006、30006、50002 比较重播前后截图，改变位于所选人物区域；10001 直接点中立希画面触发她的动作 |
| 实际导出 | 30006 PNG 3840×2160、10,906,402 bytes；VP9 WebM 1920×1080、2,861,739 bytes |
| 物理姿态恢复 | PNG、完整 WebM、取消 WebM 后，角色进度完全相同，实际画布截图最大色阶差 1，无超过 2 色阶的差异 |
| 目录／移动／回退 | 筛选 39 个可播放、五队计数 9/8/8/7/7、跨场景切换、320px 无溢出、键盘人物重播、减少动态默认结束帧、中英文、字节失配拒绝／重试、WebGL 中断释放／重载均通过 |

完整功能与 39 场景扫描使用 `425378f944a7892b157f21b8`；交付构建只额外调整移动端人物按钮的 flex 基础宽度，避免五至六人姓名挤在一行。交付构建重新通过中文五人、英文六人、320px 无溢出、载入和结束定格检查，截图见证据目录。

全量结果不能与交接文档旧资源环境的 1155/1161 或首轮 1114/1146 混用；本轮通过临时素材链接补齐沉浸式完整性测试，并用同样条件重跑前置源码副本。未修复或隐藏其他模块的基线失败。

本地证据在 `output/verification/immersive-module-20261018/`，含原生配置审计、配置生成报告、全场景浏览器扫描、导出／像素比较、Node 和 Astro 差异；生成素材和日志不提交 Git。预览使用内容快照 `67a80be70928ed663f9af1ec` 和 `/private/tmp` 内既有正式素材的硬链接补齐，不修改源快照。

## 遗留边界

- 本次客户端配置对应 Global 的 39 场景。日服 39 份现有包装仅一份 situation 摘要与该来源一致，其余不同，不能把 Global 参数直接当作日服参数。JP 暂保留原有能力门禁，待读取日服对应预制体后接入。
- 完整点击剧情、语音、BGM、聚焦对话演出、新动作素材未包含在本轮批准方案中。
- 仅完成 Chrome 本地 WebGL／下载验证；Safari、实体手机、原生逐帧对照及发布后的生产验收仍待执行。
- 新内容若更改已绑定字节，会回到原图／失配提示，需要重新核对并更新配置。未推送、未创建 PR、未部署。
