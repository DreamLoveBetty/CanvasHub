"""Offline Mac video enhancement worker for staged Topaz Video resources.

No GUI process, account directory, network/model download, or image Topaz
runtime is consulted here. The service owns queue/storage; this module owns
model subprocesses, progress, cancellation, and validated video publication.
"""
from __future__ import annotations

from fractions import Fraction
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Callable
import uuid

from .catalog import BY_ID, MODELS, public_model
from .license import resolve_license_dir
from .provision_local import inspect_conventional, inspect_precise, local_validation
from .features import DEFAULT_ENCODING, encoding_args, inspect_features, validate_capabilities
from .pipeline import Pass, audio_filter, build_plan, enhancement_filter, output_timing


class VideoRuntimeError(RuntimeError):
    pass


# The detached Topaz FFmpeg filter can return no frames when an exact input
# seek lands very close to EOF.  A bounded pre-roll keeps model state warm and
# still avoids enhancing every frame from the beginning of a long source.
CONVENTIONAL_SEEK_PREROLL_SECONDS = 2.0
MIN_CONVENTIONAL_FRAMES = 4


def missing_coreml_asset(line: str) -> str:
    """Extract a missing detached-runtime cache name from Topaz FFmpeg output."""
    if "model is not found at url" not in line.lower():
        return ""
    match = re.search(r"coreMLCache/+([^\s/]+)", line, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _probe(ffprobe: Path, video: Path) -> dict:
    command = [str(ffprobe), "-v", "error", "-protocol_whitelist", "file,pipe",
               "-count_frames", "-show_entries",
               "stream=index,codec_type,codec_name,pix_fmt,color_space,color_transfer,color_primaries,width,height,nb_read_frames,avg_frame_rate:format=duration",
               "-of", "json", str(video)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode:
        raise VideoRuntimeError("无法读取视频：" + result.stderr[-500:])
    try:
        data = json.loads(result.stdout)
        streams = data["streams"]
        video_stream = next(item for item in streams if item.get("codec_type") == "video")
        fps = float(Fraction(video_stream["avg_frame_rate"]))
        frames = int(video_stream["nb_read_frames"])
        width, height = int(video_stream["width"]), int(video_stream["height"])
        duration = float(data.get("format", {}).get("duration") or frames / fps)
    except (ValueError, TypeError, KeyError, StopIteration, ZeroDivisionError) as exc:
        raise VideoRuntimeError("视频帧率、尺寸或帧数不可读取") from exc
    if not 0 < fps <= 240 or not 0 < frames or not 0 < width <= 7680 or not 0 < height <= 7680:
        raise VideoRuntimeError("视频帧率、尺寸或帧数超出范围")
    return {**{key: video_stream.get(key, "") for key in ("codec_name", "pix_fmt", "color_space", "color_transfer", "color_primaries")},
            "width": width, "height": height, "fps": fps, "frames": frames,
            "duration": duration, "has_audio": any(item.get("codec_type") == "audio" for item in streams)}


def _stop_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=8)


def _run_process(
    command: list[str], *, environment: dict[str, str], cwd: Path, log: Path,
    cancelled: threading.Event, timeout: float, on_line: Callable[[str], None],
) -> tuple[int, tuple[str, ...]]:
    """Bounded subprocess/log; cancellation also kills descendant processes."""
    log.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors="replace",
                               bufsize=1, start_new_session=True)
    finished = threading.Event()
    expired = threading.Event()

    def watchdog() -> None:
        deadline = time.monotonic() + timeout
        while not finished.wait(0.2):
            if cancelled.is_set() or time.monotonic() >= deadline:
                if not cancelled.is_set():
                    expired.set()
                _stop_group(process)
                return

    monitor = threading.Thread(target=watchdog, daemon=True)
    monitor.start()
    tail: list[str] = []
    written = 0
    code = None
    try:
        assert process.stdout is not None
        with log.open("wb") as stream:
            for line in process.stdout:
                raw = line.encode("utf-8", "replace")
                if written < 4 * 1024 * 1024:
                    chunk = raw[:4 * 1024 * 1024 - written]
                    stream.write(chunk)
                    written += len(chunk)
                tail = (tail + [line.strip()])[-20:]
                try:
                    on_line(line)
                except Exception:
                    # A UI progress callback cannot corrupt an inference run.
                    pass
        code = process.wait(timeout=12)
    finally:
        finished.set()
        if process.poll() is None:
            _stop_group(process)
        if process.stdout is not None:
            process.stdout.close()
        monitor.join(timeout=5)
    if cancelled.is_set():
        return -15, tuple(tail)
    if expired.is_set():
        raise VideoRuntimeError(f"本地视频推理超过 {int(timeout)} 秒，已停止")
    if code is None:
        raise VideoRuntimeError("本地推理子进程未正常退出")
    return code, tuple(tail)


def build_conventional_command(ffmpeg: Path, spec: dict, asset: Path, temporary: Path,
                               width: int, height: int, frames: int) -> list[str]:
    """Keep model lookup offline and parameters limited to the selected model."""
    command = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1"]
    start_seconds = float(spec.get("start_seconds") or 0)
    coarse_seek = max(0.0, start_seconds - CONVENTIONAL_SEEK_PREROLL_SECONDS)
    if coarse_seek:
        command.extend(["-ss", f"{coarse_seek:.8f}"])
    command.extend(["-i", str(asset)])
    precise_seek = start_seconds - coarse_seek
    if precise_seek:
        # Keep this output-side.  Input-only seeking can make tvai_up receive
        # an empty stream for short GOPs; output-side seeking gives it a small,
        # bounded temporal pre-roll instead.
        command.extend(["-ss", f"{precise_seek:.8f}"])
    if spec["max_seconds"]:
        command.extend(["-t", f"{spec['max_seconds']:.8f}"])
    command.extend(["-frames:v", str(frames),
            "-filter_complex", enhancement_filter(spec, width, height),
            *encoding_args(spec.get("encoding", DEFAULT_ENCODING)),
            "-movflags", "+faststart", "-an", str(temporary)])
    return command


def build_precise_command(engine: Path, spec: dict, asset: Path, temporary: Path,
                          width: int, height: int, frames: int, start_frame: int = 0) -> list[str]:
    return [str(engine), "--once", "--input-path", str(asset), "--output-path", str(temporary),
            "--start-frame-idx", str(start_frame), "--end-frame-idx", str(start_frame + frames - 1),
            "--output-width", str(width), "--output-height", str(height),
            "--filters", json.dumps([{"model": "slp-26", "softness": spec["softness"]}], separators=(",", ":")),
            "--ffmpeg-encoding", "-c:v h264_videotoolbox -pix_fmt yuv420p",
            "--device", "0", "--max-gpu-mem", "78"]


def build_audio_mux_command(ffmpeg: Path, rendered: Path, source: Path, output: Path,
                            *, start_seconds: float, duration_seconds: float, slowmo: float = 1) -> list[str]:
    """Restore source audio without letting a short AAC tail drop a video frame.

    AAC streams commonly end a fraction of a frame before their video stream.  A
    bare ``-shortest`` therefore truncates an otherwise complete enhanced video.
    Pad the selected audio first, then let the rendered video remain the shorter
    stream and define the final container duration.
    """
    return [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-i", str(rendered),
            "-ss", f"{start_seconds:.8f}", "-t", f"{duration_seconds:.8f}",
            "-i", str(source), "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", audio_filter(slowmo),
            "-shortest", "-movflags", "+faststart", str(output)]


class TopazVideoRuntime:
    def __init__(self, component_root: Path | str, *, license_model_dir: Path | str | None = None, before_load=None):
        self.before_load = before_load
        self.root = Path(component_root).expanduser().resolve(strict=False)
        self._license_model_dir = license_model_dir

    def license_model_dir(self) -> Path | None:
        return resolve_license_dir(self._license_model_dir)

    def probe_binary(self) -> Path:
        """Prefer a staged probe; system FFprobe is a non-model fallback."""
        for path in (self.root / "precise/ffmpeg/MacOS/ffprobe",
                     self.root / "conventional/Contents/MacOS/ffprobe"):
            if path.is_file() and os.access(path, os.X_OK):
                return path
        executable = shutil.which("ffprobe")
        if not executable:
            raise VideoRuntimeError("本机缺少 ffprobe")
        return Path(executable)

    def status(self) -> dict:
        mac = sys.platform == "darwin" and platform.machine() == "arm64"
        precise = inspect_precise(self.root / "precise") if mac else {"ready": False, "verified": False}
        conventional = inspect_conventional(self.root / "conventional/Contents") if mac else {"ready": False, "models": {}}
        validated = local_validation(self.root / "conventional/Contents") if conventional["ready"] else {}
        licensed_models = self.license_model_dir() if mac else None
        models = []
        for model in MODELS:
            if not mac:
                models.append(public_model(model, available=False, reason="仅支持 Apple Silicon macOS"))
            elif model.id == "precise-26":
                verified = bool(precise["ready"] and precise["verified"])
                reason = "" if verified else "请导入已隔离验证的 Precise 2.6 运行资源"
                models.append(public_model(model, available=verified, verified=verified, reason=reason,
                                           verified_scales=model.scales if verified else ()))
            elif model.id == "precise-25":
                models.append(public_model(model, available=False, reason="未安装独立的 Precise 2.5 权重；不能使用 2.6 冒充"))
            elif model.id == "mini":
                models.append(public_model(model, available=False, reason="本机 Mini 首帧兼容性尚未跑通，暂不开放提交"))
            elif model.stage == "conventional":
                assets_ready = bool(conventional["ready"] and conventional["models"].get(model.id))
                ready = bool(assets_ready and licensed_models)
                verified_scales = tuple(scale for scale in model.scales
                                        if scale in set(validated.get(model.id, ())))
                verified = ready and bool(verified_scales)
                all_scales = set(model.scales).issubset(set(verified_scales))
                scales_label = " / ".join(f"{scale}×" for scale in verified_scales)
                reason = (("本机授权执行器已通过无水印短片验证；长片画质/速度未验收" if all_scales else
                           f"本机授权执行器已通过无水印短片验证（{scales_label}）；其他倍率建议先短测") if verified else
                          "已连接本机授权，尚待本机无水印导出验证" if ready else
                          "本机 Topaz Video 授权不可用；已禁止生成带水印结果" if assets_ready else
                          "请导入此模型的独立 CoreML 运行资源")
                models.append(public_model(model, available=ready, verified=verified, reason=reason,
                                           verified_scales=verified_scales))
            else:
                models.append(public_model(model, available=False, reason="本机未安装此模型的完整权重"))
        capabilities = inspect_features(self.root, conventional_ready=bool(conventional["ready"]),
            precise_ready=bool(precise.get("ready") and precise.get("verified")), licensed=bool(licensed_models))
        return {"engine": "Topaz Video local", "ready": any(item["available"] for item in models), "models": models,
                "processing_ready": bool(conventional["ready"]), "capabilities": capabilities,
                "encoding": {"codecs": ["h264", "hevc", "hevc10"], "container": "mp4", "audio": ["aac", "mute"]}}

    def execute(self, spec: dict, directory: Path, asset: Path, cancelled: threading.Event,
                progress: Callable[[dict], None]) -> tuple[str, str]:
        """Execute one validated video task. Return (status,error) to the task service."""
        from ..runtime_resources import local_accelerator

        try:
            validate_capabilities(spec, self.status())
        except ValueError as exc:
            return "failed", str(exc)
        with local_accelerator(self.root.parent / ".local-inference.lock", cancelled, progress):
            if cancelled.is_set():
                return "cancelled", ""
            if self.before_load:
                self.before_load()
            try:
                self._execute(spec, Path(directory), Path(asset), cancelled, progress)
            except VideoRuntimeError as exc:
                return ("cancelled", "") if cancelled.is_set() else ("failed", str(exc)[:2000])
            return ("cancelled", "") if cancelled.is_set() else ("succeeded", "")

    def _execute(self, spec: dict, directory: Path, asset: Path, cancelled: threading.Event,
                 progress: Callable[[dict], None]) -> None:
        advanced = bool(spec.get("filters")) or spec.get("enhancement") is False
        precise = spec["model"] == "precise-26" and not advanced
        stage = self.root / ("precise" if precise else "conventional/Contents")
        ffmpeg_dir = stage / ("ffmpeg/MacOS" if precise else "MacOS")
        ffmpeg, ffprobe = ffmpeg_dir / "ffmpeg", ffmpeg_dir / "ffprobe"
        source = _probe(ffprobe, asset)
        start_frame = max(0, math.floor(source["fps"] * spec.get("start_seconds", 0)))
        if start_frame >= source["frames"]:
            raise VideoRuntimeError("选区起点超出视频时长")
        available_frames = source["frames"] - start_frame
        frame_count = (min(available_frames, max(1, math.ceil(source["fps"] * spec["max_seconds"])))
                       if spec["max_seconds"] else available_frames)
        if not precise and frame_count < MIN_CONVENTIONAL_FRAMES:
            raise VideoRuntimeError(f"预览区间过短：常规视频模型至少需要 {MIN_CONVENTIONAL_FRAMES} 帧")
        if "hdr" in spec.get("filters", {}) and frame_count < 5:
            raise VideoRuntimeError("Hyperion 2 预览至少需要 5 帧")
        clip_start = start_frame / source["fps"]
        clip_duration = frame_count / source["fps"]
        runtime_spec = {**spec, "start_seconds": clip_start, "max_seconds": clip_duration}
        scale = spec["scale"] if spec.get("enhancement", True) else 1
        width, height = source["width"] * scale, source["height"] * scale
        output_frames, output_fps, slowmo = output_timing(spec, source["fps"], frame_count)
        encoding = spec.get("encoding", DEFAULT_ENCODING)
        if width % 2 or height % 2 or width > 8192 or height > 8192:
            raise VideoRuntimeError("输出尺寸必须为偶数且不超过 8192 像素")
        if advanced:
            # Multi-pass intermediates are deliberately recoverable job-local
            # files, but a long HDR sequence must not fill the user's disk.
            estimated = width * height * (frame_count * 8 + output_frames * (20 if "hdr" in spec.get("filters", {}) else 4))
            if shutil.disk_usage(directory).free < estimated + 512 * 1024 * 1024:
                raise VideoRuntimeError(f"临时空间不足：本次处理预计需要至少 {estimated / 1024**3:.1f} GiB，请缩短选区或清理空间")
        result = directory / "result"
        result.mkdir(parents=True, exist_ok=True)
        temporary = result / f".model-{uuid.uuid4().hex}.mp4"
        final_temp = result / f".enhanced-{uuid.uuid4().hex}.mp4"
        final = result / "enhanced.mp4"
        if final.exists():
            raise VideoRuntimeError("目标结果已存在，不覆盖")
        environment = {**os.environ, "PATH": os.pathsep.join([str(ffmpeg_dir), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
                       "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1"}
        work = directory / f".pipeline-{uuid.uuid4().hex}"
        if advanced:
            plan = build_plan(self.root, work, runtime_spec, asset, temporary,
                              width=width, height=height, frames=frame_count, fps=source["fps"])
            passes = plan.passes
        elif precise:
            command = build_precise_command(stage / "neuroserver/neuroserver", spec, asset,
                                            temporary, width, height, frame_count, start_frame)
            if "encoding" in spec:
                import shlex
                command[command.index("--ffmpeg-encoding") + 1] = shlex.join(encoding_args(encoding))
            passes = [Pass("本地视频增强", command, "neuro")]
        else:
            passes = [Pass("本地视频增强", build_conventional_command(
                ffmpeg, runtime_spec, asset, temporary, width, height, frame_count), "licensed")]
        if any(step.engine == "neuro" for step in passes):
            home = directory / "runtime-home"
            home.mkdir(exist_ok=True)
            environment.update({"HOME": str(home), "XDG_CACHE_HOME": str(home / ".cache"),
                                "TOPAZ_MODEL_STORE": str(self.root / "precise/models")})
        if any(step.engine == "licensed" for step in passes):
            license_models = self.license_model_dir()
            if not license_models:
                raise VideoRuntimeError("本机 Topaz Video 授权不可用；为避免水印已停止任务")
            # Model binaries and weights remain in the detached stage.  Only
            # the current machine's license-bearing metadata directory is
            # referenced, matching the activated App's own FFmpeg execution.
            environment.update({"TVAI_MODEL_DIR": str(license_models),
                                "TVAI_MODEL_DATA_DIR": str(self.root / "conventional/Contents/Resources/models")})
        progress({"stage": "本地视频增强", "message": "正在准备模型", "percent": 2})
        observed_percent = 0
        success_marker = False
        license_checkout = False
        watermark_rejected = False
        missing_model_assets: set[str] = set()
        ffmpeg_fields: dict[str, str] = {}
        pass_index = 0
        current_pass = passes[0]

        def emit_progress(fraction: float, message: str) -> None:
            nonlocal observed_percent
            percent = min(95, max(2, int((pass_index + min(1, max(0, fraction))) / len(passes) * 95)))
            if percent > observed_percent:
                observed_percent = percent
                progress({"stage": current_pass.label, "message": message[:200], "percent": percent})

        def on_line(line: str) -> None:
            nonlocal observed_percent, success_marker, license_checkout, watermark_rejected
            lowered = line.lower()
            missing_asset = missing_coreml_asset(line)
            if missing_asset:
                missing_model_assets.add(missing_asset)
            if "license checkout successful owned" in lowered:
                license_checkout = True
            if ("parseauth got detailsnull" in lowered
                    or "watermark will be enabled" in lowered
                    or "adding watermark" in lowered
                    or "applying watermark" in lowered):
                watermark_rejected = True
            if current_pass.engine == "neuro":
                if "single_shot_process status: TopServingErrorCode.OK" in line:
                    success_marker = True
                if not line.startswith("{"):
                    return
                try:
                    event = json.loads(line).get("message")
                    if isinstance(event, dict) and isinstance(event.get("progress"), (int, float)):
                        emit_progress(event["progress"] / 100, str(event.get("message") or "正在推理"))
                except (ValueError, TypeError):
                    return
            elif "=" in line:
                key, value = line.strip().split("=", 1)
                if key in {"frame", "fps", "out_time_ms", "progress"}:
                    ffmpeg_fields[key] = value
                if key == "progress":
                    try:
                        fraction = int(ffmpeg_fields.get("frame", "0")) / output_frames
                    except ValueError:
                        return
                    emit_progress(fraction, f"已处理 {ffmpeg_fields.get('frame', '0')} 帧")

        timeout = min(24 * 3600, max(1800, frame_count * 120)) if precise else min(4 * 3600, max(600, frame_count * 15))
        try:
            if advanced:
                work.mkdir()
                if "hdr" in spec.get("filters", {}):
                    (work / "pq").mkdir()
            for pass_index, current_pass in enumerate(passes):
                if cancelled.is_set():
                    return
                success_marker = license_checkout = watermark_rejected = False
                ffmpeg_fields.clear()
                missing_model_assets.clear()
                pass_env = dict(environment)
                if current_pass.engine == "neuro":
                    pass_env["PATH"] = str(self.root / "precise/ffmpeg/MacOS") + os.pathsep + environment["PATH"]
                progress({"stage": current_pass.label, "message": current_pass.label,
                          "percent": max(2, int(pass_index / len(passes) * 95))})
                code, tail = _run_process(current_pass.command, environment=pass_env,
                    cwd=(self.root / "precise/neuroserver" if current_pass.engine == "neuro" else work if advanced else ffmpeg_dir),
                    log=directory / (f"runtime-{pass_index}.log" if advanced else "runtime.log"), cancelled=cancelled,
                    timeout=max(timeout, 1800) if current_pass.engine == "neuro" else timeout, on_line=on_line)
                if cancelled.is_set():
                    return
                if code != 0 or (current_pass.engine == "neuro" and not success_marker):
                    if missing_model_assets:
                        names = "、".join(sorted(missing_model_assets))
                        raise VideoRuntimeError(f"模型资源不完整，缺少适配当前画面尺寸的 CoreML 变体：{names}")
                    if spec["model"] == "precise-26" and any("[broadcast_shapes]" in line for line in tail):
                        raise VideoRuntimeError("Starlight Precise 2.6 不兼容当前素材尺寸；请改用 Proteus / Rhea 等常规模型。原生错误已保留在任务日志。")
                    raise VideoRuntimeError(current_pass.label + "失败：" + " | ".join(tail[-5:])[-1000:])
                if watermark_rejected:
                    raise VideoRuntimeError("推理进程进入水印回退路径；已拒绝发布结果")
                if current_pass.engine == "licensed" and not license_checkout:
                    raise VideoRuntimeError("Topaz 授权未被推理进程接受；已拒绝发布带水印结果")
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise VideoRuntimeError("视频模型未生成文件")
            rendered = _probe(ffprobe, temporary)
            if rendered["frames"] != output_frames or (rendered["width"], rendered["height"]) != (width, height):
                raise VideoRuntimeError("模型结果帧数或尺寸不匹配")
            if source["has_audio"] and encoding["audio"] != "mute":
                progress({"stage": "封装结果", "message": "正在恢复原音轨", "percent": 96})
                mux = build_audio_mux_command(
                    ffmpeg, temporary, asset, final_temp,
                    start_seconds=clip_start, duration_seconds=clip_duration, slowmo=slowmo,
                )
                code, tail = _run_process(mux, environment=environment, cwd=ffmpeg_dir,
                                          log=directory / "mux.log", cancelled=cancelled, timeout=300,
                                          on_line=lambda _line: None)
                if cancelled.is_set():
                    return
                if code:
                    raise VideoRuntimeError("恢复原音轨失败：" + " | ".join(tail[-3:])[-700:])
                temporary.unlink(missing_ok=True)
            else:
                temporary.replace(final_temp)
            final_info = _probe(ffprobe, final_temp)
            if final_info["frames"] != output_frames or (final_info["width"], final_info["height"]) != (width, height):
                raise VideoRuntimeError(
                    "封装后视频校验失败："
                    f"帧数 {final_info['frames']}/{output_frames}，"
                    f"尺寸 {final_info['width']}x{final_info['height']}/{width}x{height}"
                )
            if abs(final_info["fps"] - output_fps) > 0.02:
                raise VideoRuntimeError("输出帧率与补帧配置不匹配")
            if "hdr" in spec.get("filters", {}) and (final_info.get("color_transfer") != "smpte2084"
                    or final_info.get("color_primaries") != "bt2020" or "10" not in final_info.get("pix_fmt", "")):
                raise VideoRuntimeError("HDR 输出未保留 10-bit / BT.2020 / PQ 色彩信息")
            if cancelled.is_set():
                return
            try:
                os.link(final_temp, final)
            except FileExistsError as exc:
                raise VideoRuntimeError("结果已存在，不覆盖") from exc
            provenance = {
                "schema": 1,
                "engine": "topaz_video_local",
                "model": spec["model"],
                "task_kind": spec.get("task_kind", "export"),
                "start_seconds": clip_start,
                "enhancement": spec.get("enhancement", True), "filters": spec.get("filters", {}),
                "encoding": encoding, "time_scale": slowmo,
                "watermark_verified": True,
                "verification": ("licensed_topaz_checkout" if any(step.engine == "licensed" for step in passes)
                                 else "precise_engine_no_watermark_baseline" if any(step.engine == "neuro" for step in passes)
                                 else "local_video_encoding"),
                "media": {
                    "width": final_info["width"],
                    "height": final_info["height"],
                    "fps": final_info["fps"],
                    "duration_seconds": final_info["duration"],
                    "frames": final_info["frames"],
                    "time_scale": slowmo, "codec": final_info.get("codec_name", ""),
                    "pixel_format": final_info.get("pix_fmt", ""), "hdr": "hdr" in spec.get("filters", {}),
                },
            }
            (result / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            progress({"stage": "处理完成", "message": "视频结果已保存", "percent": 100})
        finally:
            temporary.unlink(missing_ok=True)
            final_temp.unlink(missing_ok=True)
            if work.exists():
                shutil.rmtree(work)
