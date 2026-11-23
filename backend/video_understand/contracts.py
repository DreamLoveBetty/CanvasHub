"""Bounded request contracts and mode presets for WeMM-Video understanding; pure stdlib, no I/O."""
from __future__ import annotations

import re
from typing import Any, Dict

ENGINE = "wemm_video_mlx"
MODEL_KEY = "wemm-video-35ba3b-mlx-6bit"
MODEL_LABEL = "WeMM-Video 35B-A3B MLX 6-bit"
PYTHON_VERSION = "3.12"
EVENT_PREFIX = "WEMM_EVENT "
PREPARE_PREFIX = "WEMM_PREPARE "
ACTIVE = frozenset({"queued", "running", "cancelling"})
TIMEOUT_SECONDS = 1800
MAX_QUEUE_DEPTH = 8
MAX_PROMPT_CHARS = 8000
MAX_URL_CHARS = 2048

MODES: Dict[str, Dict[str, Any]] = {
    "storyboard": {
        "label": "电影拉片 · 分镜反推",
        "fps": 1.5,
        "max_frames": 96,
        "total_pixels": 4194304,
        "max_tokens": 6144,
        "shot_anchors": True,
    },
    "prompt_reverse": {
        "label": "视频提示词反推",
        "fps": 1.0,
        "max_frames": 64,
        "total_pixels": 2097152,
        "max_tokens": 2048,
        "shot_anchors": False,
    },
    "h3_prompt": {
        "label": "H3 提示词反推",
        "fps": 2.0,
        "max_frames": 96,
        "total_pixels": 4194304,
        "max_tokens": 4096,
        "shot_anchors": True,
        "min_shot_sec": 0.8,
    },
    "summary": {
        "label": "音画摘要与台词",
        "fps": 1.0,
        "max_frames": 64,
        "total_pixels": 2097152,
        "max_tokens": 3072,
        "shot_anchors": False,
    },
    "custom": {
        "label": "自定义分析",
        "fps": 1.0,
        "max_frames": 64,
        "total_pixels": 2097152,
        "max_tokens": 2048,
        "shot_anchors": False,
    },
}


def identifier(value: Any) -> str:
    """Validate a 32-character lowercase hexadecimal job identifier."""
    text = str(value or "").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", text):
        raise ValueError("任务 ID 无效")
    return text


def _bounded_float(value: Any, name: str, lo: float, hi: float, fallback: float) -> float:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数字") from exc
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        raise ValueError(f"{name} 必须为有限数字")
    return max(lo, min(hi, parsed))


def _bounded_int(value: Any, name: str, lo: int, hi: int, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须为整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为整数") from exc
    return max(lo, min(hi, parsed))


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ValueError("布尔参数格式无效")


def normalize(body: Any) -> Dict[str, Any]:
    """Validate and normalize a video_understand submit payload."""
    if not isinstance(body, dict):
        raise ValueError("请求体必须为 JSON 对象")

    video_url = str(body.get("video_url") or "").strip()
    if not video_url or len(video_url) > MAX_URL_CHARS:
        raise ValueError("缺少有效视频地址")

    mode = str(body.get("mode") or "storyboard").strip()
    if mode not in MODES:
        raise ValueError("不支持的分析模式")
    defaults = MODES[mode]

    prompt = str(body.get("prompt") or "").strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"指令长度不能超过 {MAX_PROMPT_CHARS} 字")
    if mode == "custom" and not prompt:
        raise ValueError("自定义分析模式需要填写提问或接入文本节点")

    return {
        "video_url": video_url,
        "mode": mode,
        "prompt": prompt,
        "use_audio": _bool(body.get("use_audio"), True),
        "thinking": _bool(body.get("thinking"), False),
        "shot_anchors": _bool(body.get("shot_anchors"), bool(defaults["shot_anchors"])),
        "fps": round(_bounded_float(body.get("fps"), "fps", 0.25, 4.0, float(defaults["fps"])), 2),
        "max_frames": _bounded_int(body.get("max_frames"), "max_frames", 4, 128, int(defaults["max_frames"])),
        "total_pixels": _bounded_int(
            body.get("total_pixels"), "total_pixels", 262144, 8388608, int(defaults["total_pixels"])
        ),
        "max_tokens": _bounded_int(body.get("max_tokens"), "max_tokens", 128, 8192, int(defaults["max_tokens"])),
        "min_shot_sec": round(
            _bounded_float(body.get("min_shot_sec"), "min_shot_sec", 0.4, 5.0, float(defaults.get("min_shot_sec", 1.2))),
            2,
        ),
        "temperature": round(_bounded_float(body.get("temperature"), "temperature", 0.0, 1.0, 0.0), 2),
    }
