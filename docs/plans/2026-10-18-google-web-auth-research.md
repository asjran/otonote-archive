# Google 游戏账号的网页授权调查

日期：2026-10-18。基线：`07fe9e1`，目标集成分支：`codex/release-2026-10-18`。

本次是可行性调查，不新增登录入口。约束：每次养成/抽卡查询独立认证，不保存本站登录会话，不复用玩家凭据，不开发 App。

## 结论

**游戏发行商已有官方 Google 网页登录流程，但目前没有跑通授权给本站并取得游戏 SDK 身份的完整链路。** 本次有两项新的实际阻断证据：官方网页 Google client 对本站测试回调返回 `redirect_uri_mismatch`；官方网页用户信息接口对本站 Origin 返回 403。

这不证明所有官方合作接入方式都不可行，也不证明任意其他回调地址均被拒绝。当前不能通过增加一个普通 Google 登录按钮实现游戏数据读取。下一步需要官方提供第三方授权/身份交换契约，或登记并支持本站来源和回调；不是继续调整版本号或添加前端参数能解决的问题。

## 已验证的官方网页路径

直接从[游戏官网](https://bdon.biligames.com/)取得其公开脚本，未登录玩家账号：

1. 游戏官网配置 Google 网页 client，使用官方 `overseas-gameweb-passport` 组件。
2. 组件加载旧版 `gapi.auth2`，在 Google 弹窗成功后取得 ID token。
3. 将该凭据提交给官方网页账号服务的 `/bilibili/web/game/login/sns`，字段为 `channel_type=1`、`type=1`、`access_key=<Google ID token>`。
4. 后续通过带 Cookie 的 `/bilibili/web/user/info` 查询网页账号，官网维护自己的网页登录状态。

该网页参数 `access_key` 在此处装的是 Google ID token，不能因名字相似就视为游戏 SDK 的 access token。没有对真实 Google 身份执行此交换，也未取得成功响应，不能声称该网页接口直接返回 `SdkIdentity`。

官网配置中的 `/bilibili/web/global/login/sns/callback` 属于 Apple 配置。本次观察到的 Google 路径使用 JavaScript 弹窗回调，不能把 Apple 地址当作 Google 游戏授权中转地址。

对照旧版官方 Android 1.0.2：它使用另一个 `server_client_id` 申请 server auth code，向 `/gapi/client/sns.login` 提交 `google_code` 和 `third_access_token`。网页与该 Android 配置的 Google client ID 不同；仅凭 Google 用户相同，不能推导两种凭据或两套账号响应可互换。原 APK 静态证据仍是 1.0.2，不称为新版客户端验收。

## 无账号在线验证

### Google 回调配置

使用官网公开的网页 client 发起标准 OAuth 授权请求：

- 测试回调：`https://ournotes.stonebg.cn/api/growth-export/google/callback/`。
- `response_type=code`，scope 为 `openid email profile`，`access_type=online`，`prompt=none`。
- 没有登录 Cookie，没有输入账号或密码，没有点击授权，没有取得授权码或令牌。
- Google 最终到达自己的 `/signin/oauth/error`；已核验其结构化 `authError` 参数包含 `redirect_uri_mismatch`，不是只匹配通用错误页中的提示文字。

此结果只证明**该 client + 该回调组合**不被接受。测试回调尚无实现，校验错误发生在 Google，未触发本站回调。改用弹窗也仍需满足 Google 对授权 JavaScript 来源的登记要求，参见[官方错误处理](https://developers.google.com/identity/oauth2/web/guides/error)和[网页授权码模型](https://developers.google.com/identity/oauth2/web/guides/use-code-model)。

### 官方网页服务的来源响应

对下列公开接口发送无 Cookie GET，只读且不保存 `Set-Cookie`：

`https://l11-web-login.biligames.com/bilibili/web/user/info?lang=en&region=5&web_version=ug`

| Origin | HTTP | 业务结果 | CORS |
| --- | ---: | --- | --- |
| `https://bdon.biligames.com` | 200 | `code=-101`，未登录 | 返回对应 Allow-Origin 和 Allow-Credentials |
| `https://ournotes.stonebg.cn` | 403 | 无业务 code | 无 Allow-Origin |

这是当前响应差异，未确定 403 来自哪一层防护，也不将 CORS 作为服务端授权机制。不能用反向代理、伪造官方 Origin 或转发用户 Cookie，把来源限制绕成“官方支持”。即使跨域放行，Google audience 和游戏身份交换仍需单独验证。

## 为什么普通本站 Google 登录还不够

当前游戏读取需要经过验证的 SDK uid/access token，再做所选服的 `PlayerPreLogin`、`PlayerLogin` 和只读 RPC。本站自行申请的 Google client 可以识别本站用户，但不能自动生成发行商接受的 SDK 身份。

Google 要求后端校验 ID token 的签名、issuer、有效期及预期 audience，参见[官方校验说明](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)。这说明 audience 适配是必要的接入契约；本次没有实测游戏 SDK 对本站自有 client 的具体行为，不将其推断为已证实的拒绝或接受。

在已检查的官网、登录组件及门户登录/账号/充值脚本中，没有找到可交付本站的一次性第三方授权票据及其游戏 SDK 交换契约。此结论限于所列公开脚本，不声称发行商不存在内部或合作方接口。没有调用充值、注册、绑定、邮箱发送或游戏账号创建接口。

## 可选方向

| 方向 | 所需条件 | 当前判断 |
| --- | --- | --- |
| 官方托管授权后返回一次性票据，再换取只读游戏身份 | 官方支持本站回调、票据 audience/有效期/一次性校验与游戏身份交换 | 推荐继续争取；目前未发现公开可用契约 |
| 本站 Google client + 官方认可的身份交换 | 官方明确接受该 client/audience，并提供受支持接口；或为本站登记获准使用的网页配置 | 可研究，但不能只创建 Google 项目就宣称接通 |
| 官方客户端内绑定邮箱，再用现有邮箱读取 | 用户自行操作官方绑定流程，并核对同一服、同一已有角色 | 替代路径；本次未执行绑定，不视为 Google 直接登录 |

设备码、桌面 loopback 和移动端 client 属于各自的 Google 客户端类型，不能直接拿来替代网页来源登记。官方[设备码说明](https://developers.google.com/identity/protocols/oauth2/limited-input-device)及[桌面应用说明](https://developers.google.com/identity/protocols/oauth2/native-app)仍要求相应客户端配置；本次不创建 App、不尝试将这些流程拼成旁路。

## 接通后的无登录会话边界

以下是获得官方接入契约后的候选流程，尚未实施：

```text
用户点击“读取养成”或“查询抽卡”
  -> 当次官方 Google 授权弹窗
  -> 当次授权证明 POST 到本站同源读取接口
  -> 官方允许的身份交换
  -> 所选服已有角色检查、游戏认证、一次只读查询
  -> 返回数据；结束请求，不保留可供下一功能使用的身份
```

- 每个功能重新启动授权并认证；不缓存 Google、SDK 或游戏令牌，不提供 refresh token 存储和后台续期，不签发本站玩家登录会话。
- 必需的 `state`/`nonce`/CSRF 校验只服务于当前授权事务并及时失效，不携带可供后续查数据的玩家身份。具体一次性消费与防重放方式须随官方票据契约审定，不能为追求“无状态”省略校验。
- 授权证明不写 localStorage、sessionStorage、文件或日志；采用同源 POST、no-store、来源校验及现有限流/并发边界。
- Google 自身是否保留登录 Cookie 由用户浏览器和 Google 管理；每次独立认证不等于强制用户每次输入 Google 密码。本工具不会退出用户的 Google 账号或撤销游戏已有的 Google 授权。
- 不自动注册 SDK 账号、绑定账号或创建游戏角色。第三方登录是否自动创建发行商账号，也必须先由官方契约或合适测试账号验证，不能只依赖游戏侧 PreLogin 防线。
- 官网仍使用已弃用的 Google Sign-In JavaScript 库，不建议直接搬用。Google [弃用说明](https://developers.google.com/identity/sign-in/web/deprecation-and-sunset)推荐迁移至 GIS，弃用不等于当前旧 client 一定不可用。

## 外部接入需要确认的具体事项

可向发行商询问，但本任务没有发送邮件、工单或其他消息：

1. 是否向资料查询网站开放 Google 授权？允许哪个 client、Origin 和回调；是否支持 GIS。
2. 授权后是否可返回一次性票据，并在当前请求内交换成游戏认可的 SDK 身份，且不依赖官网持久 Cookie。
3. Google 网页身份与 Global 游戏 SDK 账号如何对应；EN、韩服、港澳台及不同渠道是否共用映射。
4. 票据有效期、audience、nonce、重复消费、取消与验证失败如何处理；能否限定只读范围。
5. 对未注册的 Google 身份，是否能只检查已有账号，避免自动注册、绑定或创建角色。

## 证据与交付边界

公开脚本定位如下；它们没有复制到仓库，只在忽略的本地调查目录保留以便复核：

| 来源 | URL | SHA-256 |
| --- | --- | --- |
| 官网登录组件 | `https://s1.biligames.com/fe-static/overseas-gameweb-passport/index.js` | `0fa92d5894a1d1b5970f4aa2080ebfa0a09ab1edd9015fba5fc8a97cd2df7123` |
| 官网配置与账号调用 | `https://s1.biligames.com/fe-static/game-global-bangdreamon/gw/js/chunk-common.857b2e29.js` | `b7605784a35012dad8d694051f63d508110782c00f1d04c05335967a0e97f416` |
| 账号门户应用 | `https://s1.biligames.com/fe-static/game-platform-bhk/js/app.60c43c05.js` | `1379eff17c190af0d8261177f6fc3d0930be8c399c12cd9f90671409c1e3e399` |

本地脱敏回执：`output/google-web-auth-research-20261018/google-public-redirect-check.json`、`official-web-anonymous-cors.json`；仅含配置检查结果，不含玩家信息或凭据。

现有网关源码已核对：每次请求独立创建 SDK/游戏客户端，支持的认证方式仍仅 `email_password`。图索引中 Python tools 子树被排除，且前端索引早于本轮实现；本结论以当前源文件直接核验为准。本次没有修改认证实现、运行配置或网站页面，没有实际 Google 游戏登录验收，也没有推送或部署。
