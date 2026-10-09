# Topaz Video local runtime (separate video domain)

The Canvas Topaz Video domain consists of `catalog.py` (model metadata),
`contracts.py` (path-free public requests), `features.py` (composable filter /
encoding contracts and offline capability inspection), `pipeline.py` (pure
multi-pass command planning), `service.py` + `storage.py`
(serialized durable jobs), `runtime.py` (offline subprocess lifecycle), and
two explicit provisioners. The existing `mini_runtime.py` and `provision.py`
remain an isolated Mini experiment, not an enabled production route. No code
imports the Gigapixel image runtime or reaches into its model directory.

## Machine-local stages

The runtime is rooted at the app data `components/topaz-video/` directory:

* `precise/` — independent Neuroserver/MLX stage and installed `slp26`
  weights. Only **Starlight Precise 2.6** has a verified 2× export on this
  machine. The installed `slp-2.5.json` points to the `slp26` package, so
  Precise 2.5 is **not** exposed as a separate available model.
* `conventional/Contents/` — independent FFmpeg/CoreML engine and weight stage with
  complete downloaded bundles for Proteus v4, Nyx v3, Theia Fine Tune
  Fidelity v4, Iris v2, Rhea v1, Artemis HQ v12, Gaia HQ v5 and Gaia
  Animation v1. The downloaded camera-pose support networks are staged but
  are not presented as standalone enhancement choices. Production execution also references the
  current machine's activated Topaz Video `license.lic` metadata directory in
  place. The license file is not copied, parsed by CanvasHub, returned by an
  API, or written to task logs. The previously exposed variants plus Iris v2 1× passed
  an owned-license, no-watermark 4-frame 256px synthetic export on this Mac. This is an
  execution smoke check, not long-video/visual-quality acceptance. Current conservative scale
  lists reflect the concrete CoreML files found locally: Proteus `[1,4]`,
  Nyx `[1,2]`, Theia `[1,2]`, Iris `[1]`, Rhea `[1,2,4]`, and Artemis/Gaia/Gaia
  Animation `[2]`. Only the previously tested variants are marked
  `verified`. A model/scale completed through the production task service is
  also promoted after its result has passed the same no-watermark provenance
  gate; failed, cancelled and legacy results never affect the catalogue.
* `mini/Contents/` — the earlier isolated Mini stage. On this Mac/macOS 27,
  Mini produces no first frame in the documented bounded probes, so `status`
  always disables it even when `provision.inspect_stage()` returns ready.
* `precise/models/hyp-2/` — the downloaded Hyperion package is copied beside
  the Precise model for isolation. Hyperion 2 is now exposed as an independent
  SDR-to-HDR filter, not as an enhancement-model alias. Its native output is
  ACES2065-1 EXR. The imported `oiiotool` performs the ACES 2.0 / 1000-nit
  Rec.2020 PQ display transform; FFmpeg converts the PQ RGB samples to limited
  BT.2020 YUV and encodes HEVC 10-bit. Setting HDR tags on an SDR movie is not
  used as a substitute. Readiness requires the recorded 43-blob package, the
  verified Neuroserver and the intact, executable colour-conversion helper.
* Optional conventional filter bundles are independently inspected: Chronos Fast
  3 / Chronos 2 / Apollo 8 / Apollo Fast 2 for interpolation, Themis 2 for motion
  deblur, CPE 2 for camera estimation, Refine 2 for full-frame stabilization, and
  IFI 1 plus Chronos Fast for rolling-shutter / jitter correction. Nyx 3 can run
  independently before the selected enhancement model. Descriptors alone never
  make a filter available. Missing optional bundles do not disable unrelated
  enhancement models.

Provisioning is an **explicit offline operator action**, never performed in
request handling or process startup. A source can be an installed app during
import; **execution** uses imported engine/weight paths, disables model
downloads, and does not start the GUI process. Conventional execution must
also find a valid current-machine license directory. macOS defaults to
`/Applications/Topaz Video.app/Contents/Resources/models`; an authorized
operator-managed location can be selected with
`CANVASHUB_TOPAZ_VIDEO_LICENSE_DIR`. Existing stages are never overwritten. The precise import accepts
the previously isolated/tested source tree; it does not patch the engine:

```bash
python3 -m backend.topaz_video.provision_local precise \
  --source /absolute/path/to/previously-validated/standalone \
  --stage /absolute/path/to/components/topaz-video/precise \
  --ffprobe-source /absolute/path/to/local/ffprobe
python3 -m backend.topaz_video.provision_local conventional \
  --source '/Applications/Topaz Video.app/Contents' \
  --stage /absolute/path/to/components/topaz-video/conventional/Contents
python3 -m backend.topaz_video.provision_local sync-conventional \
  --source '/Applications/Topaz Video.app/Contents' \
  --stage /absolute/path/to/components/topaz-video/conventional/Contents
python3 -m backend.topaz_video.provision_local sync-neuro \
  --source '/Applications/Topaz Video.app/Contents' \
  --stage /absolute/path/to/components/topaz-video/precise
python3 -m backend.topaz_video.provision_local validate-conventional \
  --stage /absolute/path/to/components/topaz-video/conventional/Contents \
  --evidence /absolute/path/to/tests/output/topaz-video-runtime-authorized-20260925
```

All sync operations use an explicit allow-list, per-file atomic replacement,
and never copy `license.lic`. For conventional models the allow-list is family based:
in addition to the minimum required bundle, every locally installed top-level `.tz3`
whose stem belongs to a declared enhancement or optional filter family is imported together
with its same-stem CoreML cache. This prevents portrait/landscape tile variants such
as `384x672` from being omitted while still excluding unrelated support networks and
license files. The optional bundled `oiiotool` is imported with the existing
framework closure and its size is recorded separately. Dynamically discovered variants are recorded in the stage manifest and
become part of its integrity check. Both stages audit internal symlinks and record
immutable model-file sizes.
Precise also records the exact tested engine hash. Mutable compiled CoreML
caches are not used as the readiness signal. `status.models[]` separately
reports `available` (resource-complete and an activated local license context
is discoverable, can submit) and `verified` (an authorized local end-to-end
short-video export was observed), with a reason and supported
scales. `verified_scales` records the exact tested multipliers. The model-level
badge becomes verified after at least one supported multiplier passes; untested
multipliers are called out in the reason and should first use a short preview.
These are **not** claims about long-video throughput, quality, or
another host. The explicit validation command probes the five finished MP4s
and their completion logs, then writes a local `local-validation.json` tied to
the stage manifest, machine, and macOS version. Validation schema 2 additionally
requires every log to contain an owned-license checkout, contain no watermark
fallback marker, and carry the runtime's per-result provenance record. Copying the conventional stage
to another machine does not preserve its short-export `verified=true` flags;
the Precise flag refers to the exact previously tested engine build, not a
fresh per-host performance benchmark.

## Task contract

Protected endpoints follow `GET /api/topaz_video/status`,
`POST /upload?name=...` (video bytes, maximum 200 MiB), `POST /submit`,
`GET /job?id=...`, `POST /cancel` with `{ "id": "..." }`, and
`GET /source?id=...` / `/artifact?id=...&name=...`.

`submit` accepts
`{asset_id, model, scale, task_kind, start_seconds, max_seconds, ...model_parameters}`.
The legacy request remains valid unchanged. Optional processing fields are:

```json
{
  "enhancement": true,
  "filters": {
    "denoise": {"noise": 0.4, "details": 0},
    "stabilization": {"mode": "auto_crop", "strength": 6, "rolling_shutter": false, "reduce_jitter": 0},
    "motion_deblur": {"model": "thm-2"},
    "interpolation": {"model": "apo-8", "fps": 60, "slowmo": 2, "rdt": 0.01},
    "hdr": {"model": "hyp-2", "strength": 1}
  },
  "encoding": {"codec": "hevc10", "bitrate_mbps": 0, "audio": "aac"}
}
```

Omit a filter to disable it; `enhancement:false` runs filters/encoding without
the selected enhancement model and requires `scale:1`. Encoding supports
`h264`, `hevc`, `hevc10`; `bitrate_mbps:0` delegates to the encoder; audio is
`aac` (192 kbps) or `mute`. HDR requires `hevc10`, with strength `0.7/1/1.3`.
Interpolation accepts `fps:0` (source rate) or 1–120, 1–16× slow motion, and
native duplicate-frame threshold −0.01–0.2. All paths/model command arguments
are selected server-side; unknown fields, unavailable models and invalid
combinations fail before queueing and are rechecked before GPU acquisition.
`status.capabilities` is separate from enhancement `models`; `processing_ready`
and `encoding` declare the filter-only / encoding contract.

`task_kind` is `export` by default and may be `preview`. `start_seconds=0` is the
default; `max_seconds=0` means process from the start point to the end and is not
valid for a preview. A preview must supply a positive duration up to 600 seconds.
The runtime converts the time range to bounded frame indices, seeks source audio to
the same start and records output dimensions/duration in the completed job. Conventional
preview/export ranges must contain at least four frames. The conventional temporal
filters may accept a shorter command but produce no frames, so the runtime rejects such
requests before inference instead of returning a misleading conversion failure.
The grain-size parameter `gsize` accepts `0` (automatic) or an integer from `1` to `5`;
the native filter advertises the numeric range but fails on non-zero fractional values,
so both the API contract and desktop controls enforce the effective integer domain.
Conventional
range jobs use a bounded two-second model pre-roll plus output-side exact seek; this avoids
the detached TVAI filter's short-GOP empty-output bug without enhancing the whole prefix of
a long source. There is
no silent 30-second truncation. The model parameters returned in
`status.models[].parameters` are validated against per-model bounds and are
neutral values (`0`) by default, **not** official recommended presets.

Advanced tasks first prepare exactly the selected clip, then estimate camera
motion, stabilize / deblur / denoise, enhance, interpolate, transform HDR, encode
and restore audio. `pipeline.py` owns only the plan, not another scheduler or
subprocess implementation. The existing runtime applies cancellation, timeouts,
per-pass license / success gates and shared GPU ownership to every pass. Source
selection stays in source seconds; frame counts and audio duration reflect the
output FPS and slow-motion multiplier. Native interpolation's missing final
successor is padded by one source frame and bounded to the exact expected
output frame count. Audio uses chained `atempo` filters to retain pitch.
Full-frame stabilization uses learned edge filling; automatic crop is scaled
back to the selected output dimensions. HDR needs at least five input frames.
Job-local intermediates are removed on success, cancellation or failure, with
an up-front disk-space estimate for large processing chains. Final publication
checks frame count, dimensions, rate and HDR PQ / BT.2020 / 10-bit metadata.
Filter-only tasks never mark an unrun enhancement model as verified.

The service owns a SQLite job record, an in-process serial queue, an OS file
lease to reject a competing service instance, task cancellation, and restart
recovery (`interrupted`). The subprocess runtime also acquires the shared
`components/.local-inference.lock` GPU lease used by other Mac-local domains.
It kills the entire process group on cancel/timeout, bounds logs, parses live
progress, validates dimensions/frame counts, remuxes the source audio when
present, and publishes one `result/enhanced.mp4` atomically. Audio remuxing pads
short AAC tails before applying the video-length cutoff, so sub-frame audio/video
duration differences cannot drop the final enhanced frame. Conventional jobs
fail closed when an owned-license checkout is not observed or when the engine
reports any watermark fallback. The service additionally requires
`result/provenance.json` with `watermark_verified=true` before exposing an
artifact URL, so a rejected result cannot flow to downstream canvas nodes. Runtime logs and
model-stage files are ignored local state; the validated result is served by
the artifact route and can be ingested by the canvas asset flow.

Portable regression tests (no model inference):

```bash
PYTHONPATH="$PWD" python3 -m unittest \
  tests.test_topaz_video_domain tests.test_topaz_video_provision tests.test_topaz_video_mini_runtime
PYTHONPATH="$PWD" python3 -m unittest tests.test_topaz_video_pipeline
```

Model downloads are not a request/startup side effect. An operator may explicitly
download missing bundles using the activated Topaz application's model download
mechanism, then run the sync commands above. The 2026-10-05 approved local
completion used Topaz's own FFmpeg `download=1` mode with its in-place license
metadata and independent model-data directory. Production plans always use
`download=0`; no third-party model mirrors or license-file copies were used.
Native filter help is authoritative for the installed engine's numeric contract.
Relevant documentation: [stabilization](https://docs.topazlabs.com/video-ai/filters/stabilization)
and [OpenImageIO sequence / colour transforms](https://openimageio.readthedocs.io/en/latest/oiiotool.html).

### Local validation evidence

The independent Precise 2.6 stage previously produced an 8-frame synthetic
512→1024 export in about 66 seconds, and a 15-frame face excerpt of
`清冽苔原.mp4` at 1080×1920→2160×3840 in 708.15 seconds. Reports are in the
ignored local paths `tests/output/topaz-video-isolation-20260924/REPORT.md`
and `tests/output/topaz-video-qinglie-20260925/REPORT.md`. The short real
excerpt visually improves eyes/hair but does not establish long-video quality
or production speed. Authorized conventional checks are in ignored
`tests/output/topaz-video-runtime-authorized-20260925/`: Proteus v4 at 1× and 4×,
Nyx v3 at 1× and 2×, Theia v4 at 1×, and Iris v2 at 1× each exported 4 frames at the
expected dimensions after an owned-license checkout with no watermark fallback
markers. Iris v2 also processed a 30-frame 1080×1920 excerpt with
`preblur=0.75`, matching the failed task's input format and parameter. A real
face frame was also checked with the same detached engine and
weights plus in-place license context and contained no central Topaz watermark.
The production runtime then processed a one-second, 30-frame real-video excerpt
with Proteus v4 1× in 10.193 seconds, restored its source audio, and a middle
frame was visually confirmed free of the central watermark. Evidence is under
the ignored `tests/output/topaz-video-real-authorized-20260926/` directory.
The local `verified=true` flags reflect only these bounded exports, not real
footage quality or production speed.

Aspect/variant regression on 2026-09-27 exercised every exposed conventional
model/scale combination against four-frame landscape and portrait clips: 13
model/scale combinations × 2 orientations, 26/26 successful. The ignored local
summary is `tests/output/topaz-video-aspect-matrix-20260927/all-models-4f-e83eb04e/summary.json`.
A bounded landscape Gaia Animation run also succeeded after importing its `384x672`
variant and normalizing `gsize`. This matrix verifies runtime routing and output
construction only; it is not a visual-quality or long-video performance benchmark.

### 2026-10-05/06 processing completion

The approved native-download run completed interpolation, Themis and stabilization
support weights in the independent stage. Twelve bounded synthetic output cases
passed: automatic-crop / full-frame stabilization, interpolation, 2× slow motion,
deblur, HDR, combined enhancement/filter/HDR, standalone Nyx, Nyx plus Proteus,
silent HEVC, Precise 2.6 plus interpolation at 512→1024, and a 720×1280 full-filter
portrait chain. The portrait result is 24 frames at 48 fps, HEVC 10-bit with
BT.2020/PQ tags. Source AAC preservation, silent output and intermediate cleanup
were checked separately. Evidence is local and ignored under
`tests/output/topaz-video-completion/native-acceptance.json`.

Boundaries remain explicit: this is not long-video/visual-quality acceptance or
full parity with every Topaz format/model. Precise's native 256px synthetic input
hit a dimension broadcast error, while its previously validated 512px input
passed the new combined plan; the runtime reports that native size incompatibility
without publishing a result or silently resizing the input. An initial portrait
fixture accidentally retained square display aspect via non-square pixels;
its dimension mismatch was rejected. The corrected square-pixel portrait fixture
passed. Mini and separate Precise 2.5 remain unavailable for their existing reasons.

## Previous Mini research

This directory is **not** `backend/topaz/` (Topaz Gigapixel) or the Windows H3
runtime. `provision.py` prepares and verifies an
explicitly selected local `Contents` stage; `mini_runtime.py` runs the staged
FFmpeg/CoreML Mini filter. Neither module starts the Topaz Video GUI, selects a
stage by default, or downloads models.

## Boundary and assets

The stage contains the bundled `MacOS/ffmpeg` and the complete `Frameworks/`
directory with its relative dylib symlinks, plus exactly these Mini model assets
from `Resources/models/`:

- `slm-1.json` and its seven declared child manifests: `slmes-1`, `slmem-1`,
  `slmus-1`, `slmum-1`, `slmds-1`, `slmdm-1`, `slmdl-1` (`.json` each).
- Generic FFmpeg/TVAI metadata `tvai.tz` (the Mini filter may consult it).
- `slme-v1-1fr-fp16-720x1280-mlp.tz3`,
  `slmu-v1-16fr-fp16-90x160-mlp.tz3`, and
  `slmd-v1-16fr-fp16-30x40-mlp.tz3`.
- An empty writable `coreMLCache/` directory. If the source installation has
  cache directories matching the three weight stems, those directories are
  copied as an **optional warm-start**. A fresh installation with no compiled
  Mini cache is still stage-ready; CoreML may build it during the first run.

No account directory, license file, unrelated model, or original-App symlink is
imported. The source and stage must be disjoint. The existing stage is never
overwritten. A sibling temporary directory is built first, then atomically
renamed. `mini-stage-manifest.json` records SHA-256 and size for the immutable
FFmpeg, Frameworks, model JSON, weights, and `tvai.tz` files and records their
internal symlinks. `coreMLCache/` is deliberately excluded from this immutable
inventory: normal cache creation, refresh, or deletion does not invalidate the
stage. Existing schema 1 stages remain readable: verification compares only
their immutable-file entries and ignores legacy cache fingerprints. An idle
stage can be explicitly migrated to schema 2 with
`python3 -m backend.topaz_video.provision refresh-manifest --stage <Contents>`;
this rewrites only the manifest, only after immutable fingerprints pass. Do not
run that migration while a Mini inference task is active. Verification still
rejects symlinks escaping the stage **anywhere**,
including inside the cache. This is a local integrity check, not a claim about
licensing, model authenticity, or inference support.

## Explicit local use

```bash
python3 -m backend.topaz_video.provision prepare \
  --source '/Applications/Topaz Video.app/Contents' \
  --stage 'tests/output/topaz-video-mini-20260925/stage/Contents'

python3 -m backend.topaz_video.provision inspect \
  --stage 'tests/output/topaz-video-mini-20260925/stage/Contents'

PYTHONPATH="$PWD" python3 tests/local/topaz_video_mini_local.py \
  --stage 'tests/output/topaz-video-mini-20260925/stage/Contents' \
  --source '/absolute/path/to/source.mp4' \
  --output 'tests/output/topaz-video-mini-20260925/result.mp4' \
  --start 6 --duration 0.5 --frames 15 \
  --width 2160 --height 3840 --instances 0 --timeout 480
```

Both commands report JSON and return nonzero when the stage is unavailable.
Callers use `require_stage(explicit_path)` before launching an independent
runtime; there is no automatic fallback to `/Applications` or model download.
`mini_runtime.py` is the standalone inference entrypoint: construct a
`MiniRequest`, then call `run_mini(explicit_stage, request, log_path=...)`. Its
`on_progress` callback and `cancel_event` can be adapted to the canvas task
contract after a real export succeeds. It uses the staged FFmpeg `tvai_up`
filter rather than the GUI or Gigapixel worker. The runtime atomically
publishes a validated MP4 without overwriting a concurrent result (the output
filesystem must support hard links, e.g. APFS) and excludes source audio; an
outer media service must remux audio if desired. Validation uses the project's
shared `ffprobe` from `PATH` rather than copying a second probe binary. Keep
the stage under an
ignored path such as
`components/topaz-video/mini/Contents` or `tests/output/`; it is not committed.
Runtime logs and rendered media also stay under ignored paths.

Current local validation is **not** a production success: on macOS 27.0 / M2
Max, a 15-frame face clip at 2160×3840 and a reduced 720×1280 export both
failed to produce a first frame. A 32-frame 720×1280 export still had no first
frame after a 600-second no-sandbox, stage-working-directory run; process
sampling remained in CoreML/MPSGraph graph optimization. The original app's
Mini **preview** also logged a Metal error, but its *full export* route has not
been observed. The installed Neuroserver does not recognize `slm-1` as a
dispatchable model, so it is not an established fallback for this machine.
`inspect` returning `ready: true` verifies staged assets, **not** inference
compatibility. Portable command, cancellation, timeout, result-validation,
and staging tests pass, but canvas registration must wait for a real Mini
export and quality/speed acceptance. The exact local probes are recorded under
`tests/output/topaz-video-mini-20260925/REPORT.md`.

Synthetic verification on macOS (the tests skip on Windows/Linux):

```bash
PYTHONPATH="$PWD" python3 -m unittest tests.test_topaz_video_provision tests.test_topaz_video_mini_runtime
```
