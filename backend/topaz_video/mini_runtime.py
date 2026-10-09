"""Standalone, local Starlight Mini FFmpeg/CoreML task runner.

This module deliberately has no dependency on the Topaz Video GUI or on the
Gigapixel image runtime in ``backend.topaz``. A provisioned ``Contents`` tree
is supplied explicitly by the caller; model downloads are disabled.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .provision import require_stage


class MiniRuntimeError(RuntimeError):
    """The local Mini task could not produce a validated video."""


class MiniTaskCancelled(MiniRuntimeError):
    """The caller cancelled the running task."""


class MiniTaskTimeout(MiniRuntimeError):
    """The running task exceeded its deadline."""


@dataclass(frozen=True)
class MiniRequest:
    source_path: Path
    output_path: Path
    output_width: int
    output_height: int
    start_seconds: float = 0.0
    duration_seconds: float | None = None
    frame_limit: int | None = None
    device: str = "0"
    instances: int = 1
    max_memory_fraction: float = 1.0

    def validate(self) -> None:
        if self.output_width <= 0 or self.output_height <= 0:
            raise ValueError("Output dimensions must be positive")
        if self.start_seconds < 0:
            raise ValueError("start_seconds must not be negative")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.frame_limit is not None and self.frame_limit <= 0:
            raise ValueError("frame_limit must be positive")
        if not 0 <= self.instances <= 3:
            raise ValueError("instances must be between 0 and 3")
        if not 0.1 <= self.max_memory_fraction <= 1.0:
            raise ValueError("max_memory_fraction must be between 0.1 and 1.0")
        if not self.device or any(char in self.device for char in ":,; "):
            raise ValueError("Invalid device selector")


@dataclass(frozen=True)
class MiniResult:
    output_path: Path
    log_path: Path
    elapsed_seconds: float
    frames: int
    width: int
    height: int
    frame_rate: str


def build_command(ffmpeg_path: Path, request: MiniRequest, output_path: Path) -> list[str]:
    """Build the offline Mini command without executing it.

    ``-an`` is intentional: this runner measures/produces the enhanced video
    stream. Audio remuxing belongs to the media/asset boundary, not the model.
    """
    request.validate()
    model_filter = (
        "tvai_up=model=slm-1:scale=0"
        f":w={request.output_width}:h={request.output_height}"
        f":device={request.device}:vram={request.max_memory_fraction:g}"
        f":instances={request.instances}:download=0"
    )
    command = [str(ffmpeg_path), "-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1"]
    if request.duration_seconds is not None:
        command.extend(["-t", f"{request.duration_seconds:.9g}"])
    if request.start_seconds:
        command.extend(["-ss", f"{request.start_seconds:.9g}"])
    command.extend(["-i", str(request.source_path)])
    if request.frame_limit is not None:
        command.extend(["-frames:v", str(request.frame_limit)])
    command.extend(
        [
            "-sws_flags", "spline+accurate_rnd+full_chroma_int",
            "-filter_complex", model_filter,
            "-c:v", "h264_videotoolbox",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-allow_sw", "1",
            "-g", "30",
            "-b:v", "0",
            "-q:v", "82",
            "-movflags", "frag_keyframe+empty_moov+delay_moov+use_metadata_tags+write_colr",
            "-an", str(output_path),
        ]
    )
    return command


def _probe_video(path: Path, *, ffprobe_path: str = "ffprobe") -> tuple[int, int, int, str]:
    command = [
        ffprobe_path, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode:
        raise MiniRuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    try:
        stream = json.loads(result.stdout)["streams"][0]
        return (
            int(stream["nb_read_frames"]),
            int(stream["width"]),
            int(stream["height"]),
            str(stream["r_frame_rate"]),
        )
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise MiniRuntimeError(f"Missing video stream in {path}") from exc


def _terminate_process_group(process: subprocess.Popen[str]) -> bool:
    """Bounded shutdown; False means the OS has not reaped the child yet."""
    if process.poll() is not None:
        return True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        # The leader may exit between poll() and killpg(), releasing its group.
        # Fall back to signalling the direct child if it is still live.
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=8)
        return True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=8)
            return True
        except subprocess.TimeoutExpired:
            return False


def run_mini(
    stage: Path | str,
    request: MiniRequest,
    *,
    log_path: Path | str,
    timeout_seconds: float = 2700,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[dict[str, str]], None] | None = None,
    sandbox_profile: Path | str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> MiniResult:
    """Run one offline Mini task and atomically publish a validated MP4.

    The task has explicit cancellation, timeout, a durable log, and one output
    owner. The caller can adapt ``on_progress`` to the canvas task contract.
    """
    contents = Path(require_stage(stage)).resolve()
    request.validate()
    source = Path(request.source_path).expanduser().resolve(strict=True)
    output = Path(request.output_path).expanduser().resolve(strict=False)
    log = Path(log_path).expanduser().resolve(strict=False)
    if not source.is_file():
        raise MiniRuntimeError(f"Source video is not a file: {source}")
    if output.exists():
        raise MiniRuntimeError(f"Refusing to replace existing output: {output}")
    if output.is_relative_to(contents) or log.is_relative_to(contents):
        raise MiniRuntimeError("Mini outputs and logs must be outside the verified runtime stage")
    if log == source or log == output or (log.exists() and log.samefile(source)):
        raise MiniRuntimeError("Mini log path conflicts with the source or output")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.{uuid.uuid4().hex}.partial{output.suffix}")
    ffmpeg = contents / "MacOS" / "ffmpeg"
    model_dir = contents / "Resources" / "models"
    command = build_command(ffmpeg, request, temporary)
    if sandbox_profile is not None:
        command = ["sandbox-exec", "-f", str(Path(sandbox_profile).expanduser().resolve(strict=True)), *command]
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    # The selected stage owns model lookup even when callers supply other
    # process settings such as an isolated HOME or GPU diagnostics.
    environment.update({"TVAI_MODEL_DIR": str(model_dir), "TVAI_MODEL_DATA_DIR": str(model_dir)})

    started = time.monotonic()
    lines: queue.Queue[str | None] = queue.Queue()
    progress: dict[str, str] = {}
    tail: list[str] = []
    reader_errors: list[Exception] = []
    stopped_by: str | None = None
    termination_stuck = False
    with log.open("w", encoding="utf-8", buffering=1) as log_file:
        log_file.write(f"MINI_RUNTIME_CMD={json.dumps(command, ensure_ascii=False)}\n")
        log_file.write(f"MINI_RUNTIME_STAGE={contents}\n")
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )

        def read_output() -> None:
            assert process.stdout is not None
            try:
                with process.stdout:
                    for line in process.stdout:
                        lines.put(line)
            except Exception as exc:
                reader_errors.append(exc)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        read_failed = True
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set() and stopped_by is None:
                    stopped_by = "cancelled"
                    if not _terminate_process_group(process):
                        termination_stuck = True
                        break
                if time.monotonic() - started > timeout_seconds and stopped_by is None:
                    stopped_by = "timed out"
                    if not _terminate_process_group(process):
                        termination_stuck = True
                        break
                try:
                    line = lines.get(timeout=0.5)
                except queue.Empty:
                    if process.poll() is not None and not reader.is_alive():
                        break
                    continue
                if line is None:
                    break
                log_file.write(line)
                tail.append(line.rstrip())
                if len(tail) > 40:
                    tail.pop(0)
                if "=" in line:
                    key, value = line.rstrip().split("=", 1)
                    if key in {"frame", "fps", "out_time", "out_time_ms", "progress"}:
                        progress[key] = value
                        if key == "progress" and on_progress is not None:
                            try:
                                on_progress(dict(progress))
                            except Exception as exc:
                                log_file.write(f"MINI_RUNTIME_PROGRESS_CALLBACK_ERROR={type(exc).__name__}: {exc}\n")
            read_failed = False
        finally:
            if process.poll() is None and not termination_stuck:
                termination_stuck = not _terminate_process_group(process)
            reader.join(timeout=2)
            if read_failed or stopped_by is not None or process.poll() != 0:
                temporary.unlink(missing_ok=True)
        return_code = process.poll()
        elapsed = time.monotonic() - started
        log_file.write(f"MINI_RUNTIME_EXIT={return_code} ELAPSED_SECONDS={elapsed:.3f}\n")
        if termination_stuck:
            log_file.write(f"MINI_RUNTIME_UNREAPED_PID={process.pid}\n")
        if reader_errors:
            log_file.write(f"MINI_RUNTIME_READER_ERROR={reader_errors[0]!r}\n")

    if reader_errors:
        temporary.unlink(missing_ok=True)
        raise MiniRuntimeError(f"Mini output reader failed; log: {log}")
    if stopped_by is not None:
        stuck_note = f"; process {process.pid} not reaped" if termination_stuck else ""
        if stopped_by == "cancelled":
            raise MiniTaskCancelled(f"Mini task cancelled after {elapsed:.1f}s{stuck_note}; log: {log}")
        raise MiniTaskTimeout(f"Mini task timed out after {elapsed:.1f}s{stuck_note}; log: {log}")
    if return_code is None:
        raise MiniRuntimeError(f"Mini process {process.pid} could not be reaped; log: {log}")
    if return_code != 0:
        raise MiniRuntimeError(
            f"Mini FFmpeg exited {return_code} after {elapsed:.1f}s; log: {log}; tail: {' | '.join(tail[-5:])}"
        )
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise MiniRuntimeError(f"Mini did not produce a nonempty MP4; log: {log}")
    try:
        frames, width, height, frame_rate = _probe_video(temporary)
        if frames <= 0:
            raise MiniRuntimeError(f"Mini produced no video frames; log: {log}")
        if (width, height) != (request.output_width, request.output_height):
            raise MiniRuntimeError(f"Unexpected Mini dimensions {width}x{height}; log: {log}")
        if request.frame_limit is not None and frames != request.frame_limit:
            raise MiniRuntimeError(f"Unexpected Mini frame count {frames}, expected {request.frame_limit}; log: {log}")
        try:
            os.link(temporary, output)
        except FileExistsError as exc:
            raise MiniRuntimeError(f"Refusing to replace existing output: {output}") from exc
        except OSError as exc:
            raise MiniRuntimeError(
                f"Cannot atomically publish Mini output on this filesystem: {output}: {exc}"
            ) from exc
        temporary.unlink()
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return MiniResult(output, log, elapsed, frames, width, height, frame_rate)
