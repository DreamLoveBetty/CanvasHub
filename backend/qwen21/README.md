# Qwen-Image 2.1 · MLX integration boundary

## Design and installation order

1. Verify the existing CanvasHub interpreter; prepare an isolated, pinned MFLUX
   source checkout. Do not install or upgrade MFLUX, Torch, Transformers or MLX
   in the main environment.
2. Verify the reference-capable Heretic 8-bit checkpoint, then standard T2I,
   Viggle T2I and ordered one/two-reference edits in the same child interpreter.
3. Connect the bounded queue, task DB, shared accelerator lease, original PNG
   archive, sidecars and uncompressed Telegram delivery.
4. Connect the Qwen canvas model/API/controller. Use existing control tokens and
   task polling; keep progress outside the node body.
5. Add Qwen-specific conversion in Settings → Model Tools, then run regression
   and served-page checks. Publication requires complete name/shape matching and
   a strict reload of the exported transformer (8-bit or BF16).

## Ownership and dependencies

- `contracts.py` owns HTTP limits, presets, Transformer export formats and normalization. `profiles.py`
  owns pure sigma/reference geometry helpers; neither imports MLX.
- `environment.py` owns read-only interpreter/source checks. `install.py` owns
  pinned, checksum-verified downloads and receipts. `source_adapter.py` applies
  a small audited patch only to the Qwen checkout; Krea keeps MFLUX 0.18.1.
- `model_store.py` owns stable Base IDs, manifest discovery, shared Qwen
  components, Base retirement/default selection and atomic custom-model publication. It never exposes checkpoint
  paths to canvas state. `conversion_service.py` owns durable conversion state;
  `converter_worker.py` alone imports the quantizer/FP8 decoder.
- `runtime.py` supervises a persistent JSON-lines child. `worker.py` and
  `mlx_adapter.py` alone import Qwen/MFLUX/MLX. Runtime LoRAs are not baked into
  the quantized Base. Switching model/LoRA signatures reloads the child model.
- `service.py` owns uploads, its bounded task queue, task DB projection and
  result archiving. Task reads/cancellation still honor the existing task API.
- `text_encoder.py` owns the shared text-encoder variant record, in-place swap and
  rollback (no MLX). `bundle_import.py` is the operator CLI that verifies the pinned
  Turbo bundle and calls `model_store.publish_native` / `text_encoder.activate`.
- `backend/local_image` owns architecture-neutral checkpoint/LoRA and worker
  supervision helpers; it must not depend on Krea or Qwen.
- `backend/runtime_resources.py` owns the cross-domain POSIX lease and an
  explicitly assembled idle-worker release coordinator. Active YuE/other local
  jobs finish first; switching/quantizing releases idle Krea/Qwen workers only
  after acquiring the lease. No domain reads another domain's private state.
- `backend/routes/qwen21_routes.py` adapts authenticated `/api/qwen21/*` calls.
  `backend/server.py` only assembles dependencies and dispatches the router.
- `desktop-qwen21-model.js`, `desktop-qwen21-api.js`,
  `desktop-canvas-qwen21.js` and `desktop-qwen21-tools.js` own frontend state,
  boundary translation, node presentation/behavior and settings respectively.

## Immutable sources and data

MFLUX: `adcbe85975760d545ca142069713781929898be0` (includes editing LoRA).
Heretic: `vanch007/Qwen-Image-2.1-Heretic-mlx-8bit` revision
`6b81cbc376cb23069cc92df6084cf0f8cb9c9b88`.
Viggle default: v0.3 rank-256 from `Viggle/Qwen-Image-2.1-viggle-turbo`, revision
`009a44a895ef85f7e643c80fdca9543795248867`, 1,359,147,904 bytes, SHA256
`f06c266e04438b5272bdfb99410421d52a65d7a37f6f42aabc3cb1faf0142644`.
The previous v0.2.1 rank-128 file is retained separately. Each version/rank has
its own pinned filename/checksum/readiness; selecting one never silently uses another.

All user data is rooted at `APP_DATA_DIR`:

- `components/qwen21/source/mflux/`: worker-only source and patch receipt.
- `data/qwen21/assets/base_models/`: built-in/custom Base checkpoints.
- `data/qwen21/assets/loras/`: directly scanned ordinary LoRAs.
- `components/qwen21/adapters/`: pinned managed Viggle accelerator.
- `data/qwen21/imports/`: local complete single-file Transformer imports.
- `data/qwen21/jobs/`: uploads/job working files and bounded runtime logs.

The complete Qwen visual/text encoder, processor and RGBA VAE are shared by
Qwen models, not by Krea. Custom models store only their Transformer plus
configs and link the shared Qwen components without duplicating large weights.

## BF16 Transformer export

Settings → Model Tools accepts `precision: "bf16"` in the existing conversion
API; omission remains `8bit`. The domain service owns the selected precision,
disk precheck and leased job, and passes it explicitly to the worker and store.
The worker casts to BF16, skips `nn.quantize`, writes native MFLUX metadata
(`quantization_level: "None"`, not `16`), and strictly reloads all 297 tensors.
The neutral safetensors helper also checks actual stored BF16 dtypes/counts;
publication/discovery require zero quantized layers. Existing 8-bit verification
and immutable built-in file manifests are preserved.

Only the Transformer changes. The existing 8-bit text/visual encoder, processor
and selected VAE remain shared and unmodified; this is **not** the author's full
BF16 component bundle. The pinned MFLUX loader resolves precision per component,
and runtime LoRAs remain unbaked. No source pin or main-environment dependency is
upgraded. BF16 IDs end in `-bf16` and labels identify Transformer precision, so
the same-named 8-bit and BF16 exports coexist without changing workflow defaults.
Node labels use `名称（BF16）`; the internal MFLUX `transformer/0.safetensors`
layout is unchanged.
Supported scaled-FP8 sources decode to BF16 without another quantization pass;
their provenance remains recorded with `requantized: false`, not a claim that
source precision was recovered. Disk estimates are based on destination tensor
shapes (about 14.23 GB for BF16 weights), not the compressed source size.

## Built-in Transformer retirement

`model_store.py` owns `base_models/.selection.json`: deleting the built-in Base
requires a ready replacement (BF16 preferred), persists retirement/default first,
then removes only its pinned Transformer `.safetensors` files. Encoder, processor,
VAE and configs remain at their stable shared paths; other Base models and their
symlinks are not modified. No recursive deletion of the shared folder is allowed.
The last ready replacement cannot be deleted until another Base is available.

Shared readiness validates the pinned shared file subset, independently of the
retired Transformer. The original complete receipt remains readable; subsequent
shared repairs write `.shared-manifest.json`. `install --shared-only` actually
downloads only shared files and Transformer architecture config. Retirement also
forces shared-only preparation for direct CLI runs, preventing silent restoration
of the removed 8-bit weights. Source/dependency pins and first-install defaults
are unchanged.

Status, catalog and model-tools expose `default_model_id` and explicit
`model_replacements`; omitted generation/prepare Base IDs use that default.
An explicitly requested retired Base fails, never silently switches a submitted
job. The canvas applies replacement only to idle, live nodes and persists it via
the existing state port before constructing a request. Running jobs, unknown
missing custom models, archived tasks and workflow files not opened are untouched.
Deletion is blocked during preparation, conversion or tasks using that Base.
Portable retirement tests use small pinned fixtures; served-page checks cover
idle migration, short labels and no retired option, without creating inference jobs.

## Contracts and validation

Base mode allows 0 references for T2I or 1–10 ordered references for editing.
Viggle allows 1–3 edit references, fixed CFG=1, no negative prompt and adapter
strength=1. Step count is adjustable **5–60**, recommended 6, independently of
adapter version/rank. The official repository has no separate 8-step LoRA file.
Following its rule, custom schedules add/remove only the high-noise nodes and
retain `.875, .75, .5, .25`, then apply the resolution shift once, without terminal
stretching. A custom 9-step turbo run is not the author's 7-turbo + 2-base hybrid.
Standard steps remain adjustable 2–60, default 40. Legacy `viggle-6/8` workflow
states migrate to the default adapter while retaining their saved step count.
Reference encoding keeps a 1024² area budget independently of output size.
Outputs retain RGBA, `.txt`/Obsidian sidecars and `.qwen21.json` metadata;
`generation_timing` uses the existing local inference timing contract.

Conversion accepts complete Qwen-Image **2.1** Transformer FP32/BF16/FP16 and
strict Comfy tensor-wise scaled-E4M3FN. It rejects Qwen 1/old-edit architectures,
LoRA/delta-only files, arbitrary FP8 layouts, GGUF and already-MLX packed files.
FP8 → BF16 → MLX8bit is recorded as re-quantization; it does not restore source
precision. Qwen uses its own quantization predicate/group_size=64, not the Krea
recipe. Only the architecture-neutral FP8 decoder is shared.

Regression tests use tiny synthetic fixtures/fake workers and no credentials.
Machine-specific full-weight probes stay under ignored `tests/local/` and
`tests/output/`. Full validation is recorded separately from portable tests;
passing import checks alone is not a claim of successful image generation.

Ordinary LoRA names are normalized in the worker to the pinned upstream mapping;
PEFT/default and known Comfy prefixes are accepted only for supported Qwen targets.
Alpha/rank is folded into B in a separate cache copy, never into the Base or original
LoRA. Unsupported targets fail inspection instead of silently being ignored.

### Verified on the development Mac

The shared interpreter generated RGBA 512×512 images for standard 40-step T2I,
Viggle 6-step T2I, one-reference 6-step editing and two-reference 8-step editing.
A local **synthetic, full-shape** Comfy scaled-FP8 checkpoint (derived from the pinned
MLX Base) also passed 297-tensor matching, 228-linear quantization, strict 753-parameter
reload, atomic publication and 6-step inference. This is converter validation, not a
claim that an arbitrary community architecture/checkpoint has been validated. Local
probes and reports remain ignored under `tests/local/`, `tests/tmp/`, `tests/output/`.

## Independently selected VAE

`vae_store.py` owns immutable VAE copies, bounded header inspection, selection
and job snapshots. `vae_schema.json` records the 238 native tensor shapes from
the pinned Heretic RGBA VAE (no weights). Imports accept complete float
FP32/BF16/FP16 Qwen 2.1 VAE files with the original pinned configuration only;
other architectures, packed/FP8, wrong shapes and ambiguous layouts are rejected.
MFLUX's global `quantization_level=8` metadata is not proof the VAE is quantized:
the actual float tensors and the upstream `skip_quantization` flag are decisive.

`assets/vaes/imports/` is the user-facing inbox; `assets/vaes/<sha256>/` contains
an independent byte-identical checkpoint and verified configuration. The atomic
`assets/vaes/selection.json` selects the default for future Qwen jobs. No VAE is
selected implicitly on import. No existing Base/VAE links or immutable download
pins are edited. Restore an overwritten built-in VAE from a verified backup
before using the original/shared Base registration again.

`vae_runtime.py` supplies an ephemeral component view during pipeline loading.
Built-in selection returns the original model path unchanged; custom selection
links only that view's VAE component to the selected registered copy. The pinned
MFLUX reference/edit loader detects native metadata and otherwise applies its
own `vae_weight` layout transform exactly once, without quantization. No global
monkey patch or second implementation of that mapping is introduced. The view
is removed after eager initialization; generation does not read that directory.

Selection is copied into each queued worker spec. Public task params/sidecars
record VAE ID/name/format/SHA256, never internal checkpoint paths. Worker cache
signatures include VAE identity; switching invalidates the pipeline, changed or
missing weights fail rather than silently falling back. New protected
`/api/qwen21/vae-import` and `/api/qwen21/vae-select` routes live only in the Qwen
router; existing model-tools GET includes VAE options/inbox/selection/errors.
MLX remains worker-only. Settings → Model Tools owns the selection UI, through
`desktop-qwen21-api.js` and `desktop-qwen21-tools.js`; no extra node height or
changes to Krea/YuE, Telegram delivery, Base conversion or inference environment.

## Official Turbo Base and shared BF16 text encoder

Source: `vanch007/Qwen-Image-2.1-Turbo-Heretic-mlx-bf16` revision
`1ac68b7ede726b22ea3ace1fa6f03062450e4649` (official Qwen-Image-2.1-Turbo DiT,
Heretic text encoder, original VAE; native MFLUX BF16). `turbo_bundle_files.json`
pins the 20 used files (size + SHA256/blob id). Import from a local download:

```bash
.venv/bin/python -m backend.qwen21.bundle_import --source <downloaded repo directory>
.venv/bin/python -m backend.qwen21.bundle_import --restore-text-encoder   # rollback
```

It refuses while any Qwen task is queued/running, never modifies the source and
uses APFS clones (`cp -c`) where possible. Restart the backend after code changes;
data changes are picked up without a restart.

- **Transformer** → Base `qwen-image-2.1-turbo-heretic-bf16`, manifest
  `source_format: "mflux-native"`, `sampling: "turbo-8"`. Readiness checks the 297
  raw tensor names/shapes as unpacked BF16 across all shards (no strict-reload claim:
  bytes are proven by pinned checksums instead).
- **Preset `turbo-8`** («Turbo · 8 步») is a distilled schedule, not an adapter. It
  uses the checkpoint `sample_sigmas` verbatim (its scheduler has
  `use_dynamic_shifting=false, shift=1.0`: no resolution shift, unlike Viggle), fixed
  8 steps, CFG=1, no negative prompt, up to 10 references. A `turbo-8` Base accepts
  only this preset and this preset requires such a Base (service + canvas enforce
  both); no Viggle file is needed or downloaded.
- **Text encoder**: the bundle encoder is the unquantized source of the shared 8-bit
  Heretic encoder (dequantized cos ≈ 0.99997), so it replaces it for *all* Bases.
  `shared/text_encoder` is swapped in place; the 8-bit copy moves to
  `.text_encoder-8bit-backup/`; `.text-encoder.json` proves the BF16 files and
  replaces the 8-bit pins for readiness. `generation_head.safetensors` (restored
  `lm_head` + final norm) is excluded and removed from the index: the pinned loader's
  strict check rejects those keys and image generation never reads them. Shared
  preparation skips `text_encoder/*` while the record exists; a changed file fails
  closed. Without the backup (it may be deleted to save 8.2 GB), returning to 8-bit
  means removing the record and `text_encoder/`, then re-running shared preparation.
  Worker cache signatures include the encoder index, so a warm pipeline
  reloads after a swap. Task params record `text_encoder`.
- VAE/processor in the bundle are tensor/byte-identical to the shared ones and are
  not duplicated; the independently selected VAE still applies.
- Measured on the development Mac (M-series, 96 GB): BF16 Transformer + BF16 encoder
  peak ≈ 46 GB; 1024² T2I ≈ 85 s, 832×1248 ≈ 67 s, one-reference edit ≈ 166 s.
