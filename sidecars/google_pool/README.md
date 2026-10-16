# Google OAuth 图像账号池

与 GPT 账号池独立的 Python 模块；复用同一个 HTTP 进程，不复用 GPT 账号表、Token 管理、调度或生成代码。

## 模块边界 / 装配

- `config.py`：Google 路径、公开 installed-app OAuth client 与上游配置。账号凭据不是配置常量。
- `store.py`：独立 SQLite 账号和启用状态；外部输出使用字段白名单，Token 只写入服务端。数据库文件权限 `0600`，不做前端回显。
- `oauth.py`：10 分钟授权会话、PKCE、单次 code 交换、state / callback 匹配。进程重启后未完成的会话失效。
- `upstream.py`：Google OAuth / Cloud Code HTTP 适配，不管理账号库。
- `wire.py`：Gemini `contents` / `inlineData` 与 JSON/SSE 图片协议、大小和 MIME 校验。
- `pool.py`：账号刷新、项目解析、模型额度、每账号一个请求的 lease、只在发送生成请求前切换账号。
- `api.py`：Google FastAPI router / runtime；依赖注入宿主鉴权，后台线程只在启用时续期。
- `../account_service.py`：组合根。先挂 Google router，再挂原 GPT app；显式启动和关闭两个生命周期。Google 包不反向导入 GPT 包。

启动入口已由原 `sidecars.chatgpt_pool.app:app` 改为 `sidecars.account_service:app`。
`sidecars/chatgpt_pool/run.sh`、桌面 runtime、Windows launcher 和 Docker Compose 使用同一个组合入口；旧 GPT 入口保留。Docker 数据仍使用现有 `/app/data` volume，不把 Docker 地址或存储默认值复用于桌面。
已有 `CHATGPT_POOL_*` 仍命名宿主端口/本地认证传输，未改用户已有配置。Google 层只接收明确的鉴权依赖，不读取这些 GPT 配置。

## 数据 / 开关

源码模式：`data/google_pool/accounts.db`；设置 `CANVASHUB_DATA_DIR` 的桌面模式：`$CANVASHUB_DATA_DIR/google_pool/accounts.db`。
可单独使用 `GOOGLE_POOL_DB` 覆盖。GPT DB 不迁移、不改表。

Google 账号池默认关闭，启用状态写入自己的 DB；不与 GPT `enabled` 绑定。不读取 Antigravity Tools 本机文件，也不主动导入任何账号。
导入支持单个 Tools 账号结构 `{"email":"…","token":{"refresh_token":"…","access_token":"…","expiry_timestamp":…,"project_id":"…"}}`，由前端包装成 `accounts` 数组；也支持 Token 字段直接位于账号对象顶层。
导入不联网，不信任外部传入的模型额度；点击刷新后读取真实目录。只导入 access token 时需带有效到期时间，过期后无法自动续期。
凭据存于本地权限受限 SQLite，不是 OS Keychain 加密存储。

## 使用

1. 主后端和 sidecar 都需重启到新代码；当前旧进程不会自动加载新路由。
2. 设置中心 → 账号池 → Google OAuth → 添加 Google 授权，点击生成的授权链接；本机回调保存完成后点击读取账号。
3. 也可主动粘贴授权 JSON 导入；刷新授权 / 额度后查看该账号可用模型。
4. 启用 Google 账号池；画布切到 Google → 线路选择 Google OAuth。
5. 原线路“第三方 API”不变。老工作流默认第三方；新线路保存在节点、工作流、批量参数与任务重试中。

OAuth client 不内置在代码里：同时设置 `GOOGLE_POOL_CLIENT_ID` / `GOOGLE_POOL_CLIENT_SECRET`，或在 Google 账号池数据目录（与 `accounts.db` 同目录，默认 `data/google_pool/`；设置 `CANVASHUB_DATA_DIR` 时为其下的 `google_pool/`）放 `oauth_client.json`：`{"client_id": "...", "client_secret": "..."}`。该文件属于本机配置，不进版本库。两者都没有时 sidecar 照常启动，授权接口返回 `oauth_not_configured`、状态 `oauth_configured: false`；文件格式错误时记录警告并视为未配置。修改后需重启 sidecar。
`GOOGLE_POOL_REDIRECT_URI` 可覆盖回调，默认 `http://localhost:<宿主端口>/oauth-callback`。
该版本宿主接收路径固定为 `/oauth-callback`；自定义 URI 应通过反向代理指向该路径。
远程使用时，Google 重定向到浏览器所在电脑；也可将地址栏完整回调 URL 粘贴回设置中心，由主后端转给 sidecar 校验。不要把授权 code 写进日志；组合入口屏蔽此路径的 uvicorn access log。
需要显式网络代理时设置独立的 `GOOGLE_POOL_PROXY_URL=http://127.0.0.1:<代理端口>`，不读取 GPT 代理配置，也不自动使用系统环境代理。环境配置变更需要重启 sidecar。
没有 project_id 时通过 `loadCodeAssist` 解析；未开通 Antigravity 或无法取得项目的账号返回明确错误，不自动注册项目。

## API

管理端沿用主后端鉴权，前端只经 `desktop-api.js` → `auth-api.js`：

- `GET /api/google-pool/status`
- `POST /api/google-pool/config`：`{"enabled":true}`
- `POST /api/google-pool/oauth-start`：`{}`
- `POST /api/google-pool/oauth-finish`：`{"session_id":"…","callback":"完整 URL"}`
- `POST /api/google-pool/accounts-import`：`{"accounts":[…]}`，最多 50 个，整批先校验并事务写入。
- `POST /api/google-pool/account-refresh`：`{"account_id":"…"}`
- `POST /api/google-pool/account-update`：`{"account_id":"…","enabled":false}`
- `POST /api/google-pool/account-delete`：`{"account_id":"…"}`，仅删除本地授权，不撤销 Google 端授权。

sidecar 上的同名管理路由及以下兼容 API 需要 `Authorization: Bearer <宿主本地 auth key>`，不是 Google access token：

- `GET /v1beta/models`：已经刷新过的可用账号缓存目录。
- `POST /v1beta/models/<model>:generateContent`
- `POST /v1beta/models/<model>:streamGenerateContent?alt=sse`：等待期间发送 SSE 注释心跳，最后发送完整图片事件。

兼容范围为 Gemini 图片请求的 `contents`（text / inlineData）、`generationConfig.imageConfig.aspectRatio / imageSize`。
每个请求返回一张原图；不实现文字 chat、工具调用、远程 fileData 或 OpenAI Images。`/v1/*` 仍完全归原 GPT 服务，避免两种账号混用。
管理 API 不回显 Token、client secret、本地 auth key 或 project_id。返回图片可附加 `google_pool` 的 requested_model / resolved_model / account_id 元数据。

## 路由和失败语义

Cloud Code 调用使用 `project/model/request` envelope、`requestType=image_gen` 和原生 SSE；Pro/Flash 分别在自身 3 / 3.1 家族内按目录匹配，不自动跨档。
额度为零或账号忙碌时不会强制提交。仅前置凭据/额度检查可以继续选下一个账号；生成 POST 一旦发出，超时、断流、5xx、429 都不会自动重放。
取消会中止下游等待并阻止新的提交；已发送的 Google 请求无法保证撤销，上游读取可能持续到返回或超时，期间 lease 不复用。
没有自动 Google → GPT fallback。

画布仍使用现有 `/generate` / `/edit` / batch API，增加 `google_provider_route: "google_pool"`，默认 `third_party`。
`backend/provider_google_pool.py` 返回原图 bytes 和元数据；`backend/services/google_generation.py` 继续既有日期归档、`.txt` / `.md` 提示词文件、原文件 `sendDocument` 投递。
尺寸与请求不符只记录实际信息，不缩放伪造 4K、不自动重新生成。

## 协议参考与验证

实现为独立 Python 适配；协议核对来源为 [Antigravity Manager v4.7.1 官方源码](https://github.com/lbjlaq/Antigravity-Manager/tree/v4.7.1/src-tauri/src)，主要参考 `modules/oauth.rs`、`proxy/mappers/gemini/wrapper.rs`、`proxy/upstream/client.rs`、`proxy/handlers/gemini.rs` 与 `proxy/project_resolver.rs`。
没有直接复制 Rust 业务实现；不代表官方支持或保证所有 Google 账号具有图像资格。

离线回归在本地 ignored `tests/test_google_pool*_local.*`，结果在 `output/google-pool-integration-20260914/`。
协议、OAuth、额度和异常流使用合成账号及固定图片。真实 Google 登录 / 实际出图、生产重启、已安装桌面应用与 Windows 包仍需单独验收。
