---
name: codex-image-runtime
description: Project-owned Codex image generation and image editing runtime. Directly calls chatgpt.com/backend-api/codex/responses using local Codex auth files, without CLIProxyAPI or a localhost reverse proxy.
---

# codex-image-runtime

Standalone `gpt-image-2` command-line skill. It does not require CLIProxyAPI, does not call
`127.0.0.1:8317`, and directly uses local Codex login credentials.

## Commands

```bash
python3 backend/codex_image_runtime/scripts/chat.py "ping"
```

```bash
python3 backend/codex_image_runtime/scripts/generate_image.py \
  "simple red lantern" \
  --size 4k \
  --ratio 16:9 \
  --bg opaque \
  --format png \
  --output /tmp/gpt_image_2_image.png
```

```bash
python3 backend/codex_image_runtime/scripts/edit_image.py \
  "make the background white" \
  --image /tmp/input.png \
  --size 1k \
  --output /tmp/gpt_image_2_edit.png
```

## Auth

Auth file priority:

1. `CODEX_API_AUTH_FILE`
2. newest `~/.cli-proxy-api/codex-*.json`
3. `~/.codex/auth.json`

If the access token is expired or near expiry, the scripts refresh it with the
Codex OAuth client and write the refreshed values back to the same auth file.

## Environment

- `CODEX_API_AUTH_FILE`: explicit auth JSON path.
- `CODEX_API_BASE`: defaults to `https://chatgpt.com/backend-api/codex`.
- `CODEX_API_TIMEOUT`: request timeout seconds.

## Notes

- Image generation and editing default to `--quality high` when quality is not
  specified.
- `--size 4k --ratio 16:9` maps to `3840x2160`; the longest edge never exceeds
  the current `gpt-image-2` limit of `3840`.
- Safety rejections are not bypassed. `response.failed` and `response.incomplete`
  are printed with the upstream message and request id when present.
- This skill is direct CLI only; it intentionally does not expose a local
  OpenAI-compatible HTTP server.
