# AGENTS.md - tg-mini-app-img-gen

## Every Session

Before changing code here:

1. Read `SOUL.md`
2. Read `USER.md`
3. Read `memory/YYYY-MM-DD.md` for today and yesterday if they exist
4. Read `MEMORY.md`

## What This Project Is

- Independent Telegram Mini App for image generation, editing, and Telegram delivery
- Main HTTP entrypoint: `server.py`
- Runtime watchdog: `watchdog.sh`
- Desktop UI is served from `desktop.html`
- Source of truth is `/Users/huangjiahui/Projects/tg-mini-app-img-gen/`

## Working Rules

- Preserve uncompressed Telegram delivery. Image results should continue to go through `sendDocument`, not compressed photo upload.
- Preserve the save-to-`IMAGE_ARCHIVE_DIR/YYYY-MM-DD/` pattern and prompt sidecar files when touching generation flows.
- Treat fallback chains as production-critical, especially Codex -> account-pool fallback.
- Frontend desktop changes usually require cache-busting `desktop.html` asset version strings.
- `settings.json` is local config and may contain secrets. Do not commit or expose it.
- Do not use the older `~/.openclaw` mirror as the primary working tree for this project.

## 新功能与模块边界规则

- 新增功能前，先明确职责归属、需要新增/扩展的模块、对外接口、状态所有权、依赖方向和验证范围；先规划边界，再实现，不采用“先堆进主文件，以后再拆”的方式。
- 有独立职责或独立生命周期的新能力，应在对应领域新增模块。属于已有模块职责的功能可以原位扩展；不要机械地每个按钮/函数建一个文件，也不以固定行数作为拆分目标。
- 后端继续区分 HTTP 适配、业务服务、Provider/Runtime 与存储；前端继续区分状态、API 适配、领域控制器与展示。不要把已有领域模块变成接收所有新功能的新单体。
- `backend/server.py` 与 `frontend/scripts/desktop-canvas.js` 只增加必要的初始化、依赖装配、路由/事件分发、共享状态协调和兼容接口；新增具体业务逻辑放在所属模块，兼容转发中不得再维护第二套实现。
- 跨模块协作使用明确接口和显式依赖，不绕过模块读取私有状态、不复制共享状态，也不引入反向依赖或隐式全局容器；保留工作流状态替换、异步返回值及原有 API 契约。
- 新增模块时同步更新模块边界说明和装配/加载顺序，按下方 Test Rules 补充局部及跨模块回归。桌面 JS/CSS 变化继续处理缓存版本，交互变化验证实际服务页面。
- 保持个人/小团队、自包含、低维护和低运行依赖定位；新增代码模块不等于必须新增服务进程、框架或部署单元。

## API and Interface Rules

- New JSON APIs should use `/api/<domain>/<action>` style names unless preserving an existing public route.
- Do not add desktop-only generation APIs. The desktop client is an adapter over the existing backend flows.
- Backend request/response JSON fields should be `snake_case`; frontend state may use `camelCase`, but adapter code must translate at the boundary.
- Protected endpoints must use the existing auth path and frontend requests should go through `auth-api.js` / `desktop-api.js`, not scattered raw `fetch` calls.
- Never return secrets to the frontend: API keys, Telegram bot token, access password, Codex tokens, account-pool auth key, and full local config stay server-side.

## Frontend Design Rules

- Desktop UI class names should use the `desk-` prefix and avoid overriding mobile/common selectors such as `.sidebar`, `.menu-card`, or `.settings-overlay`.
- Desktop visual tokens belong under `.desk-app` or `:root`; do not leak desktop-only theme rules into the mobile Mini App.
- Keep desktop frontend logic in `frontend/scripts/desktop-*.js`; keep mobile/classic/cinematic logic in their existing modules unless intentionally shared.
- Update `frontend/desktop.html` asset `?v=` strings whenever desktop JS/CSS behavior or visuals change.
- After bumping `?v=` keys, record them with `(cd frontend && npm run -s assets:record)`; `frontend/asset-versions.lock.json` lets `npm run check` and `tests/test_asset_versions.cjs` fail any changed asset whose key was not bumped. Feature tests must not pin key strings — use `hasCacheKey()` from `tests/asset_keys.cjs` (or a `?v=` presence regex in Python) plus load-order assertions.
- Validate desktop UI changes against the served `/desktop.html` page when the change is visual or interaction-heavy.
- Do not let dead CSS accumulate. To change a style, edit or delete the existing declaration in the file that owns it (layout in the domain `*-geometry.css`, paint in the domain theme file or `desktop-tokens.css`) instead of appending a later or more specific rule that overrides it. Do not raise specificity or add `!important` just to win the cascade.
- When an override is genuinely needed (theme, state, `@media`, interaction), remove in the same change any declaration it leaves without effect. When a component, class, or state is removed, remove its CSS rules too (search every stylesheet for the selector).

## Storage, Provider, and Deployment Rules

- Generation outputs must remain recoverable from the configured archive and should keep sidecar prompt files when applicable.
- Preserve provider fallback semantics, especially Codex -> ChatGPT account-pool fallback and account-pool quota/verification handling.
- Docker deployment, desktop app packaging, frontend cache busting, and backend drain/restart are separate update models. Do not reuse Docker defaults as desktop app defaults.
- Runtime data and user-owned state must not be written only into disposable release/app directories when adding deployment or packaging flows.

## Test Rules

- Stable, reproducible regression tests and their minimal synthetic fixtures may be versioned under `tests/`. Before including them in a commit, verify they pass in an isolated environment, use project-relative paths, and do not depend on real credentials, personal files, or production services.
- Keep temporary probes and machine-specific/manual checks under `tests/local/`, `tests/manual/`, or in files ending with `_local.py`, `_local.js`, `_local.cjs`, or `_local.mjs`. Existing `_local` scripts remain local; do not bulk-promote them without reviewing their portability and dependencies.
- Keep generated reports, screenshots, traces, and scratch data under the ignored `tests/output/`, `tests/artifacts/`, `tests/reports/`, `tests/test-results/`, `tests/playwright-report/`, `tests/coverage/`, or `tests/tmp/` directories. Never commit `tests/__pycache__/`, real account data, or generated test artifacts.
- Permission to version regression tests is not permission to stage, commit, or push automatically; do those only when the maintainer requests them.
- Prefer standard-library `unittest` for local tests unless a new dependency is clearly justified.
- Import backend code via the `backend.*` package in local tests, not old top-level module paths.
- When touching generation, provider routing, settings, auth, or desktop cache-busting, add or update regression coverage when useful. Prefer a reproducible test suitable for version control; keep exploratory or environment-dependent checks local.

## Useful Checks

```bash
python3 -m py_compile server.py backend/api_client_gpt.py backend/provider_gpt_codex.py
PYTHONPATH="$PWD" python3 tests/run_regressions.py
PYTHONPATH="$PWD" python3 tests/run_regressions.py --scope local
node tests/run_node_regressions.mjs            # stable Node suite; never glob tests/test_*.cjs by hand (pulls in *_local probes)
node tests/run_node_regressions.mjs --scope local
(cd frontend && npm run -s check)              # build fingerprint + asset cache keys
(cd frontend && npm run -s assets:record)      # after bumping ?v= keys
curl --noproxy '*' -I http://127.0.0.1:18463
```
