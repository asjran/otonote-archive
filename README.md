# OtoNote

BanG Dream! Our Notes 的非官方资料站源码，包含角色与卡牌资料、音乐与谱面、配队工具、剧情阅读与选段长图，以及独立更新的内容管线。

- 在线站点：https://ournotes.stonebg.cn
- 源码仓库：https://github.com/stonesver/otonote
- 联系邮箱：lhystone@qq.com
- QQ：3230342553（小号）

## 公开范围

此仓库从当前开发版本导出并建立全新历史。仅包含应用源码、工具、测试及示例配置，不包含生产账号、服务器凭据、私有部署记录、游戏安装包、游戏图片/音频/模型、数据库或资源快照。资源解密参数通过本地环境变量提供，未包含在源码中。

代码和游戏内容分别发布。源码可以独立编译，但浏览页面需要自行准备符合内容协议的快照；仅克隆本仓库不会得到线上游戏资料。Live2D Core 需按其官方许可自行获取。公开版加载装饰使用站点图标。

## 开发与发布规范

开发、离线 CI、正式候选、不可变程序包及部署入口见 [开发流程](docs/DEVELOPMENT_WORKFLOW.md)。真实配置以线上生效行为为初始基线，保存在仓库之外；提交和交付先通过 [配置与脱敏边界](docs/CONFIGURATION_POLICY.md)。容量维护与数据新鲜度见 [运行维护](docs/OPERATIONS.md)。

正式候选从指定提交的干净检出构建：`bash scripts/build-web-client.sh --candidate HEAD output/code-candidate`。发布复用通过验证的同一产物，固定独立取得的验证回执摘要，并检查旧版本和发布健康；CI 不保存生产凭据，也不自动部署。

本轮落地结果、线上验收与已知限制见 [规范化验收记录](docs/DEVELOPMENT_ACCEPTANCE.md)。

## 编译代码

使用 `.nvmrc` 指定的 Node.js 22.22.0（最低 22.20）及 Python 3.11+：

```sh
nvm use
npm --prefix site ci
bash scripts/build-web-client.sh --preview output/web-client-local
python3 -m tools.code_publication --source output/web-client-local --verify-only
```

构建产物位于 `output/web-client-local`，不读取游戏快照。传统 `npm run dev` 和 Astro 静态投影构建需要本地数据与版本绑定，不能在缺少这些输入时直接使用。

内容发布与本地预览：

```sh
python3 -m tools.content_publication --candidate output/release-candidates/YOUR_CANDIDATE --store output/preview/content
python3 tools/preview_independent_site.py --code output/web-client-local --content output/preview/content --port 4340
```

以上候选目录需要自行准备；不要提交到 Git。

## 验证

不依赖游戏快照的基础检查：

```sh
node --test site/tests/story-share.test.mjs site/tests/startup.test.mjs site/tests/independent-content.test.mjs site/tests/loading-shell.test.mjs
python3 -m unittest tests.test_item_acquisition tests.test_game_database tests.test_code_publication -q
```

完整测试中部分用例依赖私有资源、额外 Python 依赖或服务环境，这些数据和服务不随仓库分发。公开源码的验证范围见 [公开版本说明](docs/PUBLIC_SOURCE.md)。

## 私有配置

按需在本地设置 `OURNOTES_MASTER_SALT_HEX`、`OURNOTES_MASTER_KEY_HEX`、`OURNOTES_MASTER_IV_HEX`（各 32 字节的十六进制字符串）及 `OURNOTES_CRI_KEY`。登录导出工具使用 `packaging/growth-tool/sdk.example.xml` 的本地副本；应用参数与账号信息不可提交。

当前资源同步另需外置 `OURNOTES_BUNDLE_DECODER_PROFILE`，精确绑定客户端版本和元数据；结构及私有维护要求见开发流程。

部署文件只作为模板使用。将 `your-server`、`otonote.example.com` 和 `registry.example.com` 替换为自己的环境，并先校验配置；仓库中没有可直接复用的生产部署身份。

## 权利说明

游戏名称、角色、资源与第三方运行库的权利归各自权利方所有。仓库公开不代表对游戏资源或第三方软件授予许可。第三方说明保留在对应目录；尚未为本项目自有代码指定统一开源许可证。
