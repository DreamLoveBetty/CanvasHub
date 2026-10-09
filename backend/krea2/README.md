# Krea 2 · MLX component boundary

This domain integrates the pinned `avlp12/krea2_alis_mlx` revision
`3d01ab823cfd969298332c2f9540d4cc822c4450` without creating a second Python
environment.

## Ownership

- `contracts.py`: public request limits, build identities, export formats and
  normalization. Export formats do not change pinned downloadable builds.
- `edit_profile.py`: MLX-independent instruction-edit defaults and the v1.2
  reference fit/crop geometry shared by request validation and the worker.
- `environment.py`: read-only checks for the shared CanvasHub Python profile,
  pinned sources and local model files. It never imports MLX.
- `install.py`: one-time preparation. It checks out the pinned Krea source,
  extracts `mflux==0.18.1` as an audited source tree and installs only the small
  compatible extras into the **existing** `.venv`. It refuses dependency
  downgrades through a full environment constraint file.
- `lora_store.py`: validates and indexes `.safetensors` files directly from the
  managed LoRA folder while keeping content-hash IDs in saved workflows.
- `model_store.py`: owns the Base transformer catalog. It projects the two
  pinned built-ins and atomically published custom MLX builds through stable
  model IDs; full filesystem paths never enter canvas workflow state.
  The optional Mixed 4/8-bit built-in is listed only when ready, not as an
  uninstalled download placeholder. The default 8-bit first-run entry remains.
  Mixed conversion recipes, installed mixed checkpoints and existing model IDs
  are unchanged; hiding the placeholder does not delete any files.
- `comfy_fp8.py`: strictly recognizes ComfyUI tensor-wise scaled-FP8 E4M3FN
  triples (`weight`, scalar `weight_scale`, JSON `comfy_quant`) and decodes them
  one tensor at a time in the isolated converter child. Torch/MLX are never
  imported by its HTTP-process inspection path.
- `conversion_service.py`: owns the single durable conversion job, cancellation,
  progress and publication. It waits on the same neutral local accelerator lease
  as YuE and the other Mac-local runtimes instead of terminating active work.
- `converter_worker.py`: the isolated offline MLX quantizer. It strictly matches
  a complete Krea 2 Turbo transformer by tensor name and shape, converts float
  weights to BF16, optionally applies the pinned 8-bit or mixed-4/8 recipe at group size 64,
  then strictly reloads the produced artifact before it can be published.
- `runtime.py`: HTTP-process supervisor and JSON-lines adapter. It does not
  import MLX and shares `components/.local-inference.lock` with the other local
  inference domains.
- `worker.py`: the only process that imports MLX/Krea/mflux. One worker is reused
  for serial jobs and exits after an idle timeout. Inference is offline and the
  optional safety classifier is only loaded for jobs that enable it and remains
  fail-closed while enabled.
- `edit_mlx.py`: worker-only Krea 2 Identity Edit runtime. It injects the source
  twice, as grounded Qwen3-VL image/instruction features and as clean VAE
  reference tokens (`frame=1`) ahead of the noisy target tokens (`frame=0`). It
  reuses the prepared model, VAE, tokenizer and complete local Qwen checkpoint;
  it does not introduce ComfyUI, another service or another model download.
- `service.py`: bounded queue, uploads, task DB projection, daily archive,
  sidecars and `sendDocument` delivery.
- `routes/krea2_routes.py`: authenticated `/api/krea2/*` HTTP adapter.

Runtime/model/LoRA state lives under `APP_DATA_DIR/components/krea2` and
`APP_DATA_DIR/data/krea2`; source repository checkouts, weights, receipts and
user LoRAs are ignored runtime data, not application source. Put user LoRAs in
`APP_DATA_DIR/data/krea2/assets/loras/`. The directory is created automatically,
and the list endpoint scans direct child `.safetensors` files without a browser
upload step. Converted Base transformers live under
`APP_DATA_DIR/data/krea2/assets/base_models/<model-id>/`; local source files can
be addressed by absolute path or copied into `APP_DATA_DIR/data/krea2/imports/`
and referenced by filename. Source checkpoints are never copied into the model
library.

## Preparation

The base model is gated. The operator must first request/accept access to
[`krea/Krea-2-Turbo`](https://huggingface.co/krea/Krea-2-Turbo) for the account
used by `hf auth login`. The first **开始生成** action automatically starts the
required preparation, or it can be run from the command line:

```bash
.venv/bin/python -m backend.krea2.install --models 8bit
```

Canvas preparation skips the optional NSFW classifier while the node switch is
off. Turning it on prepares `Falconsai/nsfw_image_detection` before submission.
The CLI keeps its existing safe default; pass `--skip-safety` to omit that model.

`8bit` requires about 23 GiB for the transformer plus shared base components;
`mixed-4-8` can be prepared independently. All repositories and model listings
are pinned to immutable revisions. Every LFS-hosted base/safety weight and the
8-bit or mixed transformer receives a full SHA-256 check.

## Offline Base model conversion

Settings Center → **模型工具** lists direct `.safetensors` children of the
managed model import directory; the browser selects a filename rather than entering or
receiving a server-side path. The selected file must contain the complete Krea 2 Turbo
transformer. Supported source tensor dtypes
are FP32, BF16 and FP16. It also accepts ComfyUI tensor-wise scaled-FP8 E4M3FN
files when every FP8 weight has one finite positive scalar `weight_scale` and a
valid `comfy_quant` marker. Those weights are decoded to BF16 one tensor at a
time before applying the selected MLX recipe; other FP8, activation-quantized or
partially paired formats remain rejected. The converter accepts the native namespace and the known
`transformer.`, `model.diffusion_model.`, `diffusion_model.`,
`base_model.model.`, `model.` and `module.` wrapper prefixes. LoRA/delta files,
already-MLX-quantized artifacts, incompatible tensor names/shapes and unsupported
quantization layouts are rejected. V1 intentionally does not merge shards, import a full
Diffusers directory or translate an unrelated architecture.

The recipes are the pinned upstream `quantize_bulk` 8-bit and `mixed_4_8`
4/8-bit policies, both using MLX `nn.quantize` with group size 64. Publication
records source/output SHA-256 hashes and strict load/reload verification; it does
not claim the optional velocity-cosine quality benchmark from upstream release
validation. A converted scaled-FP8 manifest records its source format and marks
packed outputs as re-quantized; BF16 outputs are decoded, not re-quantized.
Neither can restore precision already lost by the community checkpoint.
Custom transformers reuse the official shared Krea 2 Turbo VAE,
text encoder and tokenizer. Selecting a custom model therefore prepares those
shared components with `--models none` but does not download another built-in
transformer.

`precision: "bf16"` exports only the Transformer without calling `nn.quantize`.
It writes BF16 tensors, records `group_size: null` / zero quantized Linear layers,
and validates the stored dtype/count and strict reload before publication. The
neutral `backend/local_image/safetensors.py` owns bounded header validation and
shape-based BF16 disk estimates without importing MLX. Source decoding, shape
matching and model instantiation remain in the existing domain worker.
The source hash + precision distinguish model IDs, so a BF16 export coexists
with an 8-bit export of the same source. Manifest discovery rechecks BF16 storage;
the worker uses upstream's existing BF16 Pipeline branch. Shared preparation
still runs with `--models none`, and the default built-in remains 8-bit. No
shared VAE, encoder, tokenizer, download pin or Python dependency is changed.

Conversion runs in the existing CanvasHub Python environment and pinned source
tree; no second venv or service is created. It first waits for an active YuE,
Krea, Topaz or ReShot task to finish, then exclusively holds
`components/.local-inference.lock`. New local-inference tasks wait until
conversion completes or is canceled. A warm Krea worker is unloaded only after
the lease is acquired to release unified memory. The converter child inherits
the live lease descriptor, so an unexpected server exit cannot release the
accelerator to a second local task while that conversion process is still alive.

## API

- `GET /api/krea2/status|catalog|lora-list|model-tools`
- `POST /api/krea2/prepare|upload|lora-import|lora-delete|generate|cancel`
- `POST /api/krea2/model-inspect|model-convert|model-convert-cancel|model-delete`

Task reads continue through the existing `/status/<task_id>` contract. JSON
fields are snake_case. Browser responses never include HF credentials, LoRA
paths, source checkpoint paths or full local configuration. The model-tools
response exposes only its two managed directories for local operator use.

Generation accepts `safety_enabled`. Canvas nodes persist it as a boolean and
default it to `false`; disabled jobs do not load, score or redact through the
NSFW classifier. Enabled jobs require the pinned classifier and record the
threshold and flagged count in task/archive metadata.

Generation also accepts the snake_case `aspect_ratio` field. The Canvas ratio
presets map to concrete multiple-of-16 `width`/`height` values, while direct
dimension edits are persisted as the matching standard ratio or `custom`.
Inference continues to use the normalized width and height as the authoritative
pixel dimensions; the ratio is retained in task and archive metadata.

Instruction editing is an explicit `mode: "edit"` request so the existing
text-to-image and classic img2img contracts remain unchanged. It requires one
`edit_image_upload_token` and one `edit_adapter_asset_id`; the edit adapter is
resolved server-side and occupies one of the four total LoRA slots. Optional
fields are `edit_adapter_scale` (default `1`), `reference_strength` (default
`4`), `grounding_px` (default `768`) and `fit_mode` (`fit` or legacy `crop`).
The browser stores only content-addressed asset IDs and uploads the connected
source through the existing authenticated image-upload adapter. The source,
adapter path and full local configuration never enter workflow state or API
responses.

The implementation intentionally preserves both conditioning paths used by the
community adapter: grounded Qwen3-VL supplies scene/subject semantics, while
clean VAE tokens supply appearance and identity. Loading the LoRA alone, or
running it through the existing strength-based img2img path, is not equivalent.
Turbo remains the current fast path (typically 8 steps, no CFG); deletion of
salient content is outside this first version because the community workflow
recommends Raw + CFG for that case. Third-party attribution and license copies
live under `backend/krea2/vendor/`.

Generation results are copied into `IMAGE_ARCHIVE_DIR/YYYY-MM-DD/` as original
PNG files. Each receives `.txt`, Obsidian `.md` and `.krea2.json` sidecars.
Optional Telegram delivery uses the existing uncompressed `sendDocument` path.
The worker records a bounded `generation_timing` contract with model loading,
non-denoise inference, denoising, image-save and total wall time. Only runtimes
that explicitly set `local_inference=true` receive phase rows in the asset UI;
remote/API assets use their task start/finish timestamps for total time only.

## Verification

The tracked regression suite uses synthetic safetensors and a fake runtime; it
does not require MLX, credentials or model weights:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m unittest tests.test_krea2_domain
node --test tests/test_krea2_canvas.cjs
```

Full validation additionally loads the prepared pinned model, generates a small
text-to-image sample, an image-to-image sample and a two-LoRA sample, while
holding the shared accelerator lease.

## Neutral infrastructure boundary (2026-10-01)

Krea retains its pinned source, quantization recipes, worker, model/LoRA directories,
public routes and exception contracts. Architecture-neutral JSON-lines supervision,
strict Comfy scaled-FP8 decoding, LoRA file indexing, MLX atomic save and authenticated
route construction now live under `backend/local_image`; Krea modules forward to those
helpers without maintaining another implementation. Qwen uses a separate source checkout
and model library, not Krea's prepared assets. The server explicitly injects idle-worker
unload ports into a coordinator used only while holding the shared accelerator lease.
