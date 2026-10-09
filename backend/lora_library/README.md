# Shared local-first LoRA library

This domain owns descriptive metadata, previews and optional online enrichment.
It does not own model weights, generation jobs, MLX, conversion or the accelerator
lease. No new environment, service process or package dependency is required.

## Ownership and assembly

- `contracts.py`: bounded descriptive fields and explicit trigger-word state.
- `repository.py`: SQLite records, per-engine membership, manual revisions and
  preview references. Connections always close, including failed transactions.
- `previews.py`: bounded raster validation, normalized image/thumbnail copies,
  ownership validation and remote-only cache cleanup.
- `service.py`: catalog reconciliation, local sidecars, field precedence, manual
  operations and a serial, non-blocking metadata-sync thread.
- `civitai.py`: replaceable SHA256/version lookup and bounded HTTPS downloads.
  Does not import generation services or upload weights/prompts.
- `routes/lora_library_routes.py`: existing authenticated HTTP transport only.
- `server.py`: injects each engine's `library_snapshot`, resolver and guarded
  deleter, excludes managed Qwen acceleration adapters, and binds the router.

Dependency direction is HTTP → service → repository/previews/provider. Catalog
callbacks point to public engine ports; the library never imports server state.
The frontend's matching card is descriptive, **not** proof of cross-engine
compatibility; final addition still passes the existing engine file catalog and
node limits. Inference requests retain `asset_id` and scale, not filesystem paths.

## Persistence

Under `APP_DATA_DIR/data/lora_library/`:

- `library.db`: manual/local/remote fields kept separately, SHA256 identity,
  per-engine availability, exact-version binding and sync status.
- `images/`: independent user-uploaded, asset-copied and local-sidecar previews.
- `cache/`: replaceable remote previews only.
- `civitai-key.json`: optional server-only credential, atomic mode-0600 write.

Original Krea/Qwen LoRA directories remain unchanged. Filename changes preserve
metadata via the full content hash; changed contents receive a new identity.
Missing files retain their information and can be filtered. Weight deletion is
explicit and delegates to the engine's queued/running-task guard. It is distinct
from removing a LoRA from a node or deleting its copied preview.

Effective fields: **manual > local sidecar/header > remote > filename fallback**.
Empty trigger words and `none` (confirmed unnecessary) are meaningful manual
values. Resetting selected manual fields exposes the underlying automatic values.
Local `.lora.json`, `.civitai.info` and explicit header trigger fields are read;
training-tag frequency is never treated as a trigger list. A sibling
`.preview.png/.jpg/.webp` or `.png/.jpg/.webp` is imported as a local preview.

Example `Style.lora.json` beside `Style.safetensors`:

```json
{"name":"My style","trigger_words":["My Phrase"],"trigger_status":"provided","tags":["portrait"],"recommended_scale":0.8}
```

## Transport and failure semantics

Authenticated GET: `/api/lora/list`, `/detail`, `/preview`, `/settings`,
`/sync-state` (each under `/api/lora`). POST: `update`, `preview-import`,
`preview-delete`, `bind-source`, `sync`, `settings`, `clear-cache`, `delete-weight`.
JSON uses snake_case. Update requires the last manual `revision`; a stale edit
returns 409 rather than overwriting another window. Image upload is bounded raw
bytes, addressed by asset ID; preview reads accept opaque IDs, never local paths.

Civitai enrichment is opt-in (`auto_sync=false` initially). Manual sync works
without a key where the remote endpoint permits it. Hash lookup verifies the full
file hash; a user-supplied specific version is marked as a manual association.
Only metadata and up to four raster examples are fetched, never model weights.
Known API/image hosts and every redirect are validated; credentials go only to
the API host. Both `image.civitai.com` and its `blobs-b2.civitai.com` original-image
redirect target are allowed by exact HTTPS host checks, not a wildcard. Version
JSON is bounded at 8 MiB to accommodate embedded example workflows; these large
workflow fields are not persisted. Individual images remain bounded at 16 MiB.
Sync reports example totals/failures and sanitized reasons, distinguishing an
empty upstream gallery from a download failure. Errors, 404, 403, rate limits and interrupted sync are recorded
without affecting inference or removing manual data. A restart does not replay
an interrupted sync automatically. Cached data remains usable offline.

The static-file allowlist does not expose `data/` or this credential file. Public
settings report only whether a key is configured. Clearing remote cache leaves
user examples, fields and original generated assets intact.

## Verification

Portable offline regressions: `tests/test_lora_library.py` and
`tests/test_lora_library.cjs`. They use synthetic weights/images and fake remote
responses, not personal files, real API keys or generation. Served-page QA uses
isolated API fixtures in ignored `tests/local/`, `tests/tmp/`, `tests/output/`.
Desktop HTML cache versions and frontend build/check are part of deployment.
