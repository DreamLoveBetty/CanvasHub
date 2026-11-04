"""MOSS domain request contracts. No filesystem, HTTP or model imports."""
from __future__ import annotations

import copy
import json
import re
import secrets

TASK_TYPE = "moss-image"
ENGINE = "moss-image-mlx"
DEFAULT_MODEL_ID = "moss-image-sft-mflux-bf16"
DEFAULT_PRESET = "turbo"
MODES = ("text", "layout", "storyboard")
TERMINAL = {"succeeded", "succeeded_no_telegram", "failed", "telegram_failed", "canceled", "cancelled"}
WORKER_PREFIX = "MOSS_WORKER_EVENT "
MAX_JSON_BYTES = 256 * 1024
MAX_TOKENS = 4096
MAX_NEGATIVE_CHARS = 20_000
MAX_FREE_REGIONS = 64
# Global prompt, plus the text and caption of every free region.
MAX_TEXT_SOURCES = 1 + 2 * MAX_FREE_REGIONS
MAX_LORA_UPLOAD = 2 * 1024**3
MAX_LORAS = 4
LORA_SCALE_MIN, LORA_SCALE_MAX = -20, 20
SIZE_MIN, SIZE_MAX, SIZE_MULTIPLE = 256, 2048, 16
MAX_PIXELS = 2_097_152
SEED_MAX = 2**32 - 1
SOURCE_FIELDS = ("prompt", "text", "caption")
SAMPLER_COMMON = {"negative_prompt": "", "uncond_skip_layers": [22], "max_sequence_length": MAX_TOKENS,
                  "transformer_precision": "bf16", "vae_decode_precision": "fp32"}
PRESETS = {
    "turbo": {"label": "Turbo",
              "managed_adapters": [{"id": "student", "scale": 1.0}, {"id": "destripe", "scale": 1.5}],
              "sampler": {**SAMPLER_COMMON, "name": "author_hybrid_turbo", "updates": 10, "network_passes": 15,
                          "teacher_cfg": 3, "student_cfg": 1, "training_steps": 50, "training_shift": 5,
                          "finish_solver": "dpmpp_2m"}},
    "standard": {"label": "标准",
                 "managed_adapters": [{"id": "destripe", "scale": 1.5}],
                 "sampler": {**SAMPLER_COMMON, "name": "euler", "steps": 50, "cfg": 3, "shift": 5}},
}
JOB_FIELDS = {"mode", "base_model_id", "preset", "width", "height", "seed", "prompt", "negative_prompt", "layout_draft", "loras",
              "telegram_enabled", "draw_grid", "split_panels", "text_sources", "input_fingerprint"}
COMPILE_FIELDS = {"mode", "base_model_id", "preset", "width", "height", "prompt", "negative_prompt", "layout_draft",
                  "input_fingerprint", "draft_json"}
SOURCE_REQUIRED = {"source_node_id", "target_id", "field", "content_hash"}


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 包含重复字段：{key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"JSON 不允许 {value}")


def strict_json_loads(raw):
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("JSON 内容无效")
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON 请求不能超过 256 KiB")
    try:
        value = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_reject_duplicates,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, RecursionError, json.JSONDecodeError) as error:
        raise ValueError("JSON 内容无效") from error
    if not isinstance(value, dict):
        raise ValueError("JSON 顶层必须是对象")
    return value


def normalize_model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", value):
        raise ValueError("Base 模型 ID 无效")
    return value


def normalize_asset_id(value):
    value = value.removeprefix("sha256:") if isinstance(value, str) else ""
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("LoRA 资产 ID 无效")
    return value


def check_fields(body, allowed, location="请求"):
    if not isinstance(body, dict):
        raise ValueError(f"{location}必须为对象")
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ValueError(f"{location}包含未知字段：{unknown[0]}")


def integer(value, name, lo, hi):
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} 必须是整数")
    if not lo <= value <= hi:
        raise ValueError(f"{name} 必须在 {lo}–{hi} 之间")
    return value


def _number(value, name, lo, hi):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} 必须是数字")
    # Range first: NaN fails every comparison, and JSON integers can exceed the float range.
    if not lo <= value <= hi:
        raise ValueError(f"{name} 必须在 {lo}–{hi} 之间")
    return float(value)


def _flag(body, name, default=False):
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{name} 必须是布尔值")
    return value


def _label(value, name, limit=128):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} 无效")
    return value


def _fingerprint(body):
    value = body.get("input_fingerprint")
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", value):
        raise ValueError("输入指纹无效")
    return value


def validate_size(width, height):
    width = integer(width, "宽度", SIZE_MIN, SIZE_MAX)
    height = integer(height, "高度", SIZE_MIN, SIZE_MAX)
    if width % SIZE_MULTIPLE or height % SIZE_MULTIPLE:
        raise ValueError(f"宽度和高度必须为 {SIZE_MULTIPLE} 的倍数")
    if width * height > MAX_PIXELS:
        raise ValueError(f"总像素不能超过 {MAX_PIXELS}")
    return width, height


def _generation_input(body):
    """Fields shared by generate and compile, validated identically."""
    mode = body.get("mode", "text")
    if mode not in MODES:
        raise ValueError("未知 MOSS 工作模式")
    prompt = body.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("提示词必须是文本")
    if mode == "text" and not prompt.strip():
        raise ValueError("普通文生图须填写提示词")
    negative = body.get("negative_prompt", "")
    if not isinstance(negative, str):
        raise ValueError("负面提示词必须是文本")
    negative = negative.strip()
    if len(negative) > MAX_NEGATIVE_CHARS:
        raise ValueError("负面提示词过长")
    draft = body.get("layout_draft")
    if mode == "text":
        if "layout_draft" in body:
            raise ValueError("普通模式不能携带布局草稿")
    elif not isinstance(draft, dict):
        raise ValueError("布局模式须提供已解析草稿")
    preset = body.get("preset", DEFAULT_PRESET)
    if not isinstance(preset, str) or preset not in PRESETS:
        raise ValueError("未知 MOSS 推理预设")
    width, height = validate_size(body.get("width", 1024), body.get("height", 1024))
    return {"mode": mode, "prompt": prompt, "negative_prompt": negative, "layout_draft": draft, "preset": preset,
            "base_model_id": normalize_model_id(body.get("base_model_id", DEFAULT_MODEL_ID)),
            "width": width, "height": height}


def _loras(value):
    if not isinstance(value, list):
        raise ValueError("LoRA 参数无效")
    if len(value) > MAX_LORAS:
        raise ValueError(f"最多添加 {MAX_LORAS} 个普通 LoRA")
    loras, seen = [], set()
    for raw in value:
        check_fields(raw, {"asset_id", "scale"}, "LoRA 参数")
        asset = normalize_asset_id(raw.get("asset_id"))
        if asset in seen:
            raise ValueError("同一 LoRA 不能重复添加")
        seen.add(asset)
        loras.append({"asset_id": asset, "scale": _number(raw.get("scale", 1), "LoRA 强度",
                                                         LORA_SCALE_MIN, LORA_SCALE_MAX)})
    return loras


def _text_sources(value):
    """Audit trace only: never carries canvas state and does not prove a node's identity."""
    if not isinstance(value, list) or len(value) > MAX_TEXT_SOURCES:
        raise ValueError("文本来源记录无效")
    result = []
    for raw in value:
        check_fields(raw, SOURCE_REQUIRED | {"source_alias"}, "文本来源")
        if not SOURCE_REQUIRED <= raw.keys():
            raise ValueError("文本来源记录不完整")
        if raw["field"] not in SOURCE_FIELDS:
            raise ValueError("文本来源字段无效")
        if not isinstance(raw["content_hash"], str) or not re.fullmatch(r"[a-f0-9]{64}", raw["content_hash"]):
            raise ValueError("文本来源 hash 无效")
        _label(raw["source_node_id"], "文本来源节点")
        _label(raw["target_id"], "文本来源目标")
        if "source_alias" in raw:
            _label(raw["source_alias"], "文本来源别名", 120)
        result.append(dict(raw))
    return result


def _seed(value):
    if value is None or value == "":
        return secrets.randbits(32)
    return integer(value, "Seed", 0, SEED_MAX)


def normalize_job(body):
    check_fields(body, JOB_FIELDS, "任务参数")
    result = _generation_input(body)
    storyboard = result["mode"] == "storyboard"
    draw_grid = _flag(body, "draw_grid")
    if draw_grid and not storyboard:
        raise ValueError("draw_grid 仅分镜模式可用")
    split_panels = _flag(body, "split_panels", True)
    preset = PRESETS[result["preset"]]
    # Both presets read the negative through the CFG branch (turbo through its teacher CFG); it costs no extra pass.
    sampler = {**copy.deepcopy(preset["sampler"]), "negative_prompt": result["negative_prompt"]}
    return {**result, "seed": _seed(body.get("seed")), "loras": _loras(body.get("loras", [])),
            "telegram_enabled": _flag(body, "telegram_enabled"), "draw_grid": draw_grid,
            "split_panels": split_panels and storyboard, "text_sources": _text_sources(body.get("text_sources", [])),
            "input_fingerprint": _fingerprint(body), "sampler": sampler,
            "managed_adapters": copy.deepcopy(preset["managed_adapters"])}


def normalize_compile(body):
    check_fields(body, COMPILE_FIELDS, "编译参数")
    fingerprint = _fingerprint(body)
    if "draft_json" not in body:
        return {"kind": "compile", **_generation_input(body), "input_fingerprint": fingerprint}
    if set(body) - {"draft_json", "input_fingerprint"}:
        raise ValueError("draft_json 与其他编译字段互斥")
    draft_json = body["draft_json"]
    if not isinstance(draft_json, str) or not draft_json.strip() or len(draft_json.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("draft_json 无效")
    return {"kind": "import", "draft_json": draft_json, "input_fingerprint": fingerprint}


def catalog(models=()):
    return {"models": list(models), "presets": [{"id": key, **copy.deepcopy(value)} for key, value in PRESETS.items()],
            "limits": {"width": [SIZE_MIN, SIZE_MAX], "height": [SIZE_MIN, SIZE_MAX],
                       "dimension_multiple": SIZE_MULTIPLE, "max_pixels": MAX_PIXELS, "max_tokens": MAX_TOKENS,
                       "free_regions": MAX_FREE_REGIONS, "lora_count": MAX_LORAS,
                       "lora_scale": [LORA_SCALE_MIN, LORA_SCALE_MAX], "seed": [0, SEED_MAX]},
            "defaults": {"mode": "text", "preset": DEFAULT_PRESET, "base_model_id": DEFAULT_MODEL_ID,
                         "width": 1024, "height": 1024, "split_panels": True, "draw_grid": False}}
