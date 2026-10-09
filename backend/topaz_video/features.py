"""Path-free processing contracts and offline feature capability discovery.

Enhancement models remain in catalog.py. These are composable video filters,
not aliases for enhancement models. A descriptor alone never implies readiness.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path


FEATURE_MODELS = {
    "chf-3": ("Chronos Fast", "chf-v3-"),
    "chr-2": ("Chronos", "chr-v2-"),
    "apo-8": ("Apollo", "apo-v8-"),
    "apf-2": ("Apollo Fast", "apf-v2-"),
    "thm-2": ("Themis", "thm-v2-"),
    "ref-2": ("全帧修复", "ref-v2-"),
    "cpe-2": ("相机轨迹", "cpe-v2-"),
    "ifi-1": ("稳定插帧", "ifi-v1-"),
    "nyx-3": ("Nyx 3", "nyx-v3-"),
}
INTERPOLATION_MODELS = ("chf-3", "chr-2", "apo-8", "apf-2")
CODECS = {"h264": ("h264_videotoolbox", "yuv420p"),
          "hevc": ("hevc_videotoolbox", "yuv420p"),
          "hevc10": ("hevc_videotoolbox", "p010le")}
DEFAULT_ENCODING = {"codec": "h264", "bitrate_mbps": 0, "audio": "aac"}


def _object(value, keys, label):
    if not isinstance(value, dict) or set(value) - set(keys):
        raise ValueError(f"{label} 包含不支持的参数")
    return value


def _number(value, low, high, label, *, integer=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not low <= value <= high or not math.isfinite(value)
            or (integer and int(value) != value)):
        raise ValueError(f"{label} 须为 {low}–{high} 范围内的{'整数' if integer else '有限数字'}")
    return value


def normalize_processing(body: dict) -> dict:
    enabled = body.get("enhancement", True)
    if not isinstance(enabled, bool):
        raise ValueError("enhancement 须为布尔值")
    filters = _object(body.get("filters", {}), ("denoise", "interpolation", "stabilization", "motion_deblur", "hdr"), "filters")
    result = {}
    for key, raw in filters.items():
        if key == "denoise":
            _object(raw, ("noise", "details"), key)
            result[key] = {"noise": _number(raw.get("noise", 0), 0, 1, "noise"),
                           "details": _number(raw.get("details", 0), 0, 1, "details")}
        elif key == "interpolation":
            _object(raw, ("model", "fps", "slowmo", "rdt"), key)
            model = raw.get("model", "chf-3")
            if model not in INTERPOLATION_MODELS:
                raise ValueError("未知补帧模型")
            fps = _number(raw.get("fps", 60), 0, 120, "fps")
            if fps and fps < 1:
                raise ValueError("fps 须为 0（跟随原片）或 1–120")
            result[key] = {"model": model, "fps": fps,
                           "slowmo": _number(raw.get("slowmo", 1), 1, 16, "slowmo"),
                           "rdt": _number(raw.get("rdt", 0.01), -0.01, 0.2, "rdt")}
        elif key == "stabilization":
            _object(raw, ("mode", "strength", "rolling_shutter", "reduce_jitter"), key)
            mode = raw.get("mode", "auto_crop")
            if mode not in ("auto_crop", "full_frame"):
                raise ValueError("未知稳定模式")
            roll = raw.get("rolling_shutter", False)
            if not isinstance(roll, bool):
                raise ValueError("rolling_shutter 须为布尔值")
            result[key] = {"mode": mode, "strength": _number(raw.get("strength", 6), 0, 16, "strength"),
                           "rolling_shutter": roll,
                           "reduce_jitter": _number(raw.get("reduce_jitter", 0), 0, 5, "reduce_jitter", integer=True)}
        elif key == "motion_deblur":
            _object(raw, ("model",), key)
            if raw.get("model", "thm-2") != "thm-2":
                raise ValueError("未知运动去模糊模型")
            result[key] = {"model": "thm-2"}
        else:
            _object(raw, ("model", "strength"), key)
            if raw.get("model", "hyp-2") != "hyp-2" or raw.get("strength", 1) not in (0.7, 1.0, 1.3) or isinstance(raw.get("strength"), bool):
                raise ValueError("Hyperion 2 强度仅支持 0.7 / 1 / 1.3")
            result[key] = {"model": "hyp-2", "strength": raw.get("strength", 1)}
    encoding = {**DEFAULT_ENCODING, **_object(body.get("encoding", {}), DEFAULT_ENCODING, "encoding")}
    if (not isinstance(encoding["codec"], str) or encoding["codec"] not in CODECS
            or encoding["audio"] not in ("aac", "mute")):
        raise ValueError("不支持的编码器或音轨策略")
    _number(encoding["bitrate_mbps"], 0, 200, "bitrate_mbps")
    if "hdr" in result and encoding["codec"] != "hevc10":
        raise ValueError("HDR 输出须选择 H.265 10-bit，避免丢失动态范围")
    return {"enhancement": enabled, "filters": result, "encoding": encoding}


def inspect_features(root: Path, *, conventional_ready: bool, precise_ready: bool, licensed: bool) -> dict:
    models = root / "conventional/Contents/Resources/models"
    try:
        manifest = json.loads((models.parents[1] / "topaz-video-stage.json").read_text())
        sizes = manifest.get("model_file_sizes", {})
        helpers = manifest.get("helper_file_sizes", {})
        sizes = sizes if isinstance(sizes, dict) else {}
        helpers = helpers if isinstance(helpers, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        sizes, helpers = {}, {}

    def intact(name):
        path = models / name
        return bool(Path(name).name == name and name in sizes and path.is_file() and not path.is_symlink()
                    and 0 < path.stat().st_size == sizes[name])

    def choice(ident):
        label, prefix = FEATURE_MODELS[ident]
        weights = [name for name in sizes if name.startswith(prefix) and name.endswith(".tz3")]
        ready = bool(conventional_ready and intact(ident + ".json") and weights and all(map(intact, weights)))
        available = ready and licensed
        return {"id": ident, "label": label, "available": available,
                "reason": "" if available else "本机授权不可用" if ready else f"尚未导入 {label} 完整权重"}

    interpolation = [choice(key) for key in INTERPOLATION_MODELS]
    deblur, cpe, ref, ifi, denoise = (choice(key) for key in ("thm-2", "cpe-2", "ref-2", "ifi-1", "nyx-3"))
    try:
        stage = root / "precise"
        data = json.loads((stage / "topaz-video-stage.json").read_text())
        blobs = data.get("neuro_model_file_sizes", {}).get("hyp-2", {})
        helper = root / "conventional/Contents/MacOS/oiiotool"
        hdr = bool(conventional_ready and precise_ready and helper.is_file() and not helper.is_symlink() and os.access(helper, os.X_OK)
                   and helper.stat().st_size == helpers.get("oiiotool")
                   and isinstance(blobs, dict) and len(blobs) >= 43 and all(
            Path(name).name == name and
            (stage / "models/hyp-2" / name).is_file()
            and not (stage / "models/hyp-2" / name).is_symlink()
            and 0 < (stage / "models/hyp-2" / name).stat().st_size == size
            for name, size in blobs.items()))
    except (OSError, ValueError, TypeError, AttributeError):
        hdr = False
    return {
        "denoise": {"available": denoise["available"], "reason": denoise["reason"]},
        "interpolation": {"available": any(item["available"] for item in interpolation), "models": interpolation,
                          "reason": "请先在 Topaz 下载补帧模型，再离线同步运行资源"},
        "motion_deblur": {"available": deblur["available"], "models": [deblur], "reason": deblur["reason"]},
        "stabilization": {"available": cpe["available"], "full_frame": cpe["available"] and ref["available"],
                          "jitter": interpolation[0]["available"] and ifi["available"], "reason": cpe["reason"]},
        "hdr": {"available": hdr, "models": [{"id": "hyp-2", "label": "Hyperion 2", "available": hdr}],
                "reason": "" if hdr else "请导入 Hyperion 2 权重、已验证的 Neuroserver 和配套色彩转换工具"},
    }


def validate_capabilities(spec: dict, status: dict) -> None:
    if spec.get("enhancement", True):
        entry = next((entry for entry in status["models"] if entry["id"] == spec["model"]), None)
        if not entry or not entry["available"]:
            raise ValueError(entry.get("reason") or "增强模型不可用" if entry else "未知模型")
    elif not status.get("processing_ready", False):
        raise ValueError("本地视频编码运行时尚未就绪")
    capabilities = status.get("capabilities", {})
    for key, value in spec.get("filters", {}).items():
        feature = capabilities.get(key, {})
        if not feature.get("available"):
            raise ValueError(feature.get("reason") or f"{key} 运行资源尚未就绪")
        if key in ("interpolation", "motion_deblur") and not any(
                item["id"] == value["model"] and item["available"] for item in feature.get("models", [])):
            raise ValueError(f"{value['model']} 模型权重尚未就绪")
        if key == "stabilization":
            if value["mode"] == "full_frame" and not feature.get("full_frame"):
                raise ValueError("全帧稳定还需要 Refine 模型权重")
            if (value["rolling_shutter"] or value["reduce_jitter"]) and not feature.get("jitter"):
                raise ValueError("滚动快门 / 抖动修复还需要 Chronos Fast 和 IFI 权重")


def encoding_args(encoding: dict, *, hdr=False) -> list[str]:
    codec, pixels = CODECS[encoding["codec"]]
    args = ["-c:v", codec, "-pix_fmt", pixels, "-allow_sw", "1"]
    if encoding["codec"] != "h264":
        args += ["-tag:v", "hvc1"]
    if encoding["bitrate_mbps"]:
        args += ["-b:v", f"{encoding['bitrate_mbps']:g}M"]
    if hdr:
        args += ["-color_primaries", "bt2020", "-color_trc", "smpte2084", "-colorspace", "bt2020nc"]
    return args
