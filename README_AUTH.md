# Auth Note

当前版本的 Mini App 使用的是一套**最小鉴权**：

- 访问密码校验
- 服务端签发 `HttpOnly Cookie`
- 前端进入页面后通过 `POST /api/auth/verify` 检查登录状态

## 当前行为

- `POST /api/auth/login`
  校验密码；成功后返回登录成功，并通过 `Set-Cookie` 写入 `miniapp_auth`

- `POST /api/auth/verify`
  校验当前 Cookie 是否有效；无效时返回 `401`

- 以下核心资源需要先通过鉴权才能访问：
  - `/generate`
  - `/edit`
  - `/api/history`
  - `/api/status/*`
  - `/api/system/diagnostics`
  - `/api/gpt/generate`
  - `/api/comfy/*`
  - `/image/*`
  - `/archive_image/*`
  - `/source_image/*`
  - `/editable_file/*`
  - `/google_outputs/*`
  - `/gpt_outputs/*`

## 配置方式

优先方式：在启动服务前设置环境变量：

```bash
export MINIAPP_ACCESS_PASSWORD='你的访问密码'
```

或者直接写入项目根目录的 `settings.json`：

```json
{
  "nano_banana_api": {
    "base_url": "https://your-provider.example/v1beta"
  },
  "miniapp_access_password": "你的访问密码"
}
```

可选：

```bash
export MINIAPP_AUTH_MAX_AGE=604800
```

默认 Cookie 有效期为 7 天。

## 运行诊断

- 桌面端 `/desktop.html` 左侧工具栏的“设置”按钮会打开只读诊断面板。
- 后端接口是 `GET /api/system/diagnostics`，需要先通过 Mini App 鉴权。
- 诊断只返回状态和路径信息，不返回 Telegram bot token、API key、访问密码、Codex token 或完整配置。

当前诊断覆盖：

- Telegram 配置与 `sendDocument` 发送方式
- Telegram initData / 访问密码鉴权状态
- Nano Banana / Google 兼容 API key 是否存在
- GPT local provider 的 Codex 登录态候选
- GPT browser fallback profile / user-data dir / CDP port
- 图片归档、远程源素材、`tasks.db` 路径可用性

## 说明

- 当前版本已支持 Telegram WebApp `initData` 验签；密码登录作为桌面端和非 Telegram 环境的备用入口。
- 如果公网 URL、bot 或 Web App URL 不变，不需要重新配置 BotFather。
