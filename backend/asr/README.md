# ASR (speech recognition for automatic subtitles)

Qwen3-ASR 1.7B with Qwen3-ForcedAligner 0.6B, in its own Python 3.12 venv under
`components/asr/`. The HTTP process never imports torch: each recognition is one subprocess that
loads the models, transcribes once and exits, so its memory (about 2.3 GB) goes back to the system
as soon as it ends. Today the only caller is video_edit's automatic subtitles
(`video_edit/transcribe.py`); this domain knows nothing about videos or cues.

| File | Owns |
|---|---|
| `contracts.py` | Limits shared with the worker: engine name, 180 s per run (the aligner's one-pass limit), `max_new_tokens(seconds)` (music can make the model repeat a filler until the cap), the whole-run timeout, `is_filler` (Qwen answers music with 「啊。」/"Oh."; treated as no speech), the OpenCC script configs (`original` / `traditional` → `s2tw` / `simplified` → `t2s`, Chinese and Cantonese only). No I/O. |
| `environment.py` | Explicit, user-triggered preparation and status. `prepare` builds `venv/` with uv from `requirements.lock` (`--require-hashes --no-deps`), downloads the files pinned in `assets.lock.json` into `assets/{asr,aligner}/` (ModelScope direct first, Hugging Face through the proxy second; size + sha256 checked before a file is kept; partial downloads resume) and writes `installed.json` last. `status` reports readiness and reasons without paths. |
| `worker.py` | Runs inside the venv: loads both models (MPS bf16, CPU fp32 fallback), transcribes with timestamps, attaches the punctuation after each aligned unit, applies the OpenCC script (length-preserving, so slices still line up), writes `result.json` atomically. Progress as `ASR_EVENT {json}` lines. |
| `runtime.py` | `Runtime.transcribe(wav, seconds, script, cancelled, progress)`: takes the shared `components/.local-inference.lock` lease (passed to the child with `pass_fds`), asks resident local models to unload (`before_load`), starts the worker in a new session, kills its process group on cancel or timeout, keeps `runtime/last-run.log` (4 MB cap). The child exits by itself when the server dies (`parent_watch`). |
| `service.py` | `AsrService`: cached status (30 s, refreshed when the prepare operation changes), `prepare()` via `local_image.preparation.Preparation` (`runtime/prepare.log`), the `transcribe` port (refused while preparing). |

HTTP: `routes/asr_routes.py` — `GET /api/asr/status`, `POST /api/asr/prepare` (202). Recognition
has no route of its own; `POST /api/video_edit/transcribe` calls the port with a WAV the server
rendered itself.

## Installed layout (`components/asr/`, git-ignored)

```
venv/                 Python 3.12, 51 hash-pinned packages (~1 GB)
assets/asr/           Qwen3-ASR-1.7B        (~4.7 GB)
assets/aligner/       Qwen3-ForcedAligner-0.6B (~1.8 GB)
installed.json        receipt: python, prepared_at, versions (written last)
runtime/              prepare.log, last-run.log
```

`qwen-asr` pins `transformers==4.57.6` and pulls in gradio/flask for its demo, which is why it is
installed with `--no-deps` and the lock lists every runtime import (torch, transformers,
accelerate, librosa, soundfile, nagisa, numpy, opencc). Regenerate the lock with
`uv pip compile --python-version 3.12 --python-platform aarch64-apple-darwin --generate-hashes`
and `MACOSX_DEPLOYMENT_TARGET=14.0` (torch has no wheels for the default macOS target).

## Costs and limits

- About 10 s of fixed model loading per run, then roughly 1.5× real time for recognition plus
  alignment on Apple Silicon (a 10 s clip took 15.8 s end to end).
- 180 s of audio per run; compose output is capped at the same length.
- Accuracy: punctuation is produced; homophones and proper nouns still need the user's review,
  which is why results are always editable draft cues.

Tests: `tests/test_asr.py` (contracts, fake prepare with ModelScope→HF fallback, status, a fake
worker for result/cancel/timeout/lease release, routes).
