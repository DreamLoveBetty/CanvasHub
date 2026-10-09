"""Krea 2 request and component contracts; no HTTP, storage or MLX imports."""
from __future__ import annotations

import math
import re
import secrets

from .edit_profile import (DEFAULT_EDIT_ADAPTER_SCALE, DEFAULT_GROUNDING_PX,
                           DEFAULT_REFERENCE_STRENGTH, EDIT_MODE, FIT_MODES,
                           MODES, STANDARD_MODE)


REVISION = "3d01ab823cfd969298332c2f9540d4cc822c4450"
MFLUX_VERSION = "0.18.1"
MFLUX_WHEEL_SHA256 = "1b98bab53f9da0cb4d1e8deaa819342ba2f8aa72a3965f47a4fa769c72ccf784"
TASK_TYPE = "krea2-image"
MAX_IMAGE_UPLOAD = 32 * 1024 * 1024
MAX_LORA_UPLOAD = 2 * 1024 * 1024 * 1024
MAX_LORAS = 4
TERMINAL = {"succeeded", "succeeded_no_telegram", "failed", "telegram_failed", "canceled"}
ASPECT_RATIOS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9")

BUILTIN_MODEL_IDS = {
    "8bit": "krea-2-turbo-alis-mlx-8bit",
    "mixed-4-8": "krea-2-turbo-alis-mlx-mixed-4-8",
}
DEFAULT_MODEL_ID = BUILTIN_MODEL_IDS["8bit"]

# Export formats are independent of downloadable built-ins. BF16 is available
# only for a registered custom Transformer; it must not add a download target.
EXPORT_FORMATS = {
    "8bit": {"label": "8-bit", "recipe": "quantize_bulk", "group_size": 64,
             "quantized_linear_count": 224},
    "mixed-4-8": {"label": "Mixed 4/8-bit", "recipe": "mixed_4_8", "group_size": 64,
                  "quantized_linear_count": 224},
    "bf16": {"label": "BF16 · 不量化", "recipe": "none", "group_size": None,
             "quantized_linear_count": 0},
}

BUILDS = {
    "8bit": {
        "label": "8-bit · 最佳质量",
        "repo": "avlp12/Krea-2-Turbo-Alis-MLX-8bit",
        "repo_revision": "9fc879fe1d77d5d8abf0c916a968d3a40171d25b",
        "filename": "transformer_8bit.safetensors",
        "size": 14_244_836_620,
        "sha256": "b10f33f0dcd91772990e7cecfc8003ba4d3f1ba27f03010b6d17a1f490f80a6c",
    },
    "mixed-4-8": {
        "label": "Mixed 4/8-bit · 节省磁盘",
        "repo": "avlp12/Krea-2-Turbo-Alis-MLX-mixed-4-8",
        "repo_revision": "fdcbdb23cc2e662514064f648e77c2d271053b30",
        "filename": "transformer_mixed_4_8.safetensors",
        "size": 9_840_816_670,
        "sha256": "985d60722b339c3cd9df16a173f0cb504ae93d81ce9fbe2c3ab158cf5b60a5fb",
    },
}
BASE_REPO = "krea/Krea-2-Turbo"
BASE_REVISION = "98e0fe118d17c9e3547fbb2e25acdbae2cadf7c7"
SAFETY_REPO = "Falconsai/nsfw_image_detection"
SAFETY_REVISION = "96cb0d0342c7afb80cab76ecc58b265fa44da256"


def _integer(value, name, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if number < low or number > high:
        raise ValueError(f"{name} 必须在 {low}–{high} 之间")
    return number


def _number(value, name, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if not math.isfinite(number) or number < low or number > high:
        raise ValueError(f"{name} 必须在 {low}–{high} 之间")
    return number


def normalize_asset_id(value):
    raw = str(value or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    if not re.fullmatch(r"[a-f0-9]{64}", raw):
        raise ValueError("LoRA 资产 ID 无效")
    return raw


def normalize_model_id(value):
    raw = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", raw):
        raise ValueError("Base 权重模型 ID 无效")
    return raw


def normalize_job(body):
    if not isinstance(body, dict):
        raise ValueError("请求必须为对象")
    prompt = str(body.get("prompt") or "").strip()
    if not prompt or len(prompt) > 10_000:
        raise ValueError("请输入有效提示词（不超过 10000 字）")
    precision = str(body.get("precision") or "8bit")
    if precision == "bf16" and not body.get("base_model_id"):
        raise ValueError("BF16 须选择已转换的 Base 权重模型")
    if precision not in EXPORT_FORMATS:
        if not body.get("base_model_id"):
            raise ValueError("未知 Krea 2 模型构建")
        precision = "8bit"
    base_model_id = normalize_model_id(
        body.get("base_model_id") or BUILTIN_MODEL_IDS[precision])
    width = _integer(body.get("width", 1024), "宽度", 256, 2048)
    height = _integer(body.get("height", 1024), "高度", 256, 2048)
    if width % 16 or height % 16:
        raise ValueError("宽度和高度必须是 16 的倍数")
    aspect_ratio = str(body.get("aspect_ratio") or "").strip()
    if aspect_ratio and aspect_ratio not in (*ASPECT_RATIOS, "custom"):
        raise ValueError("未知画幅比例")
    if not aspect_ratio:
        divisor = math.gcd(width, height)
        reduced = f"{width // divisor}:{height // divisor}"
        aspect_ratio = reduced if reduced in ASPECT_RATIOS else "custom"
    steps = _integer(body.get("steps", 8), "步数", 1, 50)
    image_count = _integer(body.get("image_count", 1), "图片数量", 1, 4)
    seed_value = body.get("seed")
    if seed_value in (None, "", "random"):
        seed = secrets.randbits(63)
    else:
        seed = _integer(seed_value, "Seed", 0, 2**63 - 1)
    mode = str(body.get("mode") or STANDARD_MODE).strip().lower()
    if mode not in MODES:
        raise ValueError("未知 Krea 2 工作模式")
    strength = _number(body.get("strength", 0.6), "重绘强度", 0.01, 1.0)
    init_image_upload_token = str(body.get("init_image_upload_token") or "").strip()
    edit_image_upload_token = str(body.get("edit_image_upload_token") or "").strip()
    edit_adapter_asset_id = str(body.get("edit_adapter_asset_id") or "").strip()
    edit_adapter_scale = _number(
        body.get("edit_adapter_scale", DEFAULT_EDIT_ADAPTER_SCALE),
        "编辑 LoRA 强度", 0.01, 2.0)
    reference_strength = _number(
        body.get("reference_strength", DEFAULT_REFERENCE_STRENGTH),
        "参考图保真", 0.01, 20.0)
    grounding_px = _integer(
        body.get("grounding_px", DEFAULT_GROUNDING_PX), "语义识图尺寸", 0, 2048)
    if grounding_px and (grounding_px < 256 or grounding_px % 32):
        raise ValueError("语义识图尺寸必须为 0，或 256–2048 之间的 32 倍数")
    fit_mode = str(body.get("fit_mode") or "fit").strip().lower()
    if fit_mode not in FIT_MODES:
        raise ValueError("未知参考图适配方式")
    if mode == EDIT_MODE:
        if not edit_image_upload_token:
            raise ValueError("指令编辑必须连接 1 张源图")
        edit_adapter_asset_id = normalize_asset_id(edit_adapter_asset_id)
        if init_image_upload_token:
            raise ValueError("指令编辑不能同时提交传统重绘输入")
    elif edit_image_upload_token or edit_adapter_asset_id:
        raise ValueError("编辑源图和编辑 LoRA 只能用于指令编辑模式")
    raw_loras = body.get("loras") or []
    regular_limit = MAX_LORAS - 1 if mode == EDIT_MODE else MAX_LORAS
    if not isinstance(raw_loras, list) or len(raw_loras) > regular_limit:
        if mode == EDIT_MODE:
            raise ValueError(
                f"指令编辑最多加载 {regular_limit} 个普通 LoRA，另加 1 个编辑 LoRA")
        raise ValueError(f"一次最多加载 {MAX_LORAS} 个 LoRA")
    loras = []
    seen = set()
    for raw in raw_loras:
        if not isinstance(raw, dict):
            raise ValueError("LoRA 参数格式无效")
        asset_id = normalize_asset_id(raw.get("asset_id"))
        if asset_id in seen:
            raise ValueError("同一 LoRA 不能重复添加")
        seen.add(asset_id)
        loras.append({"asset_id": asset_id, "scale": _number(raw.get("scale", 1), "LoRA 强度", 0, 2)})
    if edit_adapter_asset_id and edit_adapter_asset_id in seen:
        raise ValueError("编辑 LoRA 不能在普通 LoRA 栈中重复加载")
    return {
        "prompt": prompt,
        "mode": mode,
        "base_model_id": base_model_id,
        "precision": precision,
        "aspect_ratio": aspect_ratio,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "image_count": image_count,
        "strength": strength,
        "init_image_upload_token": init_image_upload_token,
        "edit_image_upload_token": edit_image_upload_token,
        "edit_adapter_asset_id": edit_adapter_asset_id,
        "edit_adapter_scale": edit_adapter_scale,
        "reference_strength": reference_strength,
        "grounding_px": grounding_px,
        "fit_mode": fit_mode,
        "loras": loras,
        "safety_enabled": body.get("safety_enabled") is True,
        "telegram_enabled": body.get("telegram_enabled") is True,
    }


def catalog(models=None):
    return {
        "builds": [
            {"id": key, "label": value["label"], "download_bytes": value["size"]}
            for key, value in BUILDS.items()
        ],
        "aspect_ratios": list(ASPECT_RATIOS),
        "limits": {
            "width": [256, 2048],
            "height": [256, 2048],
            "dimension_multiple": 16,
            "steps": [1, 50],
            "image_count": [1, 4],
            "lora_count": MAX_LORAS,
            "lora_scale": [0, 2],
            "edit_adapter_scale": [0.01, 2],
            "reference_strength": [0.01, 20],
            "grounding_px": [0, 2048],
        },
        "models": list(models or []),
        "defaults": {"mode": STANDARD_MODE, "base_model_id": DEFAULT_MODEL_ID,
                     "precision": "8bit", "aspect_ratio": "1:1", "width": 1024,
                     "height": 1024, "steps": 8, "image_count": 1, "strength": 0.6,
                     "edit_adapter_scale": DEFAULT_EDIT_ADAPTER_SCALE,
                     "reference_strength": DEFAULT_REFERENCE_STRENGTH,
                     "grounding_px": DEFAULT_GROUNDING_PX, "fit_mode": "fit",
                     "safety_enabled": False},
    }
