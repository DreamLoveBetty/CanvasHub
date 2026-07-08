# codex-image-runtime

Project-owned Codex image runtime for image generation, image editing, and
small Codex chat smoke tests.

This skill directly calls:

```text
https://chatgpt.com/backend-api/codex/responses
```

It does not require CLIProxyAPI and does not call a localhost reverse proxy.

## Features

- Direct Codex chat CLI.
- Direct `gpt-image-2` image generation.
- Direct `gpt-image-2` image editing with local image inputs.
- Default image quality is `high` when `--quality` is not specified.
- Automatic auth discovery from local Codex auth files.
- Automatic token refresh when the access token is expired or close to expiry.
- Clear upstream error reporting for `response.failed` and `response.incomplete`.
- 4K size mapping that respects the current longest-edge limit of `3840`.

## Auth

The scripts discover auth files in this order:

1. `CODEX_API_AUTH_FILE`
2. newest `~/.cli-proxy-api/codex-*.json`
3. `~/.codex/auth.json`

Example:

```bash
export CODEX_API_AUTH_FILE="$HOME/.cli-proxy-api/codex-your-account.json"
```

Do not commit auth JSON files. They contain access and refresh tokens.

## Install

```bash
python3 -m pip install -r backend/codex_image_runtime/requirements.txt
```

## Chat

```bash
python3 backend/codex_image_runtime/scripts/chat.py "Reply with exactly: pong" --model gpt-5.4-mini
```

## Generate Image

```bash
python3 backend/codex_image_runtime/scripts/generate_image.py \
  "simple red lantern on a plain dark table" \
  --size 4k \
  --ratio 16:9 \
  --bg opaque \
  --format png \
  --output /tmp/gpt_image_2_image.png
```

`--size 4k --ratio 16:9` maps to `3840x2160`.
If `--quality` is omitted, the CLI uses `high`.

## Edit Image

```bash
python3 backend/codex_image_runtime/scripts/edit_image.py \
  "make the background white" \
  --image /tmp/input.png \
  --size 1k \
  --output /tmp/gpt_image_2_edit.png
```

Image editing also defaults to `--quality high` when no quality is specified.

## Environment Variables

- `CODEX_API_AUTH_FILE`: explicit local auth file.
- `CODEX_API_BASE`: defaults to `https://chatgpt.com/backend-api/codex`.
- `CODEX_API_TIMEOUT`: request timeout in seconds, defaults to `900`.

## Local Checks

```bash
python3 -m py_compile backend/codex_image_runtime/scripts/*.py
```

## Safety

This project does not bypass OpenAI or Codex safety systems. If upstream rejects
a request, the CLI reports the upstream failure message and request id when
available.
