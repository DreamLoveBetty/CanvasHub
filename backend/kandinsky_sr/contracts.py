"""Pure stdlib contracts, parameter validation, and tiling math for Kandinsky ImageSR 2.0."""
from __future__ import annotations

import math
from typing import Any, Dict

ENGINE = "kandinsky_imagesr_2_0"
MODEL_ID = "kandinsky-imagesr-2.0"
MODEL_KEY = "kandinsky-imagesr-2.0"
MODEL_LABEL = "Kandinsky ImageSR 2.0"
PYTHON_VERSION = "3.12"
EVENT_PREFIX = "KSR_EVENT "
PREPARE_PREFIX = "KSR_PREPARE "
TIMEOUT_SECONDS = 3600
TILE_SIZE = 1024

UPSCALE_FACTORS = (2, 4)
CREATIVITY_MIN = 0
CREATIVITY_MAX = 8
OVERLAP_CHOICES = (0.125, 0.25, 0.375)

DEFAULT_OPTIONS: Dict[str, Any] = {
    "upscale_factor": 2,
    "creativity": 4,
    "overlap": 0.25,
}

CREATIVITY_TIMESTEPS: Dict[int, tuple[float, ...]] = {
    2: (0.07, 0.086, 0.118, 0.134, 0.15, 0.18, 0.21, 0.27, 0.30),
    4: (0.17, 0.1885, 0.207, 0.2255, 0.244, 0.278, 0.312, 0.346, 0.38),
}

CREATIVITY_LABELS: tuple[str, ...] = (
    "0 · 极致保真",
    "1 · 高度保真",
    "2 · 偏保真",
    "3 · 轻度增强",
    "4 · 标准推荐",
    "5 · 细节增强",
    "6 · 创意增强",
    "7 · 强细节重绘",
    "8 · 最大创意",
)


def _parse_int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} 参数类型无效")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 参数必须是整数") from exc
    if not math.isfinite(num) or num != int(num):
        raise ValueError(f"{name} 参数必须是整数")
    return int(num)


def _parse_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} 参数类型无效")
    try:
        num = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 参数必须是数字") from exc
    if not math.isfinite(num):
        raise ValueError(f"{name} 参数无效")
    return num


def normalize_model(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return MODEL_ID
    if text != MODEL_ID:
        raise ValueError("不支持的 Kandinsky SR 模型")
    return MODEL_ID


def normalize_options(raw: Any = None) -> Dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_OPTIONS)
    if not isinstance(raw, dict):
        raise ValueError("Kandinsky SR 参数必须为对象")

    factor_raw = raw.get("upscale_factor", raw.get("upscaleFactor"))
    if factor_raw is None or factor_raw == "":
        upscale_factor = DEFAULT_OPTIONS["upscale_factor"]
    else:
        upscale_factor = _parse_int(factor_raw, "放大倍率")
        if upscale_factor not in UPSCALE_FACTORS:
            raise ValueError("放大倍率仅支持 2 或 4")

    creativity_raw = raw.get("creativity")
    if creativity_raw is None or creativity_raw == "":
        creativity = DEFAULT_OPTIONS["creativity"]
    else:
        creativity = _parse_int(creativity_raw, "创意度")
        if not CREATIVITY_MIN <= creativity <= CREATIVITY_MAX:
            raise ValueError("创意度必须在 0 到 8 之间")

    overlap_raw = raw.get("overlap")
    if overlap_raw is None or overlap_raw == "":
        overlap = DEFAULT_OPTIONS["overlap"]
    else:
        overlap_val = _parse_float(overlap_raw, "分块重叠")
        matched = next((choice for choice in OVERLAP_CHOICES if abs(overlap_val - choice) <= 1e-6), None)
        if matched is None:
            raise ValueError("分块重叠仅支持 0.125、0.25 或 0.375")
        overlap = matched

    return {
        "upscale_factor": upscale_factor,
        "creativity": creativity,
        "overlap": overlap,
    }


def creativity_to_timestep(upscale_factor: int, creativity: int) -> float:
    table = CREATIVITY_TIMESTEPS.get(int(upscale_factor))
    if table is None:
        raise ValueError("放大倍率仅支持 2 或 4")
    level = int(creativity)
    if not 0 <= level < len(table):
        raise ValueError("创意度必须在 0 到 8 之间")
    return float(table[level])


def _axis_positions(length: int, tile: int, stride: int) -> int:
    if length <= tile:
        return 1
    positions = list(range(0, length - tile, stride))
    if positions[-1] + tile < length:
        positions.append(length - tile)
    return len(positions)


def estimate_tile_count(
    width: int,
    height: int,
    upscale_factor: int,
    overlap: float = 0.25,
    tile_size: int = TILE_SIZE,
) -> int:
    w = max(1, int(width))
    h = max(1, int(height))
    factor = int(upscale_factor)
    lq_tile = tile_size // factor
    stride = max(1, int(lq_tile * (1.0 - float(overlap))))
    padded_w = max(w, lq_tile)
    padded_h = max(h, lq_tile)
    return _axis_positions(padded_h, lq_tile, stride) * _axis_positions(padded_w, lq_tile, stride)


def catalog_entry(ready: bool, reasons: list[str] | None = None, factor: int = 2) -> dict[str, Any]:
    return {
        "id": MODEL_ID,
        "label": MODEL_LABEL,
        "route": "kandinsky_sr_local",
        "scale": int(factor),
        "available": bool(ready),
        "error": (reasons[0] if reasons else "") if not ready else "",
    }
