# Krea 2 · MLX component boundary

Maintenance handoff: [signed ordinary-LoRA strength fix and Identity Edit interaction findings (2026-10-26)](../LORA_STRENGTH_HANDOFF_2026-10-26.md).

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

Ordinary LoRA strengths accept finite values from **-20 to 20**, including signed
sliders, in standard, edit and control modes. Canvas input and workflow reload use
the same normalization; the visible input is updated to the actual bounded value.
The dedicated Identity Edit adapter remains **0.01–2**, and the dedicated control
adapter remains **0–2**; neither inherits the ordinary-LoRA slider range.

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

## Experimental area control (2026-10-17)

The **Krea 2 区域控制** canvas node generates an EditUtils-compatible black RGB
control image with one or two `#FADBAE` ellipses at submission time. The six presets
are nominal summed area ratios, not stored example images: flat `.0149`, small
`.0294`, medium `.0322`, large `.0718`, huge `.1395`, gigantic `.1650`. Moving,
resizing and rotating markers persists normalized geometry. Overlapping/clipped
ellipses are rasterized as a union; actual pixel coverage is recorded separately.
An optional image connected to this node is only a local alignment underlay.
It is never uploaded as an edit source or included in the exported control image.

Connect **区域控制 → Krea 2**, and a text node to Krea 2. The typed edge switches
the existing Krea node to `control` mode, exposes a dedicated LoKr selector and
reserves one adapter slot (up to three ordinary LoRAs remain). The locally supplied
`breasts_control_lrzjason_20261015.safetensors` is recognized and recommended.
The original filename and content-hash ID remain unchanged; no model conversion
or additional environment is needed. Other direct LoKr files can be recognized
structurally, but that alone does not prove they were trained for this control
protocol. Standard generation and Identity Edit reject LoKr in the ordinary stack.

The existing authenticated `POST /api/krea2/generate` accepts:

```json
{
  "prompt": "clothed adult fashion portrait",
  "mode": "control",
  "control_adapter_asset_id": "<local content hash>",
  "control_adapter_scale": 1,
  "control_reference_kv_cache": false,
  "control_reference_size": 1024,
  "control": {
    "profile": "editutils-area-v1",
    "circles": [{"cx": 0.5, "cy": 0.48, "rx": 0.1, "ry": 0.08, "angle": 0}]
  },
  "width": 832,
  "height": 1248,
  "steps": 8
}
```

- `control_profile.py` owns validation, deterministic CPU rasterization and
  control-image preprocessing (reference longest edge, padding, fixed VL size).
- `lokr.py` owns bounded CPU inspection and explicit LyCORIS-to-Krea aliases.
  V1 accepts full 2D `lokr_w1`/`lokr_w2` pairs only, rejects decomposed/Tucker/
  DoRA/conv/mixed formats, and checks layer shapes again against the loaded Base.
- `lokr_mlx.py` owns reversible worker-local wrappers. It computes the direct
  Kronecker branch in factorized form rather than expanding ~25.6 GB of deltas.
  Direct full factors use the external strength without alpha/rank normalization.
  Wrappers are cleared in `finally`, including error/cancel paths; the ordinary
  LoRA and warmed Base lifecycle remain upstream-owned.
- `control_mlx.py` owns independent `[text, target, reference]` conditioning,
  zero-timestep reference spans and centre-aligned reference positions. It reuses
  `edit_mlx.encode_grounded_image` as an explicit shared vision port, without
  changing Identity Edit's sequence, sampler or default image label. Invariant
  text fusion/projection, initial reference projection, RoPE and zero-time
  modulation are evaluated once per image, after all adapters are applied.
- `control_attention_mlx.py` owns optional per-image `ReferenceKV` capture/reuse
  and native GQA attention/block math, also used without the KV cache. It never
  monkeypatches the model or changes the pinned vendor files. K/V stay at their
  original 12 heads rather than being expanded to 48 query heads. First-step
  post-QK-normalization/post-RoPE K/V are stored with compact buffers.
  Later steps omit reference queries/MLPs and
  concatenate the cached K/V. This freezes deeper reference features and is
  approximate, not equivalent to the full reference path. Caches are rebuilt
  for each image/seed and cleared in `finally`, including cancellation/errors.
- `service.py` resolves IDs, renders a per-job control image, queues through the
  existing shared accelerator lock, and archives the exact control PNG in
  `YYYY-MM-DD/.krea2-controls/<task-id>.png`. Existing output sidecars record its
  relative path, geometry, coverage, adapter identity/strength and timing.

This is **experimental area-conditioned generation**, not a local inpainting
mask. Existing photos + area control + Identity Edit are not validated together;
both client and server reject that combination rather than silently dropping a
photo. The optional guide image must connect to the control node, not to Krea 2.
The `control_reference_size` integer selects the internal VAE reference longest
edge: **1024 (unchanged default), 768, 512**. The latter two are experimental
conditioning trade-offs, not equivalent results. Output width/height and the
VL area-384 preprocessing are unchanged. The server rejects unsupported sizes,
non-integers and non-default sizes outside control mode. Per-image diagnostics
include `reference_size`, padded `reference_dimensions`, `reference_tokens` and
`target_tokens`; requested size is also saved in archive `parameters`.
Exact constant preparation is always enabled. The optional **参考 KV 加速** node
switch sends the strict boolean `control_reference_kv_cache` (default `false`,
control mode only); disabling it recomputes the complete reference block states.
Enabling it uses frozen-reference approximation without changing steps, geometry,
strength or output size. Archive `control_acceleration` records the actual cache
mode, capture/reuse counts and bytes for each image. No cache is reused across
images, tasks, models, prompts or adapter changes. No universal speed claim. User output dimensions remain authoritative,
so this is not claimed to be bit-identical to the author's Raw+Turbo Comfy graph.

Portable coverage: `tests/test_krea2_control.py` and
`tests/test_krea2_control_canvas.cjs`. Machine-only MLX algebra and fixed-seed
small/large clothed-portrait probes live under `tests/local/`; outputs stay under
ignored `tests/output/`. The smoke tests validate execution, not broad quality or
joint-edit compatibility.

The asset index explicitly excludes `.krea2-controls` from output discovery;
`rglob` alone does not hide dot-directories. Control batches allocate separate
conditioning/denoise/save progress windows so subsequent images do not reset the
visible progress bar. Synthetic tests cover both archive filtering and two-image
progress, as well as reversible bindings after success, exceptions and cancellation.

### Cache acceptance evidence (M2 Max, 96 GiB)

Machine-only probe: `tests/local/probe_krea2_control_cache_local.py`, actual user
8-bit community Base + direct control LoKr, 720×1280, ten steps, seed 7241 and a
clothed studio-portrait prompt. Test-only outputs/report under
`tests/output/krea2-cache-20261017/`:

| Path | Total seconds | Denoise seconds | Difference from original |
| --- | ---: | ---: | --- |
| Original recomputation | 344.52 | 338.41 | reference |
| Prepared constants, full reference | 421.79 | 410.98 | identical pixel hash, MAE 0 |
| Prepared constants + frozen-reference KV | 254.45 | 246.76 | pixel MAE 2.42/255; folds/detail change |

These are sequential samples, not a controlled thermal benchmark: original
step times drifted from ~30 to ~43 seconds. Exact preparation eliminates repeated
operations and preserves pixels but this run does **not** prove an end-to-end
speedup for that stage. KV-on was ~1.66× faster than the prepared/full-reference
run, with first step ~37 seconds and subsequent steps ~21–27 seconds. It captured
28 layers once and reused them nine times, with 396,361,728 cache bytes. Total
MLX peak allocation remained approximately 38.1 GB in this sample. It is not a
promise for all prompts/models/machine states, nor evidence of broad quality parity.

Representative real LoKr Q/K/gate/down-layer microprobes measured factorized
branches at ~19–28% of their corresponding Base projection time (not a percentage
of whole generation). A flattened-matmul alternative had no consistent advantage;
it stays test-only. No dense ~25.6 GB delta expansion or weight mutation was added.

### Native GQA / reference-size acceptance (2026-10-18)

On MLX 0.32.2 / the same M2 Max, alternating SDPA microprobes at 6,160 key
tokens, 48 query heads and 12 K/V heads measured native GQA about 3–4% faster
than explicitly repeated K/V, with zero output error. Tiny F32/BF16 transformer
tests preserve the original full-reference predictions; the actual ten-step
KV-on native/repeated comparison also produced identical pixel hashes.
However, sequential whole-image times were **212.03 s repeated vs 243.07 s
native**. This does not establish an end-to-end GQA speedup; machine-state
variation was not controlled. The change removes needless K/V expansion, not a
promise of a whole-image speed factor. Standard generation / Identity Edit do
not use this control-only attention implementation.

The same loaded 8-bit community Base, direct control LoKr, 720×1280 output,
ten steps, seed 7241 and **KV enabled** produced these single-sample results:

| Reference longest edge | Padded reference | Tokens | Generation seconds | Denoise seconds |
| --- | --- | ---: | ---: | ---: |
| 1024 | 576×1024 | 2304 | 243.07 | 233.05 |
| 768 | 432×768 | 1296 | 213.97 | 207.26 |
| 512 | 288×512 | 576 | 207.34 | 201.36 |

Generation timing excludes Base loading; these are sequential samples, not a
statistical benchmark. Relative to the native 1024 sample, 768/512 reduced time
by about 12%/15%. They are **not quality-equivalent**: visual inspection found
changed garment texture/folds at 768 and more visible pose/clothing/composition
changes at 512. Keep 1024 and KV-off as defaults; 768 is an optional trade-off,
512 a preview experiment. No claims about tiny-marker accuracy from this test.
Reports/images are local in `tests/output/krea2-next-round/`; use
`1024-clean/report.json`, not the initial `1024/` run whose recording mock
retained tensors and invalidated its timing/memory comparison.

### Joint-edit research closed (2026-10-18)

The user reports that the adapter author confirmed area control cannot be used
with Identity Edit, and explicitly ended this research. This is a closed work
item, not a pending integration task. Experimental joint/protected-repaint code
and artifacts have been removed; no production runtime imported them.

Keep independent area-control generation and Identity Edit unchanged, including
client/API/worker rejection of mixing them and `catalog.control.joint_edit=false`.
Do not remove those guards or restart the experiments based on older plans.
See [closure and handoff](JOINT_EDIT_RESEARCH_CLOSED.md) for the scoped decision,
retained findings, exact cleanup inventory and maintenance boundaries.
