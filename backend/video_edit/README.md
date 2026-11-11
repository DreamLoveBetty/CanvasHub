# Video edit (phase 1: exact frames, scene candidates, audio separation; phase 2: compose; phase 3a: speed, transitions; phase 3b: burned-in subtitles; automatic subtitles)

Design: `docs/VIDEO_EDITING_DESIGN.md`. This domain only runs the system FFmpeg/ffprobe as
subprocesses; it imports no media library, model or other video domain.

| File | Owns |
|---|---|
| `contracts.py` | Limits and request validation. Requests carry a served media URL, never a path. |
| `sources.py` | Maps `/video/…`, `/api/topaz_video/{source,artifact}` and `/api/video_control/{source,artifact}` to files through resolvers injected by `server.py` (the same ones that serve those URLs). |
| `media.py` | `Tools` (FFmpeg lookup), `Runner` (timeouts, cancel), probe with every frame's presentation time, exact frame extraction, `scdet` scene scoring, audio copy/re-encode plan. |
| `service.py` | Serial in-memory job queue (`frames`, `scenes`, `extract_audio`), probe/digest caches, preview frames and timeline filmstrips (LRU-cached), archive writes. |
| `plan.py` | Pure compose planning: output size, frame-exact clip windows, the FFmpeg filter graph (fit, fps, speed, clip audio or silence, transitions, music with fades), output and total seconds after speed and transitions, encoder arguments and progress parsing. No files or subprocesses. |
| `subtitles.py` | Burned-in subtitles with Pillow: the font catalog of `PROJECT_ROOT/font` (ttf/otf/ttc, browser preview URL), layout metrics, wrapping (CJK anywhere, Latin by word, no leading punctuation), one transparent PNG per cue with its overlay position and time, `.srt` text. |
| `compose.py` | `ComposeService`: validates a recipe against each source's probe, renders one job at a time on its own worker (`nice`), writes the MP4 and its `.json` recipe / `.txt` / `.md` sidecars, reads a recipe back for reopening. |
| `transcribe.py` | `TranscribeService`: automatic subtitles. Resolves the recipe like a render, renders only the clips' own sound (`plan.voice_command`: no music, muted clips silent, same speed and transitions, 16 kHz mono WAV in a temp folder) so timestamps are already output seconds, calls the injected ASR port (`backend/asr`), and cuts the aligned tokens into draft cues (`cues_from_tokens`: sentence punctuation, a comma once a cue is 10 wide, a 0.6 s pause, at most 24 wide / 6 s; trailing commas and full stops dropped; ≥ 0.3 s, no overlaps, +0.2 s hold). In-memory jobs (`transcribe_…` ids, one worker, at most 2 active); nothing is archived and nothing is burned in. |
| `beats.py` | Music beats for compose snapping, no numpy: FFmpeg `astats` RMS of four bands per 512 samples at 22.05 kHz (first 190 s only), onset envelope from the summed level rises, tempo from windowed autocorrelation with log compression and a 120 BPM log-normal prior (refined over four beats), beats by Ellis dynamic programming. `BeatAnalyzer` runs the four bands in parallel and caches 32 results by content digest. About 0.5 s a song; fast songs can come out at half tempo (every beat still lands on a beat). |
| `storage.py` | `ComposeStore`: durable compose receipts in `data/video-edit/jobs.sqlite3`; queued/running jobs become `interrupted` on start and keep their recipe. |

HTTP adapter: `routes/video_edit_routes.py` (`/api/video_edit/{status,probe,preview_frame,filmstrip,submit,job,cancel}`,
plus `compose`, `compose_check`, `compose_recipe` and `subtitle_fonts` for the compose service, `music_beats` (GET, `source_url` or `asset_id` of the compose music) and `transcribe` for automatic subtitles; `job`/`cancel` route an id to the service
that owns it).

## Frame accuracy

`probe` lists video packet `pts_time` values from ffprobe, drops discarded packets and anything
before the container start, and sorts them: index N is the Nth displayed frame, VFR included.
Frame N is decoded with `-seek_timestamp 1 -ss <midpoint of frames N-1 and N>`, so the decoder
drops N-1 and outputs N. The canvas picker seeks the player to the same midpoints. Regression
tests compare against `select=eq(n,N)` on B-frame, offset-start and VFR clips.

## Outputs

* Frames: full-resolution PNG in today's archive folder,
  `video_frame_<HHMMSS>_<sha12>_f<NNNNNN>.png` with `.txt` and Obsidian `.md` sidecars. The asset
  index files them under provider `video_frame` (“视频抽帧”). The same source frame is reused.
* Audio: the first audio stream, copied bit-exact when a common container holds it
  (AAC/ALAC → `.m4a`, MP3, FLAC, Opus/Vorbis → `.ogg`, PCM LE → `.wav`), otherwise FLAC. Published
  with `AudioArchive.publish_file` into `<archive>/audio/YYYY-MM-DD/video_audio_<HHMMSS>_<sha12>.<ext>`
  (`engine: video_edit`, `title`, source codec, `copied`). One file per source content.

`sha12` is the source file's SHA-256 prefix, so outputs are idempotent per content.

## Jobs

Jobs are short and kept in memory (a deliberate simplification of the design's durable queue):
a restart forgets receipts, never outputs, because every output is already in the archive. Limits:
sources up to 600 s, 20 frames per job, 8 active jobs, finished receipts kept 1 h (at most 64).
Scene candidates use `scdet` on a 270p copy (score ≥ 6, at least 0.5 s apart, at most 40); the
user confirms them in the picker.

## Compose (phase 2)

A recipe is the ordered clips (served URL + frame range `start_frame`..`end_frame`, `-1` = last
frame, per-clip audio on/off), clip volume, optional music (archive URL, audio job artifact or an
uploaded `asset_id`, with volume and fades) and output settings (aspect, 720/1080, 24/30 fps,
crop/pad/blur fit, `libx264` quality or VideoToolbox fast). `clip_window` uses the same frame
times as the picker, so a trim is exact to the frame; clips without audio get silence. The total
is limited to 180 s and 20 clips.

* Phase 3a: each clip has `speed` (0.5/0.75/1/1.25/1.5/2: `setpts=(PTS-STARTPTS)/speed` +
  `atempo`) and `transition` to the next clip (`none`/`fade`/`fadeblack`/`wipeleft`, 0.5 or 1 s;
  the last clip's is forced to none). A transition is capped at half of either neighbour; video
  joins pairwise with `xfade`, audio with `acrossfade`, `none` seams with `concat=n=2`; with no
  transitions the phase-2 single `concat=n=N` graph is kept. Total = Σ(window ÷ speed) − Σ cuts;
  a clip shorter than 0.5 s after speed is rejected. Speed/transition enter the recipe key only
  when non-default, so phase-2 recipes keep their file names.
* Phase 3b: optional `subtitles` = `{cues: [{start, end, text}], style: {size, position, look, font}}`
  on the output timeline (seconds; at most 100 cues of 80 characters, each at least 0.3 s, sorted,
  no overlaps; a cue starting within 0.3 s of the end is rejected, an end past it is clipped; at
  most 3 lines after wrapping). Each cue is drawn to a PNG in a scratch folder that is removed after
  the render, and overlaid with `enable='gte(t,a)*lt(t,b)'` after the joined video. Subtitles enter
  the recipe key (cues, style, font file digest) only when there are cues.
* Output: `<today>/video_compose_<HHMMSS>_<recipe sha12>.mp4`. The name hashes the source contents
  and every setting, so an identical recipe reuses the file instead of rendering again.
  Rendering writes `.<name>.writing.mp4` and renames it; a cancel or failure removes it.
* Sidecars: `.json` (the recipe and a summary), `.txt` and the Obsidian `.md` note, plus a same-name
  `.srt` when the render has subtitles.
  `compose_recipe?source_url=/video/video_compose_….mp4` reads the `.json` back (only for files
  with that name, at most 256 KB, re-validated by `contracts.compose_request`) so the canvas can
  rebuild the node.
* Renders run on a worker of their own, so a long render never blocks frames or scene jobs.
* Compose outputs are never sent to Telegram, whatever their size (maintainer decision,
  2026-11-10); they stay in the archive and the asset library. A regression test guards this.
* `filmstrip?source_url=&tiles=` returns one JPEG row of 8/16/24/40 tiles, 96 px tall, frame
  `int((i + 0.5) * count / tiles)` per tile; the compose timeline draws clip thumbnails from it.
