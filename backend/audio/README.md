# Audio / mlx-Yue boundary

Status: optional local inference, **never installed or downloaded by server startup**.
The Python 3.14 profile has passed real generation, transcription, ABC-reference generation
and process cancellation on Apple Silicon. It does not require an external audio Provider.

## Ownership and dependency direction

- `contracts.py`: bounded snake_case requests and upstream-compatible defaults.
- `storage.py`: independent SQLite task receipts and immutable per-task artifact directories.
- `service.py`: serial audio queue, uploaded audio assets, cancellation, recovery and artifact manifests.
- `environment.py` / `requirements-py314.txt`: the shared interpreter contract and pinned optional
  audio dependency profile. `install.py` owns explicit installation and its receipt.
- `runtime.py` → `worker.py`: offline CLI execution in a separate **process**, sharing the
  main Python 3.14 virtual environment, not creating another audio virtual environment.
  Parent death stops the inference process group. Cancellation uses TERM, then KILL;
  runtime deadline is two hours. The server never imports MLX/NumPy/PyTorch.
  Its child environment sets `AGX_RELAX_CDM_CTXSTORE_TIMEOUT=1` before Metal
  initialization, following the maintainer workaround in
  [MLX #3267](https://github.com/ml-explore/mlx/issues/3267#issuecomment-4072457752).
  This mitigates `Impacting Interactivity` aborts; it is not an OOM fix or a
  guarantee for all GPU workloads. It does not change the parent/global/image
  environment, model parameters, memory guard, cancellation or output formats.
- `progress.py`: bounded parser for the pinned CLI's non-TTY `[YuE2]` stage lines
  and transcription JSON. Runtime passes observations to the service, which stores
  only approved fields (`stage`, counts, unit and phase status). A completed phase
  never marks the job complete; output verification still belongs to runtime.
  Known synthesis/decode totals describe that phase only. AR token counts have no
  known total, and neither token limits nor elapsed time become fake percentages.
- `vendor/yue_abc.py`: pinned standard-library native-dialect parser/inspector/strip/compare,
  usable without model weights. Source and license: `vendor/NOTICE.md`.
- `../routes/audio_routes.py`: exact authenticated endpoints, bounded bodies and streamed
  HTTP Range support. `server.py` only constructs the runtime/service and dispatches routes.

No imports of image providers, image job database, GPT/Google account pools, Telegram
senders or image archives. Audio does not automatically send to Telegram. Deleting a canvas
node does not cancel its independent job; use Stop first. Receipts/artifacts remain persistent;
history will be managed by the asset library later, not by controls on each inference node.
Concurrent service instances cannot take over the same audio task database. In-flight/queued
jobs become `interrupted` on service recovery; no automatic duplicate generation.

## Persistent layout

Relative to **APP_DATA_DIR**, not the disposable packaged application directory:

```
components/audio-yue/source/       pinned upstream checkout + audited metadata adaptation
components/audio-yue/install-records/ dependency baselines, constraints and doctor reports
components/audio-yue/models/       generator, VAE, SheetSage2, MERT checkpoints
components/audio-yue/cache/        audio-only Hugging Face cache
components/audio-yue/installed.json
data/audio/jobs.sqlite3
data/audio/assets/<sha256>.<ext>    local reference audio (maximum 100 MB)
data/audio/jobs/<job_id>/           submission, runtime log, resource logs, result/*
```

These runtime paths are ignored by Git. Job results keep all upstream artifacts, including
request/config/result/plan JSON, score, semantic/latent/noise arrays when emitted. There is no
automatic artifact or source-audio deletion. `/api/audio/artifact` only serves manifest-listed
files in a validated job directory; paths from a caller are never passed to the CLI.
Uploads require supported audio-container signatures, not playlists. Authentication remains
the existing server session/header gate. Browser requests never forward credentials to
arbitrary remote audio URLs: import those as local audio-node files first.

## Install explicitly (source checkout)

From the project root, with native Apple Silicon macOS, main Python **3.14**, and `uv`:

```sh
# Install into the existing main .venv. Models already placed locally are preserved.
.venv/bin/python -m backend.audio.install
# Optional explicit downloads, only for missing model directories:
.venv/bin/python -m backend.audio.install --models generation
.venv/bin/python -m backend.audio.install --models all
```

The installer checks out `vanch007/mlx-Yue` at
`9253ed133343406947bde7b67d43c7a63fb39d99`. The only source adaptation is two dependency
metadata lines: Python `<3.13` → `<3.15`, NumPy `2.2.6` → `2.3.3`. This is our tested
**3.14 compatibility profile**, not an upstream 3.14 support claim or a new upstream lock.
Algorithm code and all other direct upstream runtime pins are unchanged. Do not run the
upstream `uv sync` (its lock remains Python 3.12); use this installer and the separate pinned
`requirements-py314.txt` dependency closure instead. Generic root requirements remain portable.

Installation builds a non-editable wheel, constrains existing packages to their installed
versions, resolves before installing, runs package checks and upstream doctor, then atomically
writes `installed.json`. A dependency conflict stops installation rather than downgrading the
app. Re-running accepts only the two exact metadata edits; extra source changes are preserved
and rejected. Baselines and doctor reports remain in `install-records/`. Temporary build
isolation is removed automatically; no persistent audio `.venv`, Torch, or FFmpeg wheel is added.
Install during an idle maintenance window and restart the main service after changes.

Source-mode workers use the server's `sys.executable`, preserving its venv symlink. An explicit
`--python /absolute/shared/.venv/bin/python` installer option supports a differently located
shared runtime. For a frozen desktop backend, `sys.executable` is an app binary, so only the
external interpreter recorded by the installer is used; no attempt is made to execute the
frozen binary as Python. `CANVASHUB_DATA_DIR` must match that app's persistent data directory.
Packaging includes worker source and the profile, not MLX/model weights or a new environment.

FFmpeg is shared with the system. The worker also searches `/opt/homebrew/bin` and
`/usr/local/bin`, because launchd/Finder do not read shell profiles; the parent process PATH is
not modified. Checkpoint downloads are opt-in, pinned, do not overwrite existing directories,
and keep HF cache metadata outside the strictly validated generator directory. All generator
weights, including `ar-bf16.safetensors`, must remain present even when selecting 8bit.
The converted generator also performs a strict relative-file manifest check. Before an
install doctor run and before each worker launch, CanvasHub removes only `.DS_Store` files
inside the four known audio model directories; Finder can recreate these harmless metadata
files and upstream otherwise rejects them as unexpected model artifacts. Other unexpected
files are preserved so integrity errors remain visible.

`status` checks receipt/profile, interpreter identity and installed package versions (cached
for 30 seconds), then required model files and FFmpeg. It is **not an inference
benchmark or an audio quality verdict**. Real generation and transcription must be smoke-tested
after installation. The upstream and downloaded model license/notice files are retained;
code licensing does not replace the separate checkpoint licenses.

## APIs

All endpoints require existing auth; no unauthenticated music port or daemon is added.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/audio/status` | Independent runtime / model readiness |
| POST | `/api/audio/upload?name=clip.wav` | Raw binary → `asset_id` |
| POST | `/api/audio/submit` | Validated job → durable receipt |
| GET | `/api/audio/job?id=...` | Status, original spec, progress observations, artifacts |
| GET | `/api/audio/jobs` | Latest 50 audio jobs, recovery |
| POST | `/api/audio/cancel` | `{ "id": "..." }` |
| GET | `/api/audio/artifact?id=...&name=...` | Protected streaming / Range / download |
| POST | `/api/audio/score` | Native ABC `inspect`, `strip-chords`, `compare` |

Generation example:

```json
{"operation":"generate","precision":"8bit","audio_format":"flac","request":{"style":"Mandarin pop, piano","lyrics":"[Verse]\nA short song","cot":"full","seed":831001,"generation_config":{"ode_steps":32}}}
```

`audio_format` is an app export setting (`flac` default / `wav`), not a `SongRequest`
field. The worker retains the unmodified upstream FLAC bundle and its replay checksums;
when WAV is selected it additionally exports `result/audio.wav` as lossless PCM-24 in
bounded chunks using the already-installed soundfile dependency. No resampling, model
rerun, additional service or environment. WAV export remains inside the cancellable worker
process; an atomic rename publishes only a completed export. Runtime completion requires
the selected file, and the canvas publishes that format rather than the archive FLAC.
Old submissions without this field keep FLAC. Plan/transcription do not create WAV exports.

`operation=plan` creates score artifacts only. `cot=off` rejects supplied ABC and plan-only
requests. Seed `-1` is an app convenience expanded to a real seed before saving/submitting.
The API uses JavaScript-safe integer seeds (upstream accepts a larger 63-bit range).
CFG is omitted by default: upstream uses 1.0 in full/melody, 1.01 in off. Screenshot CFG 2.5,
Top P .9 and Temperature .8 are not silently treated as upstream defaults. ABC sampling
and semantic sampling are distinct JSON groups; `generation_config` supports ODE and the
upstream `abc`/`semantic` sampling aliases. The fixed upstream context/midpoint/version
are not user-overridable. App ODE limit is 128, transcription cap 1–1800 seconds.

Transcription takes `operation=transcribe`, `asset_id`, `task` (full/melody-full/melody-vocal),
`preset` (default/paper), `max_seconds`. Vocal melody is a transcription target, not audio
stem separation. `max_seconds` deliberately limits the input; it is not a guaranteed song
generation length. A truncated model result is `partial`, never silently shown as complete.

## Verification and remaining scope

Local tests live under ignored `tests/*_local.*`. Browser fixtures mirror the running
`/desktop.html` and actual assets but use isolated synthetic jobs and an independent origin.
No production workflow, account or image generation request is touched.

Supported UI: five music nodes, typed links, real ABC rendering, SVG/PNG/MIDI export,
print-to-PDF, native-dialect checks, audio/score/parameter side-by-side comparison, cancellation,
and generated audio in the original shared audio node. Style/lyrics must come from connected
text nodes. Inference nodes have no inline creative-text fields, connection diagnostics, or
history/restore panel. Local HTTP routes are the app-to-worker boundary, not an external
audio API dependency. Automatic current-job polling on reload is retained; asset-library
history integration is not implemented yet.

Not claimed: generic MIDI-to-ABC import, audio stem separation, voice cloning, automatic
transcription of lyrics, sample-accurate multi-player synchronization, or a guarantee of subjective music quality.
The preview key/meter/tempo come from ABC; edit source ABC to change them. Music replay/render-plan
and batch CLI modes are not exposed in this first UI. Complete artifacts remain available for
future adapters. PDF uses the browser's print dialog, not a silent PDF file writer.
