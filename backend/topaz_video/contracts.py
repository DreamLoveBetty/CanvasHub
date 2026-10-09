"""Public, path-free task inputs for the independent Topaz Video domain."""
from __future__ import annotations

import math
import re

from .catalog import BY_ID, PARAMETERS
from .features import normalize_processing


MAX_UPLOAD = 200 * 1024 * 1024
MAX_SECONDS = 600
MAX_START_SECONDS = 24 * 60 * 60
ACTIVE = frozenset({"queued", "running", "cancelling"})


def identifier(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("无效 Topaz Video 标识")
    return value


def normalize(body: object) -> dict:
    if not isinstance(body, dict):
        raise ValueError("请求必须为对象")
    model = BY_ID.get(body.get("model")) if isinstance(body.get("model"), str) else None
    if model is None:
        raise ValueError("未知 Topaz Video 模型")
    allowed = {"asset_id", "model", "scale", "task_kind", "start_seconds", "max_seconds",
               "enhancement", "filters", "encoding", *model.parameter_keys}
    if set(body) - allowed:
        raise ValueError("包含不支持的模型参数")
    scales = (1,) if body.get("enhancement") is False else model.scales
    scale = body.get("scale", scales[0] if scales else None)
    if isinstance(scale, bool) or not isinstance(scale, int) or scale not in scales:
        raise ValueError("此模型或倍率当前不可用")
    task_kind = body.get("task_kind", "export")
    if task_kind not in {"preview", "export"}:
        raise ValueError("task_kind 仅支持 preview 或 export")
    start = body.get("start_seconds", 0)
    if (isinstance(start, bool) or not isinstance(start, (int, float))
            or not math.isfinite(start) or not 0 <= start <= MAX_START_SECONDS):
        raise ValueError(f"start_seconds 须为 0–{MAX_START_SECONDS} 秒有限数字")
    seconds = body.get("max_seconds", 0)
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or not 0 <= seconds <= MAX_SECONDS):
        raise ValueError(f"max_seconds 须为 0–{MAX_SECONDS} 秒有限数字（0 表示处理至片尾）")
    if task_kind == "preview" and seconds <= 0:
        raise ValueError("预览任务必须提供大于 0 的 max_seconds")
    spec = {"asset_id": identifier(body.get("asset_id")), "model": model.id,
            "scale": scale, "task_kind": task_kind,
            "start_seconds": float(start), "max_seconds": float(seconds)}
    for key in model.parameter_keys:
        definition = PARAMETERS[key]
        value = body.get(key, definition["default"])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} 须为有限数字")
        if not definition["min"] <= value <= definition["max"]:
            raise ValueError(f"{key} 超出范围")
        if key == "softness" and int(value) != value:
            raise ValueError("softness 须为整数")
        if key == "gsize" and int(value) != value:
            raise ValueError("gsize 须为 0–5 整数（0 表示自动）")
        spec[key] = int(value) if key == "softness" else float(value)
    if any(key in body for key in ("enhancement", "filters", "encoding")):
        spec.update(normalize_processing(body))
    return spec
