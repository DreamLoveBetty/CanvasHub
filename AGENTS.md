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
- Validate desktop UI changes against the served `/desktop.html` page when the change is visual or interaction-heavy.

## Storage, Provider, and Deployment Rules

- Generation outputs must remain recoverable from the configured archive and should keep sidecar prompt files when applicable.
- Preserve provider fallback semantics, especially Codex -> ChatGPT account-pool fallback and account-pool quota/verification handling.
- Docker deployment, desktop app packaging, frontend cache busting, and backend drain/restart are separate update models. Do not reuse Docker defaults as desktop app defaults.
- Runtime data and user-owned state must not be written only into disposable release/app directories when adding deployment or packaging flows.

## Test Rules

- Keep tests in `tests/` tracked by Git; do not commit `tests/__pycache__/` or generated test artifacts.
- Prefer standard-library `unittest` tests unless a new dependency is clearly justified.
- Import backend code via the `backend.*` package in tests, not old top-level module paths.
- When touching generation, provider routing, settings, auth, or desktop cache-busting, add or update the relevant regression test.

## Useful Checks

```bash
python3 -m py_compile server.py backend/api_client_gpt.py backend/provider_gpt_codex.py
PYTHONPATH="$PWD" python3 -m unittest discover -s tests -p 'test_*.py' -t .
curl --noproxy '*' -I http://127.0.0.1:18463
```
