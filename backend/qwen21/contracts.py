"""Qwen domain request contracts. No filesystem, HTTP or model imports."""
from __future__ import annotations

import math
import re
import secrets

from .profiles import ADAPTERS, DEFAULT_PRESET, LEGACY_PRESETS, PRESETS, TURBO_PRESET, canonical_preset

REVISION = "adcbe85975760d545ca142069713781929898be0"
TASK_TYPE = "qwen21-image"
ENGINE = "qwen-image-2.1-mlx"
DEFAULT_MODEL_ID = "qwen-image-2.1-heretic-mlx-8bit"
EXPORT_FORMATS = {
    "8bit": {"label": "MLX 8-bit", "group_size": 64, "quantized_linear_count": 228},
    "bf16": {"label": "BF16 · 不量化", "group_size": None, "quantized_linear_count": 0},
}
MODEL_REPO = "vanch007/Qwen-Image-2.1-Heretic-mlx-8bit"
MODEL_REVISION = "6b81cbc376cb23069cc92df6084cf0f8cb9c9b88"
TURBO_REPO = "Viggle/Qwen-Image-2.1-viggle-turbo"
# Preserve imports of the initial release constants; profile metadata is canonical.
TURBO_REVISION = ADAPTERS["viggle-v021-r128"]["revision"]
TURBO_FILENAME = ADAPTERS["viggle-v021-r128"]["filename"]
TURBO_SIZE = ADAPTERS["viggle-v021-r128"]["size"]
TURBO_SHA256 = ADAPTERS["viggle-v021-r128"]["sha256"]
MAX_IMAGE_UPLOAD = 32 * 1024**2
MAX_LORA_UPLOAD = 2 * 1024**3
MAX_LORAS = 4
TERMINAL = {"succeeded", "succeeded_no_telegram", "failed", "telegram_failed", "canceled", "cancelled"}
ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9")


def normalize_model_id(value):
    value = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", value) or value in {".", ".."}:
        raise ValueError("Base 模型 ID 无效")
    return value


def normalize_asset_id(value):
    value = str(value or "").removeprefix("sha256:").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("LoRA 资产 ID 无效")
    return value


def integer(value, name, lo, hi):
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    try:
        result = int(value)
        if float(value) != result:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是整数") from None
    if not lo <= result <= hi:
        raise ValueError(f"{name} 必须在 {lo}–{hi} 之间")
    return result


def number(value, name, lo, hi):
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{name} 必须是数字") from None
    if not math.isfinite(result) or not lo <= result <= hi:
        raise ValueError(f"{name} 必须在 {lo}–{hi} 之间")
    return result


def normalize_job(body):
    if not isinstance(body, dict):
        raise ValueError("任务参数必须为对象")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 20_000:
        raise ValueError("提示词须为 1–20000 个字符")
    mode = str(body.get("mode") or "text")
    if mode not in {"text", "edit"}:
        raise ValueError("未知 Qwen 工作模式")
    requested_preset = str(body.get("preset") or DEFAULT_PRESET)
    preset = canonical_preset(requested_preset)
    if preset not in PRESETS:
        raise ValueError("未知 Qwen 推理预设")
    tokens = body.get("reference_upload_tokens") or []
    limit = PRESETS[preset]["max_references"]
    if not isinstance(tokens, list) or len(tokens) > limit or any(
            not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{32}", x) for x in tokens):
        raise ValueError(f"该预设最多支持 {limit} 张有效参考图")
    if mode == "edit" and not tokens:
        raise ValueError("参考图编辑须连接至少 1 张图片")
    if mode == "text" and tokens:
        raise ValueError("文生图模式不能携带编辑参考图")
    width = integer(body.get("width", 1024), "宽度", 256, 2048)
    height = integer(body.get("height", 1024), "高度", 256, 2048)
    if width % 32 or height % 32:
        raise ValueError("宽度和高度必须为 32 的倍数")
    default_steps = LEGACY_PRESETS.get(requested_preset, (preset, PRESETS[preset]["steps"]))[1]
    steps = integer(body.get("steps", default_steps), "步数", PRESETS[preset]["min_steps"],
                    PRESETS[preset]["max_steps"])
    guidance = number(body.get("guidance", 1), "CFG", 1, 10)
    negative = str(body.get("negative_prompt") or "").strip()
    if len(negative) > 20_000:
        raise ValueError("负向提示词过长")
    if preset != "standard" and (guidance != 1 or negative):
        raise ValueError("Viggle / Turbo 须使用 CFG=1，且不支持负向提示词")
    raw_loras = body.get("loras") or []
    if not isinstance(raw_loras, list) or len(raw_loras) > MAX_LORAS:
        raise ValueError(f"最多添加 {MAX_LORAS} 个普通 LoRA")
    loras, seen = [], set()
    for raw in raw_loras:
        if not isinstance(raw, dict):
            raise ValueError("LoRA 参数无效")
        asset = normalize_asset_id(raw.get("asset_id"))
        if asset in seen:
            raise ValueError("同一 LoRA 不能重复添加")
        seen.add(asset)
        loras.append({"asset_id": asset, "scale": number(raw.get("scale", 1), "LoRA 强度", 0, 2)})
    seed = body.get("seed")
    seed = secrets.randbits(32) if seed is None or str(seed).strip() in {"", "random", "-1"} else integer(seed, "Seed", 0, 2**32 - 1)
    ratio = str(body.get("aspect_ratio") or "custom")
    if ratio not in ASPECT_RATIOS and ratio != "custom":
        raise ValueError("未知画幅比例")
    return {"prompt": prompt, "mode": mode, "preset": preset,
            "base_model_id": normalize_model_id(body.get("base_model_id") or DEFAULT_MODEL_ID),
            "width": width, "height": height, "aspect_ratio": ratio,
            "steps": steps, "image_count": integer(body.get("image_count", 1), "张数", 1, 4),
            "seed": seed, "guidance": guidance, "negative_prompt": negative,
            "reference_upload_tokens": tokens, "reference_resolution": 1024,
            "loras": loras, "telegram_enabled": body.get("telegram_enabled") is True}


def catalog(models=()):
    return {"models": list(models), "presets": [{"id": key, **value} for key, value in PRESETS.items()],
            "aspect_ratios": list(ASPECT_RATIOS),
            "limits": {"width": [256, 2048], "height": [256, 2048], "dimension_multiple": 32,
                       "lora_count": MAX_LORAS, "references": {"standard": 10, "viggle": 3, "turbo": PRESETS[TURBO_PRESET]["max_references"]}},
            "defaults": {"mode": "text", "preset": DEFAULT_PRESET, "base_model_id": DEFAULT_MODEL_ID,
                         "width": 1024, "height": 1024, "steps": 6, "guidance": 1,
                         "image_count": 1, "aspect_ratio": "1:1"}}
