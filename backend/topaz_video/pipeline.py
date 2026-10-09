"""Build an explicit, offline multi-pass video plan (no task or process state).

Runtime owns the GPU lease, cancellation, subprocesses and publication gate.
Every intermediate is job-local. Camera estimation consumes exactly the selected
clip; interpolation changes both the expected frame count and audio time mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import shlex

from .catalog import BY_ID
from .features import DEFAULT_ENCODING, encoding_args


@dataclass(frozen=True)
class Pass:
    label: str
    command: list[str]
    engine: str = "ffmpeg"  # ffmpeg | licensed | neuro


@dataclass(frozen=True)
class Plan:
    passes: list[Pass]
    frames: int
    fps: float
    slowmo: float


def output_timing(spec: dict, source_fps: float, frames: int) -> tuple[int, float, float]:
    interpolation = spec.get("filters", {}).get("interpolation", {})
    fps = float(interpolation.get("fps") or source_fps)
    slowmo = float(interpolation.get("slowmo", 1))
    return max(1, math.ceil(frames / source_fps * fps * slowmo - 1e-7)), fps, slowmo


def enhancement_filter(spec: dict, width: int, height: int) -> str:
    model = BY_ID[spec["model"]]
    parts = [f"model={model.backend_name}", "scale=0", f"w={width}", f"h={height}",
             "device=0", "instances=0", "download=0"]
    parts.extend(f"{key}={spec[key]:g}" for key in model.parameter_keys)
    return "tvai_up=" + ":".join(parts)


def build_plan(root: Path, work: Path, spec: dict, source: Path, output: Path,
               *, width: int, height: int, frames: int, fps: float) -> Plan:
    ffmpeg = root / "conventional/Contents/MacOS/ffmpeg"
    neuro = root / "precise/neuroserver/neuroserver"
    filters = spec.get("filters", {})
    encoding = spec.get("encoding", DEFAULT_ENCODING)
    out_frames, out_fps, slowmo = output_timing(spec, fps, frames)
    base = [str(ffmpeg), "-hide_banner", "-nostdin", "-y", "-nostats", "-progress", "pipe:1"]
    intermediate = ["-c:v", "prores_ks", "-profile:v", "2", "-pix_fmt", "yuv422p10le", "-an"]
    current = work / "clip.mov"
    passes = [Pass("准备选区", base + ["-ss", f"{spec.get('start_seconds', 0):.8f}", "-i", str(source),
                  "-frames:v", str(frames), *intermediate, str(current)])]
    chain = []
    stabilization = filters.get("stabilization")
    if stabilization:
        passes.append(Pass("分析相机轨迹", base + ["-i", str(current), "-vf",
            "tvai_cpe=model=cpe-2:filename=cpe.json:device=0:download=0", "-an", "-f", "null", "-"], "licensed"))
        chain.append("tvai_stb=model=ref-2:filename=cpe.json:device=0:download=0:"
                     f"full={int(stabilization['mode'] == 'full_frame')}:smoothness={stabilization['strength']:g}:"
                     f"roll={int(stabilization['rolling_shutter'])}:reduce={stabilization['reduce_jitter']}")
    if "motion_deblur" in filters:
        chain.append("tvai_up=model=thm-2:scale=1:device=0:instances=0:download=0")
    if "denoise" in filters:
        denoise = filters["denoise"]
        chain.append(f"tvai_up=model=nyx-3:scale=1:noise={denoise['noise']:g}:details={denoise['details']:g}:device=0:instances=0:download=0")
    precise = spec.get("enhancement", True) and spec["model"] == "precise-26"
    if spec.get("enhancement", True) and not precise:
        chain.append(enhancement_filter(spec, width, height))
    if chain:
        # Auto-crop legitimately changes the native dimensions. Explicitly
        # resize its safe area to the selected output size (no hidden crop).
        target = work / "processed.mov"
        chain.append(f"scale={width if not precise else width // spec['scale']}:{height if not precise else height // spec['scale']}")
        passes.append(Pass("稳定 / 去模糊 / 增强", base + ["-i", str(current), "-vf", ",".join(chain),
                      "-frames:v", str(frames), *intermediate, str(target)], "licensed"))
        current = target
    if precise:
        target = work / "precise.mov"
        passes.append(Pass("Starlight Precise 增强", [str(neuro), "--once", "--input-path", str(current),
            "--output-path", str(target), "--start-frame-idx", "0", "--end-frame-idx", str(frames - 1),
            "--output-width", str(width), "--output-height", str(height), "--filters",
            json.dumps([{"model": "slp-26", "softness": spec["softness"]}], separators=(",", ":")),
            "--ffmpeg-encoding", shlex.join(intermediate[:-1]), "--device", "0", "--max-gpu-mem", "78"], "neuro"))
        current = target
    tail_filters = []
    if "interpolation" in filters:
        option = filters["interpolation"]
        # Native FI interpolates between samples, so its last sample has no
        # successor. One cloned input-frame tail preserves the source duration.
        tail_filters.append(f"tpad=stop_mode=clone:stop_duration={1 / fps:.8f}")
        tail_filters.append(f"tvai_fi=model={option['model']}:fps={out_fps:g}:slowmo={slowmo:g}:"
                            f"rdt={option['rdt']:g}:device=0:instances=0:download=0")
    is_hdr = "hdr" in filters
    target = work / "interpolated.mov" if is_hdr and tail_filters else output
    if not is_hdr or tail_filters:
        command = base + ["-i", str(current)]
        if tail_filters:
            command += ["-vf", ",".join(tail_filters)]
        command += ["-frames:v", str(out_frames), "-r", f"{out_fps:g}"]
        command += intermediate if is_hdr else [*encoding_args(encoding), "-an", "-movflags", "+faststart"]
        passes.append(Pass("补帧 / 慢动作" if tail_filters else "编码视频", command + [str(target)],
                           "licensed" if tail_filters else "ffmpeg"))
        current = target
    if is_hdr:
        passes.append(Pass("Hyperion 2 · HDR 线性帧", [str(neuro), "--once", "--input-path", str(current),
            "--output-path", str(work / "hdr"), "--output-codec", "exr", "--output-bit-depth", "16",
            "--start-frame-idx", "0", "--end-frame-idx", str(out_frames - 1),
            "--output-width", str(width), "--output-height", str(height), "--filters",
            json.dumps([{"model": "hyp-2", "enhancement_strength": filters["hdr"]["strength"], "scale": 1}], separators=(",", ":")),
            "--device", "0", "--max-gpu-mem", "78"], "neuro"))
        # Hyperion 2's native HDR output is scene-linear ACES2065-1 EXR;
        # setting PQ tags on its SDR movie would NOT create real HDR. Use the
        # bundled OCIO ACES display transform, then encode the PQ pixels.
        passes.append(Pass("ACES → HDR10 · 1000 nits", [str(root / "conventional/Contents/MacOS/oiiotool"),
            "--frames", f"0-{out_frames - 1}", str(work / "hdr/frame_%06d.exr"),
            "--colorconfig", "ocio://default", "--iscolorspace", "ACES2065-1",
            "--ociodisplay", "Rec.2100-PQ - Display", "ACES 2.0 - HDR 1000 nits (Rec.2020)",
            "-d", "uint16", "-o", str(work / "pq/frame_%06d.tif")]))
        passes.append(Pass("编码 HDR10", base + ["-framerate", f"{out_fps:g}", "-i", str(work / "pq/frame_%06d.tif"),
            "-vf", "format=gbrp16le,zscale=matrixin=gbr:primariesin=bt2020:transferin=smpte2084:rangein=full:matrix=bt2020nc:primaries=bt2020:transfer=smpte2084:range=limited,format=yuv420p10le",
            "-frames:v", str(out_frames), *encoding_args(encoding, hdr=True), "-an", "-movflags", "+faststart", str(output)]))
    return Plan(passes, out_frames, out_fps, slowmo)


def audio_filter(slowmo: float) -> str:
    parts = []
    speed = 1 / slowmo
    while speed < 0.5:
        parts.append("atempo=0.5")
        speed *= 2
    if abs(speed - 1) > 1e-8:
        parts.append(f"atempo={speed:g}")
    return ",".join([*parts, "apad"])
