#!/usr/bin/env python3
"""Prompt-skill model discovery and text polishing helpers."""

from __future__ import annotations

import json
import os
import re
import requests
import sys
import time
import urllib.error
import urllib.request
import base64
import binascii
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

from .app_config import (
    BASE_DIR,
    DEFAULT_GPT_TRANSPORT_MODE,
    DEFAULT_PROMPT_SKILL_ID,
    DEFAULT_PROMPT_SKILL_PROVIDER,
    GPT_REASONING_EFFORTS,
    get_gpt_provider_config,
    get_prompt_skill_config,
    load_app_settings,
)
from .prompt_library import built_in_templates

CODEX_SCRIPTS_DIR = BASE_DIR / "backend" / "codex_image_runtime" / "scripts"
if str(CODEX_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(CODEX_SCRIPTS_DIR))

try:
    from codex_api import (  # type: ignore
        CodexAPIError,
        build_text_request,
        codex_headers,
        extract_text,
        get_auth as get_codex_auth,
        iter_sse_events,
        post_responses,
        post_responses_stream,
        _codex_api_base as codex_api_base,
    )
except Exception:  # pragma: no cover - surfaced as runtime provider errors
    CodexAPIError = RuntimeError  # type: ignore
    build_text_request = None  # type: ignore
    codex_headers = None  # type: ignore
    extract_text = None  # type: ignore
    get_codex_auth = None  # type: ignore
    iter_sse_events = None  # type: ignore
    post_responses = None  # type: ignore
    post_responses_stream = None  # type: ignore
    codex_api_base = None  # type: ignore

try:
    from .managed_codex_oauth import (  # type: ignore
        get_auth_status as get_managed_codex_oauth_status,
        get_provider_env as get_managed_codex_provider_env,
    )
except Exception:  # pragma: no cover - managed OAuth is optional at runtime
    get_managed_codex_oauth_status = None  # type: ignore
    get_managed_codex_provider_env = None  # type: ignore

try:
    from .provider_chatgpt_pool import chat_chatgpt_pool  # type: ignore
except Exception:  # pragma: no cover - account-pool fallback is optional
    chat_chatgpt_pool = None  # type: ignore

try:
    from PIL import Image, ImageOps, UnidentifiedImageError  # type: ignore
except Exception:  # pragma: no cover - Pillow is optional for prompt text-only helpers
    Image = None  # type: ignore
    ImageOps = None  # type: ignore
    UnidentifiedImageError = Exception  # type: ignore


PROMPT_SKILL_DIR = BASE_DIR / "prompt_skills"
DEFAULT_MODEL_CACHE = Path.home() / ".codex" / "models_cache.json"
DEFAULT_TIMEOUT_SECONDS = int(os.environ.get("PROMPT_SKILL_TIMEOUT", "180"))
GPT_OAUTH_RETRY_ATTEMPTS = int(os.environ.get("PROMPT_SKILL_GPT_OAUTH_RETRIES", "3"))
GPT_OAUTH_RETRY_DELAY_SECONDS = float(os.environ.get("PROMPT_SKILL_GPT_OAUTH_RETRY_DELAY", "1.5"))
PROMPT_IMAGE_ANALYSIS_MAX_EDGE = int(os.environ.get("PROMPT_IMAGE_ANALYSIS_MAX_EDGE", "1800"))
PROMPT_IMAGE_ANALYSIS_MAX_BYTES = int(os.environ.get("PROMPT_IMAGE_ANALYSIS_MAX_BYTES", str(3 * 1024 * 1024)))
PROMPT_IMAGE_ANALYSIS_JPEG_QUALITY = int(os.environ.get("PROMPT_IMAGE_ANALYSIS_JPEG_QUALITY", "86"))
PROMPT_IMAGE_ANALYSIS_MIN_JPEG_QUALITY = int(os.environ.get("PROMPT_IMAGE_ANALYSIS_MIN_JPEG_QUALITY", "68"))
PROMPT_IMAGE_ANALYSIS_POOL_TIMEOUT_SECONDS = int(os.environ.get("PROMPT_IMAGE_ANALYSIS_POOL_TIMEOUT", "120"))
MIN_FULL_PROMPT_CHARS = int(os.environ.get("PROMPT_SKILL_MIN_FULL_CHARS", "900"))
MIN_FULL_PROMPT_PARAGRAPHS = int(os.environ.get("PROMPT_SKILL_MIN_FULL_PARAGRAPHS", "5"))
MODULE_ORDER = [f"M{index}" for index in range(15)]
PERSON_HINTS = (
    "人物",
    "人像",
    "女性",
    "女人",
    "女孩",
    "男性",
    "男人",
    "男孩",
    "角色",
    "网红",
    "模特",
    "肖像",
    "妻子",
    "母亲",
    "妈妈",
    "孕妇",
    "孕期",
    "孕肚",
)
FEMALE_HINTS = ("女性", "女人", "女孩", "美女", "女网红", "成熟女性", "东亚女性", "亚洲女性", "妻子", "孕妇", "母亲", "妈妈")
PHOTO_HINTS = ("照片", "摄影", "写真", "自拍", "人像", "肖像", "真实", "网红", "社交媒体", "商业人像", "抓拍", "纪实", "记录")
MOBILE_PHOTO_HINTS = ("手机", "抓拍", "随手拍", "POV", "pov", "爸爸", "妈妈", "丈夫", "妻子", "生活纪实", "家庭记录")
PREGNANCY_HINTS = ("怀孕", "孕期", "孕妇", "孕肚", "孕晚期", "胎动", "孕期记录", "孕期纪念")
SCENE_HINTS = ("场景", "背景", "空间", "街", "室内", "室外", "咖啡馆", "城市", "自然光", "摄影棚", "卧室", "客厅", "家居", "家庭")
TEXTURE_HINTS = ("质感", "材质", "皮肤", "发丝", "服装", "面料", "反光", "纹理", "金属", "玻璃", "磨砂", "皮革", "丝绸", "树脂", "PVC", "涂装")
FORMAT_HINTS = (
    "壁纸",
    "海报",
    "手办",
    "设计稿",
    "UI",
    "界面",
    "信息图",
    "Logo",
    "logo",
    "包装",
    "封面",
    "头像",
    "Banner",
    "banner",
    "详情页",
    "图标",
    "产品图",
    "多图合成",
    "修图",
)
PRODUCT_HINTS = ("产品", "商品", "包装", "瓶", "鞋", "手办", "玩具", "模型", "道具", "设备", "家具", "摆件")
STRUCTURE_HINTS = ("姿态", "动作", "结构", "形体", "造型", "轮廓", "组件", "按钮", "卡片", "布局", "版式", "站姿", "坐姿", "手势", "网格")
STYLE_HINTS = ("风格", "赛博", "复古", "极简", "可爱", "3A", "二次元", "插画", "像素", "国潮", "品牌", "电影感", "CG", "动漫", "海报", "壁纸")
LAYOUT_HINTS = ("构图", "画幅", "比例", "景别", "机位", "视角", "透视", "留白", "居中", "网格", "对齐", "排版")
MEDIUM_HINTS = PHOTO_HINTS + MOBILE_PHOTO_HINTS + ("插画", "3D", "CG", "渲染", "手办", "设计稿", "UI", "界面", "壁纸", "海报", "信息图", "Logo", "logo")
LIGHTING_HINTS = (
    "光线",
    "光影",
    "色彩",
    "配色",
    "颜色",
    "色调",
    "渐变",
    "深色",
    "浅色",
    "明暗",
    "亮度",
    "对比",
    "自然光",
    "窗光",
    "逆光",
    "侧光",
    "补光",
    "直闪",
    "轮廓光",
    "发丝光",
    "暗部",
    "高光",
    "低曝光",
    "曝光",
    "烟雾",
)
HIGH_CONTRAST_LIGHTING_HINTS = (
    "暗调",
    "强对比",
    "暗背景",
    "夜景",
    "低曝光",
    "背景很暗",
    "黑暗",
    "浮出来",
    "主体分离",
    "赛博",
    "舞台感",
)
LIGHTING_CONSTRAINT_HINTS = ("过曝", "死黑", "烟雾过亮", "平均受光", "主体与背景黏连", "廉价发光")
RISK_HINTS = (
    "胸",
    "乳",
    "饱满",
    "丰满",
    "丰腴",
    "身材",
    "曲线",
    "性感",
    "臀",
    "腿",
    "吊带",
    "睡裙",
    "暴露",
    "暧昧",
    "诱惑",
    "撩人",
    "擦边",
    "裸",
    "私房",
)
CONSTRAINT_HINTS = ("避免", "不要", "防止", "排除", "约束", "非")
BODY_SAFETY_CONSTRAINT_HINTS = ("幼态", "低俗", "局部", "暴露", "夸张身体", "廉价网红", "过度磨皮")
BODY_SAFETY_FULL_CONSTRAINT = "避免幼态化、低俗化、身体局部特写、过度暴露服装、夸张身体比例、廉价网红感和过度磨皮。"
BODY_SAFETY_COMPACT_CONSTRAINT = "避免幼态化、低俗化、局部身体特写、过度暴露、夸张比例和过度磨皮。"
PREGNANCY_CONSTRAINT_HINTS = ("影楼风", "过度摆拍", "不真实孕肚", "孕肚形态", "广角畸变", "商业广告感")
PREGNANCY_FULL_CONSTRAINT = "负面约束：避免影楼风、过度摆拍、不真实孕肚形态、强烈广角畸变、过度磨皮、商业广告感过重、背景杂乱。"
PREGNANCY_COMPACT_CONSTRAINT = "避免影楼风、过度摆拍、不真实孕肚、强广角畸变、过度磨皮和背景杂乱。"
HIGH_CONTRAST_FULL_CONSTRAINT = "避免人物过曝、背景死黑、廉价发光特效、烟雾过亮、主体与背景黏连和全画面平均受光。"
HIGH_CONTRAST_COMPACT_CONSTRAINT = "避免过曝、背景死黑、廉价发光、烟雾过亮、主体背景黏连和平均受光。"
GENERIC_CONSTRAINT = "避免结构错误、风格冲突、信息过载和背景抢主体。"
TRANSIENT_GPT_OAUTH_ERROR_MARKERS = (
    "http 500",
    "http 502",
    "http 503",
    "http 504",
    "server_error",
    "upstream connect error",
    "disconnect/reset before headers",
    "remote connection failure",
    "connection refused",
    "stream disconnected",
    "chunkedencodingerror",
    "response ended prematurely",
)
PROMPT_CHAT_POOL_FALLBACK_MARKERS = (
    "http 401",
    "http 429",
    "unauthorized",
    "token_invalidated",
    "invalidated",
    "invalid_request_error",
    "refresh_token",
    "usage_limit_reached",
    "usage limit",
    "limit has been reached",
    "rate limit",
    "rate_limited",
    "quota",
)
NO_TEXT_CHINESE_CONSTRAINT = "画面无可读文字。"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _text_has_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _has_han(text: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _normalize_modules(items: list[Any]) -> list[str]:
    valid = set(MODULE_ORDER)
    seen: set[str] = set()
    for item in items:
        module = str(item or "").strip().upper()
        if module in valid:
            seen.add(module)
    return [module for module in MODULE_ORDER if module in seen]


def _has_constraint(text: str) -> bool:
    return _text_has_any(text, CONSTRAINT_HINTS)


def _has_body_safety_constraint(text: str) -> bool:
    return _text_has_any(text, BODY_SAFETY_CONSTRAINT_HINTS)


def _has_pregnancy_constraint(text: str) -> bool:
    return _text_has_any(text, PREGNANCY_CONSTRAINT_HINTS)


def _has_lighting_constraint(text: str) -> bool:
    return _text_has_any(text, LIGHTING_CONSTRAINT_HINTS)


def _paragraph_count(text: str) -> int:
    parts = [part.strip() for part in str(text or "").replace("\r\n", "\n").split("\n")]
    return len([part for part in parts if part])


def _append_sentence_once(text: str, sentence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return sentence
    if sentence in cleaned:
        return cleaned
    if cleaned.endswith(("。", "！", "？", "；")):
        separator = ""
    elif cleaned.endswith((".", "!", "?", ";")):
        separator = " "
    else:
        separator = "。"
    return f"{cleaned}{separator}{sentence}"


def _infer_formula_modules(original_text: str, full_prompt: str, compact_prompt: str) -> tuple[set[str], bool]:
    combined = f"{original_text} {full_prompt} {compact_prompt}"
    has_person = _text_has_any(combined, PERSON_HINTS)
    has_female = _text_has_any(combined, FEMALE_HINTS)
    has_photo = _text_has_any(combined, PHOTO_HINTS)
    has_mobile_photo = _text_has_any(combined, MOBILE_PHOTO_HINTS)
    has_pregnancy = _text_has_any(combined, PREGNANCY_HINTS)
    has_scene = _text_has_any(combined, SCENE_HINTS)
    has_texture = _text_has_any(combined, TEXTURE_HINTS)
    has_format = _text_has_any(combined, FORMAT_HINTS)
    has_product = _text_has_any(combined, PRODUCT_HINTS)
    has_structure = _text_has_any(combined, STRUCTURE_HINTS)
    has_style = _text_has_any(combined, STYLE_HINTS)
    has_layout = _text_has_any(combined, LAYOUT_HINTS)
    has_medium = _text_has_any(combined, MEDIUM_HINTS)
    has_lighting = _text_has_any(combined, LIGHTING_HINTS)
    has_high_contrast_lighting = _text_has_any(combined, HIGH_CONTRAST_LIGHTING_HINTS)
    has_risk = _text_has_any(original_text, RISK_HINTS)

    required = {"M0", "M2", "M3", "M7", "M14"}
    if has_female or has_risk:
        required.update({"M1", "M12"})
    if has_risk:
        required.add("M13")
    if has_photo or has_person or has_mobile_photo or has_medium:
        required.add("M3")
    if has_pregnancy:
        required.update({"M1", "M4", "M8", "M9", "M10", "M11", "M12"})
    if has_scene:
        required.add("M4")
    if has_structure or has_product or has_person:
        required.add("M5")
    if has_style or has_format:
        required.add("M6")
    if has_lighting or has_high_contrast_lighting:
        required.add("M8")
    if has_texture or has_product or has_person:
        required.add("M9")
    if has_person or has_scene or has_format or has_product or has_lighting or has_high_contrast_lighting:
        required.add("M10")
    if has_format or has_product:
        required.add("M11")
    if has_high_contrast_lighting:
        required.update({"M8", "M10", "M12"})
    if has_layout:
        required.add("M7")
    if _has_constraint(full_prompt) or _has_constraint(compact_prompt):
        required.add("M12")
    return required, has_risk


def _apply_formula_guards(data: dict[str, Any], original_text: str) -> dict[str, Any]:
    full_prompt = str(data.get("full_prompt") or data.get("完整提示词") or "").strip()
    compact_prompt = str(data.get("compact_prompt") or data.get("精简提示词") or data.get("精简可投喂版") or "").strip()
    if not full_prompt:
        raise ValueError("模型返回缺少 full_prompt")
    if not compact_prompt:
        compact_prompt = full_prompt

    raw_modules = data.get("modules")
    module_items = raw_modules if isinstance(raw_modules, list) else []
    required_modules, has_risk = _infer_formula_modules(original_text, full_prompt, compact_prompt)
    modules = _normalize_modules([*module_items, *required_modules])
    has_pregnancy = _text_has_any(f"{original_text} {full_prompt} {compact_prompt}", PREGNANCY_HINTS)
    has_high_contrast_lighting = _text_has_any(f"{original_text} {full_prompt} {compact_prompt}", HIGH_CONTRAST_LIGHTING_HINTS)

    if has_pregnancy:
        if not _has_pregnancy_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, PREGNANCY_FULL_CONSTRAINT)
        if not _has_pregnancy_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, PREGNANCY_COMPACT_CONSTRAINT)
    elif has_risk:
        if not _has_body_safety_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, BODY_SAFETY_FULL_CONSTRAINT)
        if not _has_body_safety_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, BODY_SAFETY_COMPACT_CONSTRAINT)
    elif has_high_contrast_lighting:
        if not _has_lighting_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, HIGH_CONTRAST_FULL_CONSTRAINT)
        if not _has_lighting_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, HIGH_CONTRAST_COMPACT_CONSTRAINT)
    elif "M12" in modules:
        if not _has_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, GENERIC_CONSTRAINT)
        if not _has_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, GENERIC_CONSTRAINT)

    warnings = data.get("warnings")
    normalized_warnings = [str(item) for item in warnings] if isinstance(warnings, list) else []
    if has_risk and not normalized_warnings:
        normalized_warnings.append("已将身体局部或性感化表达转译为成熟得体的整体体态、服装剪裁与商业人像表达。")

    return {
        "full_prompt": full_prompt,
        "compact_prompt": compact_prompt,
        "modules": modules,
        "warnings": normalized_warnings,
        "router_summary": str(data.get("router_summary") or "").strip(),
        "original_text": original_text,
    }


def _extract_first_json_block(text: str) -> str:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:index + 1]
    raise ValueError("模型返回的 JSON 不完整")


def _load_skill_prompt(skill_id: str) -> str:
    safe_id = "".join(ch for ch in str(skill_id or "") if ch.isalnum() or ch in {"_", "-"})
    if not safe_id:
        safe_id = DEFAULT_PROMPT_SKILL_ID
    path = PROMPT_SKILL_DIR / f"{safe_id}.md"
    if not path.exists():
        raise ValueError(f"未知提示词 skill：{safe_id}")
    return path.read_text(encoding="utf-8").strip()


def _provider_settings() -> dict[str, Any]:
    settings = load_app_settings().get("prompt_model_providers") or {}
    return settings if isinstance(settings, dict) else {}


def list_prompt_providers() -> list[dict[str, str]]:
    providers = [
        {
            "id": DEFAULT_PROMPT_SKILL_PROVIDER,
            "label": "GPT OAuth",
            "type": "gpt_oauth",
        }
    ]
    for provider_id, provider in _provider_settings().items():
        if not isinstance(provider, dict):
            continue
        clean_id = str(provider_id or "").strip()
        if not clean_id or clean_id == DEFAULT_PROMPT_SKILL_PROVIDER:
            continue
        providers.append(
            {
                "id": clean_id,
                "label": str(provider.get("label") or clean_id),
                "type": str(provider.get("type") or "openai_compatible"),
            }
        )
    return providers


def _codex_cache_models() -> tuple[list[dict[str, Any]], str]:
    cache_path = Path(os.environ.get("CODEX_MODELS_CACHE", "") or DEFAULT_MODEL_CACHE).expanduser()
    if not cache_path.exists():
        return [], f"未找到模型缓存：{cache_path}"
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], f"模型缓存读取失败：{exc}"

    models = []
    for item in _as_list(data.get("models")):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("slug") or item.get("id") or "").strip()
        if not model_id:
            continue
        if item.get("supported_in_api") is False:
            continue
        if str(item.get("visibility") or "list").lower() in {"hidden", "disabled"}:
            continue
        reasoning_levels = []
        for level in _as_list(item.get("supported_reasoning_levels")):
            if isinstance(level, dict) and level.get("effort"):
                reasoning_levels.append(str(level.get("effort")))
        models.append(
            {
                "id": model_id,
                "label": str(item.get("display_name") or model_id),
                "description": str(item.get("description") or ""),
                "default_reasoning_effort": str(item.get("default_reasoning_level") or ""),
                "reasoning_efforts": [effort for effort in reasoning_levels if effort in GPT_REASONING_EFFORTS],
                "available": True,
            }
        )
    return models, ""


def _openai_compatible_models(provider: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    configured_models = provider.get("models")
    if isinstance(configured_models, list) and configured_models:
        return [
            {
                "id": str(item.get("id") if isinstance(item, dict) else item).strip(),
                "label": str((item.get("label") or item.get("id")) if isinstance(item, dict) else item).strip(),
                "available": True,
            }
            for item in configured_models
            if str(item.get("id") if isinstance(item, dict) else item).strip()
        ], ""

    api_base = str(provider.get("api_base") or "").rstrip("/")
    api_key = str(provider.get("api_key") or os.environ.get(str(provider.get("api_key_env") or "")) or "")
    if not api_base:
        return [], "第三方 provider 未配置 api_base"

    request = urllib.request.Request(
        f"{api_base}/models",
        headers={
            "Accept": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        return [], f"模型列表请求失败（HTTP {exc.code}）：{body[:300]}"
    except Exception as exc:
        return [], f"模型列表请求失败：{exc}"

    models = []
    for item in _as_list(payload.get("data") or payload.get("models")):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("name") or "").strip()
        if not model_id:
            continue
        models.append({"id": model_id, "label": str(item.get("display_name") or model_id), "available": True})
    return models, ""


def discover_prompt_models(provider_id: str | None = None) -> dict[str, Any]:
    config = get_prompt_skill_config()
    provider_id = str(provider_id or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    providers = {item["id"]: item for item in list_prompt_providers()}
    warning = ""

    if provider_id == DEFAULT_PROMPT_SKILL_PROVIDER:
        models, warning = _codex_cache_models()
    else:
        provider = _as_dict(_provider_settings().get(provider_id))
        models, warning = _openai_compatible_models(provider)

    default_model = str(config.get("model") or "").strip()
    model_ids = {item.get("id") for item in models}
    if not default_model or default_model not in model_ids:
        default_model = str(models[0]["id"]) if models else ""

    return {
        "ok": True,
        "provider": provider_id,
        "providers": list(providers.values()),
        "models": models,
        "default_model": default_model,
        "warning": warning,
    }


def _choose_model(provider_id: str, requested_model: str | None) -> str:
    models_payload = discover_prompt_models(provider_id)
    models = models_payload.get("models") or []
    model_ids = {str(item.get("id")) for item in models}
    model = str(requested_model or "").strip()
    if model and model in model_ids:
        return model
    default_model = str(models_payload.get("default_model") or "").strip()
    if default_model:
        return default_model
    raise RuntimeError(models_payload.get("warning") or "没有可用的文本推理模型")


@contextmanager
def _temporary_env(overrides: dict[str, Any]):
    previous = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value in (None, ""):
                os.environ.pop(str(key), None)
            else:
                os.environ[str(key)] = str(value)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _managed_codex_prompt_env() -> dict[str, Any]:
    if not get_managed_codex_oauth_status or not get_managed_codex_provider_env:
        return {}
    try:
        status = get_managed_codex_oauth_status()
        if status.get("enabled") and status.get("configured"):
            return get_managed_codex_provider_env()
    except Exception as exc:
        print(f"⚠️ Prompt Skill managed Codex OAuth 不可用，回退本地 Codex：{exc}")
    return {}


def _gpt_oauth_env_overrides() -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve Codex OAuth env for one prompt request, managed auth first."""
    cfg = get_gpt_provider_config()
    managed_env = _managed_codex_prompt_env()
    if managed_env:
        cfg = {**cfg, "_managed_codex_oauth": True}
        return cfg, managed_env

    mappings = {
        "CODEX_API_AUTH_FILE": cfg.get("auth_file"),
        "CODEX_API_AUTH_DIR": cfg.get("auth_dir"),
        "CODEX_API_BASE": cfg.get("api_base"),
        "GPT_IMAGE_MAIN_MODEL": cfg.get("image_main_model"),
        "GPT_REASONING_EFFORT": cfg.get("reasoning_effort"),
        "GPT_TRANSPORT_MODE": cfg.get("transport_mode"),
        "CODEX_API_AUTH_STRICT": None,
    }
    return cfg, mappings


def _apply_gpt_oauth_env() -> dict[str, Any]:
    """Keep prompt polishing aligned with the selected Codex provider config."""
    cfg, mappings = _gpt_oauth_env_overrides()
    force = bool(cfg.get("_managed_codex_oauth"))
    for key, value in mappings.items():
        if value in (None, ""):
            os.environ.pop(key, None)
        elif force or not os.environ.get(key):
            os.environ[key] = str(value)
    return cfg


def _is_transient_gpt_oauth_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and 500 <= status_code <= 504:
        return True
    text = str(error or "").lower()
    return any(marker in text for marker in TRANSIENT_GPT_OAUTH_ERROR_MARKERS)


def _friendly_gpt_oauth_error(error: Exception) -> RuntimeError:
    if _is_transient_gpt_oauth_error(error):
        return RuntimeError(f"润色模型上游连接失败，已重试仍不可用：{error}")
    return RuntimeError(str(error))


def _call_gpt_oauth(prompt: str, system: str, model: str, reasoning_effort: str) -> str:
    if not build_text_request or not post_responses or not extract_text:
        raise RuntimeError("Codex OAuth 客户端不可用")
    cfg, env_overrides = _gpt_oauth_env_overrides()
    transport_mode = str(cfg.get("transport_mode") or os.environ.get("GPT_TRANSPORT_MODE") or DEFAULT_GPT_TRANSPORT_MODE).strip().lower()
    request = build_text_request(
        prompt=prompt,
        model=model,
        system=system,
        reasoning_effort=reasoning_effort,
    )
    modes = [transport_mode or DEFAULT_GPT_TRANSPORT_MODE]
    if modes[0] != "nonstream":
        modes.append("nonstream")
    while len(modes) < max(1, GPT_OAUTH_RETRY_ATTEMPTS):
        modes.append(modes[0])

    last_error: Exception | None = None
    for index, mode in enumerate(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)], start=1):
        try:
            with _temporary_env(env_overrides):
                event = post_responses(request, timeout=DEFAULT_TIMEOUT_SECONDS, transport_mode=mode)
            return str(extract_text(event) or "").strip()
        except Exception as exc:
            last_error = exc
            if not _is_transient_gpt_oauth_error(exc) or index >= len(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)]):
                break
            print(f"⚠️ Prompt Skill GPT OAuth 暂时失败，切换/重试 {index}/{len(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)])}: {exc}")
            time.sleep(GPT_OAUTH_RETRY_DELAY_SECONDS * index)
    if last_error:
        raise _friendly_gpt_oauth_error(last_error) from last_error
    raise RuntimeError("润色模型请求失败")


def _build_multimodal_text_request(
    prompt: str,
    images: list[str],
    system: str,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    for image_url in images:
        if image_url:
            content.append({"type": "input_image", "image_url": image_url})
    return {
        "model": model,
        "instructions": system or "",
        "input": [{"type": "message", "role": "user", "content": content}],
        "stream": True,
        "store": False,
        "reasoning": {"effort": reasoning_effort, "summary": "auto"},
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
    }


def _call_gpt_oauth_image_json(prompt: str, system: str, images: list[str], model: str, reasoning_effort: str) -> str:
    if not post_responses or not extract_text:
        raise RuntimeError("Codex OAuth 客户端不可用")
    cfg, env_overrides = _gpt_oauth_env_overrides()
    transport_mode = str(cfg.get("transport_mode") or os.environ.get("GPT_TRANSPORT_MODE") or DEFAULT_GPT_TRANSPORT_MODE).strip().lower()
    request = _build_multimodal_text_request(prompt, images, system, model, reasoning_effort)
    modes = [transport_mode or DEFAULT_GPT_TRANSPORT_MODE]
    if modes[0] != "nonstream":
        modes.append("nonstream")
    while len(modes) < max(1, GPT_OAUTH_RETRY_ATTEMPTS):
        modes.append(modes[0])

    last_error: Exception | None = None
    for index, mode in enumerate(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)], start=1):
        try:
            with _temporary_env(env_overrides):
                event = post_responses(request, timeout=DEFAULT_TIMEOUT_SECONDS, transport_mode=mode)
            return str(extract_text(event) or "").strip()
        except Exception as exc:
            last_error = exc
            if not _is_transient_gpt_oauth_error(exc) or index >= len(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)]):
                break
            print(f"⚠️ Prompt Image Analysis GPT OAuth 暂时失败，切换/重试 {index}/{len(modes[: max(1, GPT_OAUTH_RETRY_ATTEMPTS)])}: {exc}")
            time.sleep(GPT_OAUTH_RETRY_DELAY_SECONDS * index)
    if last_error:
        raise _friendly_gpt_oauth_error(last_error) from last_error
    raise RuntimeError("图片分析模型请求失败")


def _event_text_delta(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type.endswith(".delta"):
        for key in ("delta", "text", "content"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        delta = event.get("delta")
        if isinstance(delta, dict):
            for key in ("text", "content"):
                value = delta.get(key)
                if isinstance(value, str) and value:
                    return value
    return ""


def _call_gpt_oauth_stream(prompt: str, system: str, model: str, reasoning_effort: str) -> Iterator[str]:
    if not build_text_request or not extract_text or not codex_headers or not get_codex_auth or not iter_sse_events or not codex_api_base:
        raise RuntimeError("Codex OAuth 流式客户端不可用")
    _, env_overrides = _gpt_oauth_env_overrides()
    request = build_text_request(
        prompt=prompt,
        model=model,
        system=system,
        reasoning_effort=reasoning_effort,
    )
    request["stream"] = True
    last_event: dict[str, Any] | None = None
    output_items: dict[int, dict[str, Any]] = {}
    output_items_fallback: list[dict[str, Any]] = []
    emitted_delta = False
    event_index = 0
    try:
        with _temporary_env(env_overrides):
            auth = get_codex_auth()
            response = requests.post(
                f"{codex_api_base()}/responses",
                headers=codex_headers(auth, stream=True),
                json=request,
                stream=True,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            if response.status_code >= 400:
                raise CodexAPIError(f"HTTP {response.status_code}: {response.text[:2000]}", response.status_code)
            for event in iter_sse_events(response):
                event_index += 1
                last_event = event
                event_type = str(event.get("type") or "")
                if event_type == "response.output_item.done" and isinstance(event.get("item"), dict):
                    output_index = event.get("output_index")
                    if isinstance(output_index, int):
                        output_items[output_index] = event["item"]
                    else:
                        output_items_fallback.append(event["item"])
                    continue
                if event_type in {"response.failed", "response.incomplete"}:
                    raise CodexAPIError(f"upstream {event_type}: {event}", 502)
                delta = _event_text_delta(event)
                if delta:
                    emitted_delta = True
                    yield delta
                    continue
                if event_type == "response.completed":
                    response_payload = event.get("response")
                    if isinstance(response_payload, dict) and not response_payload.get("output"):
                        ordered = [output_items[i] for i in sorted(output_items)]
                        ordered.extend(output_items_fallback)
                        if ordered:
                            response_payload["output"] = ordered
                    if not emitted_delta:
                        final_text = str(extract_text(event) or "").strip()
                        if final_text:
                            yield final_text
                    return
    except requests.exceptions.RequestException as exc:
        detail = f"stream disconnected before completion; events={event_index}"
        if last_event:
            detail += f"; last_event={last_event.get('type')}"
        raise RuntimeError(f"{detail}: {exc}") from exc
    if last_event:
        raise RuntimeError(f"stream disconnected before completion; last_event={last_event.get('type')}")
    raise RuntimeError("stream disconnected before completion")


def _call_openai_compatible_stream(provider: dict[str, Any], prompt: str, system: str, model: str) -> Iterator[str]:
    api_base = str(provider.get("api_base") or "").rstrip("/")
    api_key = str(provider.get("api_key") or os.environ.get(str(provider.get("api_key_env") or "")) or "")
    if not api_base:
        raise RuntimeError("第三方 provider 未配置 api_base")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(provider.get("temperature", 0.4)),
        "stream": True,
    }
    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            while True:
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                payload = text[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                data = json.loads(payload)
                choices = data.get("choices") if isinstance(data.get("choices"), list) else []
                for choice in choices:
                    delta = choice.get("delta") if isinstance(choice, dict) else {}
                    content = delta.get("content") if isinstance(delta, dict) else ""
                    if content:
                        yield str(content)
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"第三方模型流式请求失败（HTTP {exc.code}）：{body_text[:500]}") from exc


def _call_prompt_provider_stream(provider_id: str, prompt: str, system: str, model: str, reasoning_effort: str) -> Iterator[str]:
    if provider_id == DEFAULT_PROMPT_SKILL_PROVIDER:
        yield from _call_gpt_oauth_stream(prompt, system, model, reasoning_effort)
        return
    yield from _call_openai_compatible_stream(_as_dict(_provider_settings().get(provider_id)), prompt, system, model)


# Keep the imported symbol referenced so old monkeypatch-based checks fail loudly
# if the shared Codex helper removes it.
_ = post_responses_stream


def _call_openai_compatible(provider: dict[str, Any], prompt: str, system: str, model: str) -> str:
    api_base = str(provider.get("api_base") or "").rstrip("/")
    api_key = str(provider.get("api_key") or os.environ.get(str(provider.get("api_key_env") or "")) or "")
    if not api_base:
        raise RuntimeError("第三方 provider 未配置 api_base")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(provider.get("temperature", 0.4)),
    }
    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"第三方模型请求失败（HTTP {exc.code}）：{body_text[:500]}") from exc
    return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _call_openai_compatible_image_json(provider: dict[str, Any], prompt: str, system: str, images: list[str], model: str) -> str:
    api_base = str(provider.get("api_base") or "").rstrip("/")
    api_key = str(provider.get("api_key") or os.environ.get(str(provider.get("api_key_env") or "")) or "")
    if not api_base:
        raise RuntimeError("第三方 provider 未配置 api_base")
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_url in images:
        if image_url:
            content.append({"type": "image_url", "image_url": {"url": image_url}})
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        "temperature": float(provider.get("temperature", 0.2)),
    }
    request = urllib.request.Request(
        f"{api_base}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        raise RuntimeError(f"第三方图片分析请求失败（HTTP {exc.code}）：{body_text[:500]}") from exc
    return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _call_prompt_provider(provider_id: str, prompt: str, system: str, model: str, reasoning_effort: str) -> str:
    if provider_id == DEFAULT_PROMPT_SKILL_PROVIDER:
        return _call_gpt_oauth(prompt, system, model, reasoning_effort)
    return _call_openai_compatible(_as_dict(_provider_settings().get(provider_id)), prompt, system, model)


def _call_prompt_provider_image_json(provider_id: str, prompt: str, system: str, images: list[str], model: str, reasoning_effort: str) -> str:
    if provider_id == "chatgpt_pool":
        reply, _ = _chatgpt_pool_image_json_reply(prompt, system, images)
        return reply
    if provider_id == DEFAULT_PROMPT_SKILL_PROVIDER:
        return _call_gpt_oauth_image_json(prompt, system, images, model, reasoning_effort)
    return _call_openai_compatible_image_json(_as_dict(_provider_settings().get(provider_id)), prompt, system, images, model)


def _should_fallback_prompt_chat_to_pool(provider_id: str, error: Exception) -> bool:
    return provider_id == DEFAULT_PROMPT_SKILL_PROVIDER and bool(chat_chatgpt_pool)


def _prompt_pool_fallback_reason(error: Exception) -> str:
    text = str(error or "").lower()
    if any(marker in text for marker in ("usage_limit_reached", "usage limit", "limit has been reached", "http 429", "rate limit", "rate_limited", "quota")):
        return "Codex 用量受限，已切换 ChatGPT 账号池"
    if any(marker in text for marker in ("http 401", "unauthorized", "token_invalidated", "invalidated", "invalid_request_error", "refresh_token")):
        return "Codex OAuth 失效，已切换 ChatGPT 账号池"
    return "Codex 暂不可用，已切换 ChatGPT 账号池"


def _chatgpt_pool_chat_reply(prompt: str, system: str, timeout_seconds: int = 180) -> tuple[str, str]:
    if not chat_chatgpt_pool:
        raise RuntimeError("ChatGPT 账号池 chat 不可用")
    result = chat_chatgpt_pool(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model="auto",
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(result.get("error") if isinstance(result, dict) else "账号池 chat 失败")
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("账号池 chat 没有返回内容")
    return content, str(payload.get("model") or "auto")


def _fallback_prompt_chat_to_pool(prompt: str, system: str, error: Exception) -> tuple[str, str, str]:
    reply, model = _chatgpt_pool_chat_reply(prompt, system)
    warning = f"{_prompt_pool_fallback_reason(error)}：{error}"
    print(f"⚠️ Prompt Assistant Chat fallback to account pool: {error}")
    return reply, model, warning


def _call_prompt_provider_with_pool_fallback(
    provider_id: str,
    prompt: str,
    system: str,
    model: str,
    reasoning_effort: str,
    error_label: str,
) -> tuple[str, str, str, str, str]:
    if provider_id == "chatgpt_pool":
        reply, fallback_model = _chatgpt_pool_chat_reply(prompt, system)
        return reply, "chatgpt_pool", fallback_model, "", ""
    try:
        raw_text = _call_prompt_provider(provider_id, prompt, system, model, reasoning_effort)
        return raw_text, provider_id, model, reasoning_effort, ""
    except Exception as exc:
        if not _should_fallback_prompt_chat_to_pool(provider_id, exc):
            raise
        reply, fallback_model = _chatgpt_pool_chat_reply(prompt, system)
        warning = f"{_prompt_pool_fallback_reason(exc)}{error_label}：{exc}"
        print(f"⚠️ Prompt Skill {error_label} fallback to account pool: {exc}")
        return reply, "chatgpt_pool", fallback_model, "", warning


def _select_prompt_provider_model_with_pool_fallback(
    provider_id: str,
    requested_model: str,
    error_label: str,
) -> tuple[str, str, str]:
    if provider_id == "chatgpt_pool":
        return provider_id, requested_model or "auto", ""
    try:
        return provider_id, _choose_model(provider_id, requested_model), ""
    except Exception as exc:
        if not _should_fallback_prompt_chat_to_pool(provider_id, exc):
            raise
        warning = f"{_prompt_pool_fallback_reason(exc)}{error_label}：{exc}"
        print(f"⚠️ Prompt Skill {error_label} model selection fallback to account pool: {exc}")
        return "chatgpt_pool", "auto", warning


def _friendly_pool_image_analysis_error(error: Any) -> str:
    text = str(error or "").strip()
    lower = text.lower()
    if any(marker in lower for marker in ("write operation timed out", "read timed out", "timed out", "timeout")):
        return "账号池图片分析上传/请求超时：参考图可能过大或当前网络较慢，已停止等待；请重试或换一张较小的参考图。"
    return text or "账号池图片分析失败"


def _chatgpt_pool_image_json_reply(
    prompt: str,
    system: str,
    images: list[str],
    timeout_seconds: int | None = None,
) -> tuple[str, str]:
    if not chat_chatgpt_pool:
        raise RuntimeError("ChatGPT 账号池 multimodal chat 不可用")
    try:
        selected_timeout = int(timeout_seconds or PROMPT_IMAGE_ANALYSIS_POOL_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        selected_timeout = PROMPT_IMAGE_ANALYSIS_POOL_TIMEOUT_SECONDS
    selected_timeout = max(45, min(180, selected_timeout))
    result = chat_chatgpt_pool(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model="auto",
        timeout_seconds=selected_timeout,
        base64_images=images,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError(_friendly_pool_image_analysis_error(result.get("error") if isinstance(result, dict) else "账号池图片分析失败"))
    payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    first = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = str(message.get("content") or "").strip()
    if not content:
        raise RuntimeError("账号池图片分析没有返回内容")
    return content, str(payload.get("model") or "auto")


def _fallback_prompt_image_analysis_to_pool(prompt: str, system: str, images: list[str], error: Exception) -> tuple[str, str, str]:
    reply, model = _chatgpt_pool_image_json_reply(prompt, system, images)
    warning = f"{_prompt_pool_fallback_reason(error)}图片分析：{error}"
    print(f"⚠️ Prompt Image Analysis fallback to account pool: {error}")
    return reply, model, warning


ASSISTANT_CHAT_SYSTEM = """你是桌面画布中文本节点的提示词创作助手。
你的任务是帮助用户讨论、判断和收敛图像提示词方向，而不是默认生成完整候选提示词。
回答必须专业、精准、可执行；长度由问题复杂度决定，不强制简短，但避免客套、模板化废话和无关扩写。
除非用户明确要求整理为正式提示词，否则不要输出完整成片提示词，不要输出多版本候选列表。
你可以诊断当前文本的问题、提出改写策略、比较风格方向、指出容易跑偏的词，并在方向不清楚时提出关键追问。"""

PROMPT_BLOCK_EXTRACTION_SYSTEM = """你是图像生成提示词素材块拆分器。
你的唯一任务是把用户给出的完整提示词拆成可以单独复用和快速插入的短提示词素材块。

必须遵守：
1. 不要输出完整提示词，不要把原文整体作为一个素材块。
2. 按语义拆分；人物优先拆成身份、外貌、动作姿态、表情视线、服装造型、妆发、配饰。
3. 其他内容按主体、场景、构图、镜头、光线、色彩、视觉风格、材质细节、质量要求、负面约束等拆分。
4. 每个素材块必须能脱离原文独立插入，保留关键限定词，但不得凭空增加原文没有的信息。
5. 合并重复内容；忽略空泛套话。遵循本次拆分规则给出的粒度和数量上限；未指定时通常输出 3-18 个素材块。
6. name 使用 4-16 个字概括内容；content 使用原提示词语言；compact_content 是更短的同义版本。
7. module_type 只使用 snake_case 标识；优先使用本次任务提供的拆分规则模块，其次使用 identity、appearance、pose、expression、clothing、makeup_hair、accessories、subject、scene、composition、camera、lighting、color、style、material、quality、constraints；确实无法归类时使用 custom。
8. 输出严格 JSON 对象，不要 Markdown、解释或代码围栏。

JSON 形状：
{"primary_type":"portrait/landscape/product/...","blocks":[{"name":"","module_type":"","content":"","compact_content":"","english_content":"","tags":[]}]}"""

PROMPT_BLOCK_MODULE_ALIASES = {
    "character_identity": "identity", "role": "identity", "人物身份": "identity", "角色身份": "identity", "身份": "identity",
    "looks": "appearance", "visual_traits": "appearance", "外貌": "appearance",
    "action": "pose", "动作": "pose", "姿态": "pose", "动作姿态": "pose",
    "facial_expression": "expression", "表情": "expression", "表情视线": "expression",
    "outfit": "clothing", "costume": "clothing", "服装": "clothing", "服装造型": "clothing",
    "hair": "makeup_hair", "makeup": "makeup_hair", "妆发": "makeup_hair",
    "props": "accessories", "配饰": "accessories", "主体": "subject", "场景": "scene",
    "layout": "composition", "构图": "composition", "镜头": "camera", "光线": "lighting",
    "palette": "color", "色彩": "color", "风格": "style", "视觉风格": "style",
    "texture": "material", "材质": "material", "质量": "quality", "负面": "constraints",
    "negative": "constraints", "negative_prompt": "constraints", "约束": "constraints",
}

PROMPT_BLOCK_MODULE_LABELS = {
    "identity": "身份", "appearance": "外貌", "pose": "动作姿态", "expression": "表情视线",
    "clothing": "服装造型", "makeup_hair": "妆发", "accessories": "配饰", "subject": "主体",
    "scene": "场景环境", "composition": "构图", "camera": "视角与镜头", "lighting": "光线",
    "color": "色彩", "style": "视觉风格", "material": "材质细节", "quality": "质量要求",
    "constraints": "负面约束", "custom": "自定义素材",
}

PROMPT_BLOCK_TEMPLATES = {
    str(template["primary_type"]): template
    for template in built_in_templates()
}
PROMPT_BLOCK_PRIMARY_TYPES = set(PROMPT_BLOCK_TEMPLATES)
PROMPT_BLOCK_MODULE_TYPE_OWNERS: dict[str, set[str]] = {}
for _prompt_block_template in PROMPT_BLOCK_TEMPLATES.values():
    for _prompt_block_module in _prompt_block_template.get("modules") or []:
        _module_key = str(_prompt_block_module.get("key") or "").strip()
        _module_label = str(_prompt_block_module.get("label") or "").strip()
        if not _module_key:
            continue
        PROMPT_BLOCK_MODULE_LABELS.setdefault(_module_key, _module_label or _module_key)
        if _module_label:
            _alias_key = _module_label.lower().replace("-", "_").replace(" ", "_")
            PROMPT_BLOCK_MODULE_ALIASES.setdefault(_alias_key, _module_key)
        if str(_prompt_block_module.get("kind") or "") == "specific":
            PROMPT_BLOCK_MODULE_TYPE_OWNERS.setdefault(_module_key, set()).add(str(_prompt_block_template["primary_type"]))

SAFE_REWRITE_SYSTEM = """You are a prompt rewriting assistant for image generation.

Rewrite the user's image prompt into a safer, policy-compliant, image-model-friendly prompt.

Rules:
1. Preserve the core visual intent, subject, style, composition, color palette, and scene.
2. If people are involved, make them clearly adult unless the original request is non-sexual and explicitly about children.
3. Remove or soften sexualized wording such as sexy, seductive, erotic, provocative, revealing, nude, fetish, or body-part-focused language.
4. Convert body descriptions into clothing, silhouette, fabric, fashion, costume, or styling descriptions.
5. Convert transparent / see-through wording into layered fabric, translucent outer layer, or sheer sleeves over opaque base.
6. Emphasize editorial, cinematic, fashion, cosplay, historical, fantasy, or character-design context.
7. Avoid readable random text unless specifically required; if signage is background detail, make it blurred and not legible.
8. Add concise safety constraints: non-explicit, no nudity, no minors, no watermark.
9. Keep each prompt visually rich and directly usable for image generation.
10. Return exactly two rewritten prompts: one Chinese prompt and one English prompt. Each prompt must use the 11-section prompt skeleton.
11. The Chinese prompt must use Chinese section headings from [1. 画布] through [11. 约束].
12. The English prompt must use English section headings from [1. Canvas] through [11. Constraints].
13. Do not return extra versions, markdown fences, explanations, or change notes.
14. Output strict JSON only with this exact shape:
{"zh_prompt":"改写后的中文提示词","en_prompt":"rewritten English prompt"}

High-risk wording replacement table:
- young girl / teen-looking / youthful-looking / schoolgirl -> clearly adult woman / adult character / adult student-inspired fashion / academy-style outfit.
- young women in sensual, revealing, or body-focused contexts -> clearly adult women in an editorial, fashion, cosplay, cinematic, or character-design context.
- sexy / seductive / sultry / provocative -> elegant / glamorous / fashionable / poised / softly posed / confident / cinematic.
- erotic / fetish / nude / naked / barely covered -> non-explicit, clothed, tasteful styling, elegant layered costume.
- breasts / big breasts / body-part focus -> bustline / bodice silhouette / sculpted garment shape / upper-body costume silhouette.
- cleavage / revealing cleavage -> deep-V neckline / low-cut evening gown / structured bodice / elegant neckline.
- see-through / transparent dress / translucent over body -> layered translucent fabric, sheer outer layer over an opaque base, sheer sleeves over opaque fabric.
- spread legs / arching back seductively / bending over -> seated fashion pose / elegant S-curve posture / leaning slightly toward camera / poised editorial pose.
- low angle focused on legs, hips, chest, feet, or underwear -> low cinematic camera angle with controlled perspective, full-body composition, no body-part emphasis.
- glossy skin / oily body / sweaty body -> polished skin under soft lighting / luminous skin highlights / subtle skin sheen from stage lighting.
- readable random signage or text -> blurred background signage, not legible, no watermark.
- 女孩 / 少女 / 幼态 / 学生妹 in sensual contexts -> 明确成年的女性角色 / 成熟女性 / 学院风成人造型.
- 性感 / 诱惑 / 挑逗 / 色情 / 擦边 -> 优雅 / 自信 / 时尚摆拍 / 电影感 / 克制的角色气质.
- 胸部 / 乳房 / 爆乳 / 事业线 / 身体局部特写 -> 胸衣轮廓 / 上身剪裁 / 深 V 礼服 / 结构化衣身 / 服装轮廓.
- 透视 / 透明 / 若隐若现 / 几乎遮不住 -> 叠层薄纱 / 不透明内层 / 透明外搭 / 轻薄袖纱覆盖在不透明面料上.
- 低机位强调腿部、胸部、臀部或脚部 -> 轻微低机位电影镜头、控制透视、完整构图、不形成身体局部凝视.
- 随机文字 / 招牌文字 / 背景红字 -> 模糊背景标识，不清晰可读，无水印。
""".strip()

STYLE_EXTRACT_SYSTEM = """你是图像提示词风格预设整理器。
你的任务是从文本节点、聊天讨论和候选提示词中提取可复用的风格预设。
只保存风格语言，不保存具体画面主体、工作流节点、模型参数或任务状态。
只返回合法 JSON 对象，不要 markdown，不要解释。"""

SAFE_REWRITE_CONSTRAINT = "Safety constraints: non-explicit, no nudity, no minors, no watermark."
SAFE_REWRITE_STRUCTURED_SECTIONS = (
    "Canvas",
    "Image Type",
    "Subject",
    "Role / Worldbuilding",
    "Pose / Action",
    "Clothing / Styling",
    "Composition / Camera",
    "Scene / Background",
    "Lighting / Color",
    "Material / Rendering",
    "Constraints",
)

ADAPTER_TASK_TYPES = [
    {
        "id": "cosplay_event",
        "label": "Cosplay / 漫展 / 角色定妆",
        "keywords": ("cosplay", "漫展", "展会", "convention", "expo", "角色定妆", "cosplayer", "头饰", "礼服"),
        "template_hint": "cosplay event portrait, costume craftsmanship, character styling, editorial convention photo",
    },
    {
        "id": "portrait_photo",
        "label": "写真 / 摄影人像",
        "keywords": ("人像", "写真", "portrait", "selfie", "photo", "摄影", "模特", "肖像", "拍照"),
        "template_hint": "editorial portrait, fashion photography, cinematic lighting, tasteful styling, natural skin texture",
    },
    {
        "id": "historical_fantasy",
        "label": "古风 / 仙侠 / 奇幻",
        "keywords": ("古风", "仙侠", "fantasy", "historical", "奇幻", "汉服", "仙气", "古代", "王朝", "江湖"),
        "template_hint": "historical-inspired costume, layered silk robe, embroidered outer gown, opaque inner garment",
    },
    {
        "id": "cyberpunk_game",
        "label": "赛博朋克 / 3A 游戏角色",
        "keywords": ("赛博", "cyberpunk", "3A", "游戏角色", "game character", "neon", "霓虹", "tactical", "装甲"),
        "template_hint": "sci-fi armor paneling, sleek reflective tactical suit, heroic silhouette, game character poster",
    },
    {
        "id": "business_fashion",
        "label": "现代职场 / 通勤风",
        "keywords": ("OL", "office", "办公室", "职场", "通勤", "西装", "business", "workplace", "高跟"),
        "template_hint": "professional fashion, tailored blazer, commuting outfit, business editorial portrait",
    },
    {
        "id": "product_ad",
        "label": "产品 / 广告 / 电商图",
        "keywords": ("产品", "商品", "广告", "电商", "包装", "product", "commercial", "品牌", "详情页"),
        "template_hint": "clean studio lighting, product hero shot, premium material, commercial advertising",
    },
    {
        "id": "architecture_scene",
        "label": "建筑 / 室内 / 场景",
        "keywords": ("建筑", "室内", "interior", "architecture", "空间", "房间", "街景", "场景", "可视化"),
        "template_hint": "architectural visualization, natural lighting, material realism, spatial depth, clean composition",
    },
    {
        "id": "action_dark",
        "label": "战斗 / 暴力 / 暗黑动作",
        "keywords": ("战斗", "battle", "combat", "blood", "gore", "暗黑", "动作", "武器", "伤口"),
        "template_hint": "stylized action, non-graphic combat, battle-worn armor, sparks, smoke, debris",
    },
    {
        "id": "children_family",
        "label": "儿童 / 家庭 / 校园",
        "keywords": ("儿童", "孩子", "小孩", "child", "children", "family", "家庭", "校园", "school"),
        "template_hint": "wholesome, family-friendly, age-appropriate clothing, warm documentary style",
    },
    {
        "id": "reference_edit",
        "label": "参考图 / 图像编辑",
        "keywords": ("参考图", "改图", "edit", "reference", "保持", "换背景", "修图", "基于图片"),
        "template_hint": "safe image edit, preserve non-explicit nature, adjust background, lighting, color, material, or style",
    },
]

ADAPTER_REPLACEMENTS = [
    ("real_person", ("celebrity nude", "real person nude", "private celebrity"), "original fictional adult character in a non-explicit editorial portrait", "Convert real-person sexualized framing into an original fictional safe portrait."),
    ("real_person", ("deepfake nude", "deepfake"), "original fictional adult character portrait", "Remove deepfake or real-person sexualization framing."),
    ("explicit", ("explicit sexual", "sexual act", "porn"), "non-explicit editorial character portrait", "Convert explicit sexual framing into a safe editorial portrait."),
    ("explicit", ("genitals",), "fully clothed non-explicit styling", "Remove explicit anatomy wording."),
    ("explicit", ("明确色情", "性交", "性行为", "性器官", "非同意亲密", "偷拍"), "非露骨的原创成年角色定妆照", "将明确色情、非同意或偷拍表述转为安全原创角色语境。"),
    ("real_person", ("真实人物色情", "名人裸照", "换脸色情"), "原创成年角色的非露骨编辑人像", "移除真实人物色情化或换脸色情表述。"),
    ("age", ("young East Asian women",), "clearly adult East Asian women", "Clarify adult age when the prompt contains mature styling or close portrait framing."),
    ("age", ("young women",), "clearly adult women", "Clarify adult age in a mature or fashion-oriented prompt."),
    ("age", ("young girl", "girl"), "clearly adult woman", "Replace youthful wording with clearly adult framing."),
    ("age", ("teen-looking", "teenage", "youthful"), "mature adult appearance", "Remove teen/youthful framing from image-generation prompt."),
    ("age", ("schoolgirl",), "academy-inspired adult fashion", "Convert school-coded wording into adult styling language."),
    ("age", ("cute little", "childlike", "loli"), "elegant stylized adult", "Avoid childlike framing in image prompts."),
    ("age", ("女孩", "少女", "幼态", "学生妹"), "明确成年的女性角色", "移除幼态或学生妹表述，改为明确成年角色。"),
    ("sexualized", ("sexy",), "elegant high-fashion", "Reduce sexualized wording while preserving visual appeal."),
    ("sexualized", ("seductive",), "softly posed and confident", "Convert seductive wording into editorial posing language."),
    ("sexualized", ("sultry",), "cinematic and moody", "Convert sultry mood into cinematic language."),
    ("sexualized", ("provocative",), "bold editorial fashion", "Convert provocative wording into editorial styling."),
    ("sexualized", ("erotic", "naughty", "horny"), "refined non-explicit", "Remove explicit sexual framing."),
    ("sexualized", ("tempting",), "alluring fashion presence / elegant charisma", "Convert tempting wording into fashion charisma."),
    ("sexualized", ("sensual",), "graceful and refined", "Soften sensual wording into refined mood language."),
    ("sexualized", ("flirtatious",), "gentle confident expression", "Convert flirtatious expression into confident portrait language."),
    ("sexualized", ("性感", "诱惑", "挑逗", "擦边", "色情"), "优雅、自信、时尚摆拍", "将性化表述转为时尚与角色气质语言。"),
    ("body", ("big breasts", "huge chest"), "dramatic structured bodice", "Convert body-size wording into garment construction."),
    ("body", ("breasts",), "bodice silhouette", "Convert body-part wording into clothing silhouette."),
    ("body", ("revealing cleavage",), "refined deep-V gown", "Convert cleavage wording into formal clothing design."),
    ("body", ("cleavage",), "deep neckline", "Convert body focus into neckline/costume wording."),
    ("body", ("hips",), "tailored waistline", "Convert body focus into garment tailoring."),
    ("body", ("butt",), "back silhouette and garment drape", "Avoid explicit body-part focus."),
    ("body", ("thighs",), "leg line within full-body styling", "Keep leg details as styling, not body focus."),
    ("body", ("legs focus",), "full outfit composition", "Shift focus from legs to full outfit."),
    ("body", ("feet focus",), "footwear visible as part of full-body styling", "Shift focus from feet to full-body styling."),
    ("body", ("top-heavy",), "curvy fashion silhouette", "Convert body-proportion wording into fashion silhouette."),
    ("body", ("bust-dominant",), "structured bodice-forward costume design", "Convert bust-focused wording into costume design."),
    ("body", ("胸部", "乳房", "爆乳", "事业线", "身体局部特写"), "胸衣轮廓、上身剪裁、结构化衣身", "将身体局部描述转为服装剪裁语言。"),
    ("exposure", ("naked", "nude"), "clothed tasteful styling", "Remove nudity framing and keep the prompt non-explicit."),
    ("exposure", ("see-through",), "layered translucent fabric over an opaque base", "Convert see-through wording into layered fabric construction."),
    ("exposure", ("transparent dress",), "translucent outer layer over an opaque inner garment", "Convert transparent clothing into safe layered styling."),
    ("exposure", ("transparent",), "translucent outer layer", "Use material language instead of body visibility."),
    ("exposure", ("bare skin",), "open-shoulder design / exposed neckline area", "Convert bare-skin wording into clothing design."),
    ("exposure", ("barely covered",), "elegant layered costume", "Replace revealing coverage wording with costume layers."),
    ("exposure", ("lingerie",), "corset-inspired bodice / eveningwear", "Convert underwear framing into fashion construction."),
    ("exposure", ("underwear",), "fitted inner garment", "Use garment layer language."),
    ("exposure", ("wet clothes clinging",), "rain-textured fabric", "Avoid body-clinging framing."),
    ("exposure", ("revealing outfit",), "open-cut formal gown / stylized costume design", "Convert revealing wording into formal costume design."),
    ("exposure", ("透视", "透明", "若隐若现", "几乎遮不住"), "叠层薄纱、不透明内层、透明外搭", "将透明暴露改为服装材质层次。"),
    ("pose", ("seductive pose",), "elegant editorial pose", "Convert seductive pose into editorial pose."),
    ("pose", ("provocative pose",), "confident fashion pose", "Convert provocative pose into fashion pose."),
    ("pose", ("arching back",), "graceful upright posture", "Avoid sexualized body posture."),
    ("pose", ("bending over",), "leaning slightly forward", "Soften pose while preserving perspective."),
    ("pose", ("spreading legs", "spread legs"), "seated balanced pose", "Avoid explicit pose framing."),
    ("pose", ("legs apart",), "stable stance", "Use neutral stance language."),
    ("pose", ("foot toward camera", "one foot reaching camera"), "shoes angled slightly toward viewer", "Convert foot focus into balanced footwear perspective."),
    ("pose", ("body pressed",), "close group composition", "Convert body-contact wording into group composition."),
    ("pose", ("intimate pose",), "warm natural group pose", "Avoid intimate framing."),
    ("camera", ("camera below knees",), "slight low-angle cinematic view", "Convert risky low angle into controlled cinematic view."),
    ("camera", ("worm-eye focusing legs",), "controlled low-angle full-body composition", "Avoid leg-focused low angle."),
    ("camera", ("POV body shot",), "editorial portrait composition", "Avoid body-focused POV framing."),
    ("camera", ("chest close-up",), "upper-body fashion portrait", "Convert chest focus into portrait/fashion framing."),
    ("camera", ("foot close-up",), "full-body framing with visible footwear", "Avoid foot-focused composition."),
    ("camera", ("extreme low angle under body",), "low-angle heroic framing", "Avoid under-body camera framing."),
    ("camera", ("voyeuristic",), "documentary / candid / natural", "Remove voyeuristic framing."),
    ("camera", ("猫眼视角", "镜头低于膝部", "脚伸向镜头", "低机位强调腿部", "低机位强调胸部", "低机位强调臀部", "低机位强调脚部"), "轻微低机位电影镜头、控制透视、完整构图、不形成身体局部凝视", "将高风险镜头转为受控电影构图。"),
    ("skin", ("oily body",), "natural skin highlights", "Convert oily body wording into neutral lighting."),
    ("skin", ("glossy body",), "polished skin under soft lighting", "Convert body gloss into portrait lighting."),
    ("skin", ("glossy skin",), "polished skin under soft lighting", "Convert skin gloss into lighting language."),
    ("skin", ("sweaty",), "subtle stage-light sheen", "Avoid sweat/body emphasis."),
    ("skin", ("wet skin",), "rain-lit highlights", "Convert skin wetness into lighting."),
    ("skin", ("shiny breasts",), "fabric highlights", "Move highlights from body to fabric."),
    ("skin", ("smooth erotic skin",), "refined natural skin texture", "Convert erotic skin wording into neutral material detail."),
    ("skin", ("微弱健康油光", "油光", "湿润皮肤"), "自然健康的皮肤光泽", "将皮肤质感转为自然光泽语言。"),
    ("ip", ("exact copy of",), "original design inspired by", "Avoid exact IP copying."),
    ("ip", ("replicate this official poster exactly",), "create an original poster inspired by", "Avoid exact poster replication."),
    ("ip", ("identical to",), "similar cinematic archetype / original character", "Avoid identity copying."),
    ("text", ("readable random text",), "small blurred signage", "Avoid random readable text."),
    ("text", ("exact brand logo",), "generic fictional signage", "Avoid unauthorized real brand logo."),
    ("text", ("real company logo",), "brand-like but fictional mark", "Avoid real company logo misuse."),
    ("text", ("large Chinese text",), "subtle graphic title area", "Reduce random text risk."),
    ("text", ("clear text on poster",), "clean minimal text, legible only if necessary", "Keep text intentional and minimal."),
    ("text", ("随机文字", "招牌文字", "背景红字"), "模糊背景标识，不清晰可读", "降低背景文字乱码和品牌误用风险。"),
]

ADAPTER_MATURE_CONTEXT_TERMS = (
    "sexy", "seductive", "sultry", "provocative", "cleavage", "breasts", "transparent", "see-through",
    "stockings", "high heels", "swimwear", "tight", "low angle", "bedroom", "bathroom", "lingerie",
    "性感", "诱惑", "挑逗", "低胸", "透明", "透视", "丝袜", "高跟", "泳装", "低机位", "卧室", "浴室",
)

ADAPTER_PERSON_TERMS = (
    "woman", "women", "girl", "person", "people", "portrait", "model", "cosplayer", "character",
    "女性", "女人", "女孩", "人物", "角色", "人像", "模特", "肖像",
)

ADAPTER_MINOR_TERMS = (
    "minor", "minors", "child", "children", "young girl", "teen", "teenage", "schoolgirl", "loli", "childlike",
    "未成年", "儿童", "孩子", "小孩", "少女", "幼态", "学生妹",
)

ADAPTER_SEXUAL_TERMS = (
    "sexy", "seductive", "sultry", "provocative", "erotic", "nude", "naked", "fetish", "cleavage",
    "breasts", "lingerie", "see-through", "transparent", "性感", "诱惑", "挑逗", "色情", "裸露", "胸部", "乳房",
)

ADAPTER_EXPLICIT_TERMS = (
    "explicit sexual", "sexual act", "porn", "genitals", "non-consensual", "deepfake nude",
    "明确色情", "性交", "性行为", "性器官", "非同意亲密", "偷拍",
)

ADAPTER_GRAPHIC_VIOLENCE_TERMS = (
    "gore", "dismemberment", "graphic wound", "torture", "肢解", "血腥特写", "伤口特写", "酷刑",
)

ADAPTER_REAL_PERSON_RISK_TERMS = (
    "celebrity nude", "real person nude", "deepfake", "private celebrity", "真实人物色情", "名人裸照", "换脸色情",
)

ADAPTER_HARD_BLOCK_MINOR_TERMS = (
    "minor", "minors", "child", "children", "young girl", "girl", "teen", "teenage", "schoolgirl", "loli", "childlike",
    "未成年", "儿童", "孩子", "小孩", "少女", "女孩", "幼态", "学生妹",
)

ADAPTER_SCORE_RULES = [
    ("age_young", 2, ("young", "girl", "年轻", "女孩")),
    ("minor_coded", 5, ("teen", "schoolgirl", "teenage", "loli", "少女", "学生妹", "幼态")),
    ("sexualized_language", 3, ("sexy", "seductive", "sultry", "provocative", "性感", "诱惑", "挑逗", "擦边")),
    ("body_focus", 3, ("cleavage", "breasts", "huge chest", "body close-up", "事业线", "胸部", "乳房", "身体局部")),
    ("transparent_exposure", 3, ("transparent", "see-through", "barely covered", "透视", "透明", "若隐若现")),
    ("fetish_framing", 1, ("stockings", "high heels", "丝袜", "高跟", "足部")),
    ("low_angle", 2, ("low angle", "below knees", "worm-eye", "cat-eye", "低机位", "猫眼视角", "低于膝部")),
    ("foot_foreground", 3, ("foot toward camera", "one foot reaching", "脚伸向镜头", "鞋尖朝向镜头")),
    ("private_scene", 2, ("bedroom", "bathroom", "bed", "hotel room", "卧室", "浴室", "床", "酒店房间")),
    ("nudity", 6, ("nude", "naked", "裸露", "裸体", "没穿衣服")),
]

ADAPTER_INTENT_TERMS = {
    "subject": (
        "woman", "women", "man", "person", "people", "portrait", "model", "cosplayer", "character",
        "product", "package", "architecture", "interior", "animal", "landscape",
        "女性", "女人", "男人", "人物", "角色", "人像", "模特", "产品", "包装", "建筑", "室内", "动物", "风景",
    ),
    "identity": (
        "clearly adult", "mature adult", "editorial", "fashion", "cosplay", "warrior", "mage", "business",
        "historical", "fantasy", "cyberpunk", "adult", "professional", "student-inspired",
        "明确成年", "成年人", "时尚", "角色定妆", "战士", "法师", "职场", "古风", "奇幻", "赛博",
    ),
    "action": (
        "standing", "sitting", "walking", "running", "leaning", "posing", "holding", "looking at camera",
        "站立", "坐姿", "走路", "奔跑", "轻微前倾", "摆拍", "手持", "看向镜头",
    ),
    "clothing": (
        "gown", "dress", "robe", "suit", "blazer", "armor", "costume", "bodice", "neckline", "fabric",
        "translucent outer layer", "opaque base", "layered", "silk", "chiffon", "鞋", "礼服", "长裙",
        "汉服", "西装", "盔甲", "服装", "胸衣轮廓", "剪裁", "叠层薄纱", "不透明内层", "面料",
    ),
    "scene": (
        "studio", "street", "bedroom", "room", "city", "forest", "convention", "expo", "stage",
        "office", "interior", "outdoor", "rain", "night", "室内", "街道", "城市", "森林", "漫展", "展会",
        "舞台", "办公室", "户外", "雨夜", "夜景",
    ),
    "camera": (
        "close-up", "full-body", "upper-body", "low angle", "low-angle", "slight low-angle", "wide angle", "telephoto",
        "depth of field", "portrait composition", "balanced composition", "controlled perspective",
        "特写", "全身", "半身", "低机位", "轻微低机位", "广角", "长焦", "景深", "完整构图", "受控电影机位",
    ),
    "style": (
        "photo", "portrait", "photography", "cinematic", "editorial", "fashion", "3D", "CGI", "illustration",
        "poster", "anime", "commercial", "minimal", "电影", "摄影", "写真", "时尚", "编辑", "插画",
        "海报", "动漫", "商业", "极简",
    ),
}


def _adapter_contains_any(text: str, terms: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(str(term or "").lower() in haystack for term in terms)


def _adapter_risk_text(text: str) -> str:
    """Remove explicit negative safety constraints before positive risk scans."""
    cleaned = str(text or "")
    replacements = (
        (r"无未成年人|无未成年|没有未成年人|没有未成年|不含未成年人|不含未成年|无儿童|没有儿童", " "),
        (r"\bno\s+minors?\b|\bwithout\s+minors?\b|\bno\s+children\b", " "),
        (r"无裸露|没有裸露|不裸露|无裸体|没有裸体|非裸露|非露骨|非色情", " "),
        (r"\bno\s+nudity\b|\bno\s+nude\b|\bno\s+naked\b|\bnon[-\s]?explicit\b|\bnot\s+explicit\b", " "),
        (r"不透明", "opaque"),
        (r"控制透视|艺术透视|镜头透视|透视关系|透视畸变", "controlled perspective"),
        (r"不形成身体局部强调|不形成身体局部凝视|非身体局部强调|非身体局部凝视", " "),
    )
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)
    return cleaned


def _adapter_phrase_pattern(phrase: str) -> re.Pattern:
    escaped = re.escape(str(phrase or ""))
    if re.search(r"[A-Za-z0-9]", phrase or ""):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)
    return re.compile(escaped, re.I)


def _adapter_match_is_safe_context(category: str, phrase: str, text: str, start: int, end: int) -> bool:
    if category != "exposure":
        return False
    clean_phrase = str(phrase or "").lower()
    window = str(text or "")[max(0, start - 12): min(len(str(text or "")), end + 12)]
    lowered_window = window.lower()
    if clean_phrase in {"transparent", "透视", "透明"}:
        if any(marker in lowered_window for marker in ("not transparent", "opaque", "non-transparent", "不透明")):
            return True
    if phrase in {"透视", "透明"}:
        if any(marker in window for marker in ("控制透视", "艺术透视", "镜头透视", "透视关系", "透视畸变")):
            return True
        risky_markers = ("透视装", "透视衣", "透视服", "透明衣", "透明服", "透明裙", "透明材质", "透明外衣", "若隐若现", "几乎遮不住", "暴露", "裸露", "肌肤", "身体")
        return not any(marker in window for marker in risky_markers)
    return False


def _classify_adapter_task_type(text: str) -> dict[str, Any]:
    scored = []
    for item in ADAPTER_TASK_TYPES:
        score = sum(1 for keyword in item["keywords"] if keyword.lower() in str(text or "").lower())
        if score:
            scored.append((score, item))
    if not scored:
        return {
            "id": "general_image",
            "label": "通用图像",
            "template_hint": "clear image prompt, balanced composition, visual structure, lighting, material detail",
        }
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = scored[0][1]
    return {
        "id": selected["id"],
        "label": selected["label"],
        "template_hint": selected["template_hint"],
    }


def _score_adapter_prompt(text: str) -> tuple[int, list[str]]:
    score = 0
    flags: list[str] = []
    risk_text = _adapter_risk_text(text)
    for flag, points, terms in ADAPTER_SCORE_RULES:
        if _adapter_contains_any(risk_text, terms):
            score += points
            flags.append(flag)
    if _adapter_contains_any(text, ("clearly adult", "明确成年", "成年人", "adult woman", "adult women")):
        score -= 2
        flags.append("adult_framing_present")
    if _adapter_contains_any(text, ("non-explicit", "非露骨", "非色情")):
        score -= 1
        flags.append("non_explicit_present")
    if _adapter_contains_any(text, ("editorial", "fashion", "cosplay event", "cinematic", "时尚", "电影", "角色定妆")):
        score -= 1
        flags.append("safe_visual_context_present")
    return max(0, score), flags


def _adapter_risk_level(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 6:
        return "medium"
    if score <= 10:
        return "high"
    return "severe"


def _adapter_unique_matches(text: str, terms: tuple[str, ...], limit: int = 4) -> list[str]:
    source = str(text or "")
    haystack = source.lower()
    matches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = str(term or "").strip()
        if not clean or clean.lower() in seen:
            continue
        has_match = bool(_adapter_phrase_pattern(clean).search(source)) if re.search(r"[A-Za-z0-9]", clean) else clean.lower() in haystack
        if has_match:
            matches.append(clean)
            seen.add(clean.lower())
        if len(matches) >= limit:
            break
    return matches


def _adapter_extract_aspect_ratio(text: str) -> str:
    source = str(text or "")
    match = re.search(r"(?<!\d)(\d{1,2}\s*[:：]\s*\d{1,2})(?!\d)", source)
    if match:
        return re.sub(r"\s+", "", match.group(1)).replace("：", ":")
    lowered = source.lower()
    if any(term in lowered for term in ("vertical", "portrait orientation", "9:16", "竖版", "竖屏")):
        return "9:16"
    if any(term in lowered for term in ("horizontal", "landscape orientation", "16:9", "横版", "横屏")):
        return "16:9"
    if any(term in lowered for term in ("square", "1:1", "方图", "正方形")):
        return "1:1"
    return ""


def _extract_adapter_intent(original_text: str, rewritten_seed: str, task_type: dict[str, Any]) -> dict[str, Any]:
    source = " ".join(part for part in [rewritten_seed, original_text] if part)
    subject = _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["subject"])
    if not subject and task_type.get("id") != "general_image":
        subject = [str(task_type.get("label") or task_type.get("id") or "").strip()]
    return {
        "aspect_ratio": _adapter_extract_aspect_ratio(original_text),
        "subject": subject,
        "identity": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["identity"]),
        "action": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["action"]),
        "clothing": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["clothing"]),
        "scene": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["scene"]),
        "camera": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["camera"]),
        "style": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["style"]),
    }


def _should_apply_adapter_replacement(category: str, source_text: str) -> bool:
    risk_text = _adapter_risk_text(source_text)
    if category == "age":
        if _adapter_contains_any(risk_text, ("loli", "teen-looking", "schoolgirl", "childlike", "少女", "幼态", "学生妹")):
            return True
        return _adapter_contains_any(risk_text, ADAPTER_MATURE_CONTEXT_TERMS)
    return True


def _apply_adapter_replacements(text: str) -> tuple[str, list[dict[str, str]]]:
    rewritten = str(text or "")
    changed: list[dict[str, str]] = []
    entries = sorted(ADAPTER_REPLACEMENTS, key=lambda item: max(len(term) for term in item[1]), reverse=True)
    for category, terms, replacement, reason in entries:
        if not _should_apply_adapter_replacement(category, rewritten):
            continue
        for term in terms:
            pattern = _adapter_phrase_pattern(term)
            if not pattern.search(rewritten):
                continue
            replaced = False

            def replace_match(match: re.Match) -> str:
                nonlocal replaced
                if _adapter_match_is_safe_context(category, term, rewritten, match.start(), match.end()):
                    return match.group(0)
                replaced = True
                return replacement

            rewritten = pattern.sub(replace_match, rewritten)
            if replaced:
                changed.append({
                    "from": term,
                    "to": replacement,
                    "category": category,
                    "reason": reason,
                })
    return rewritten.strip(), changed


def _adapter_warnings(text: str, score: int, flags: list[str], task_type: dict[str, Any], changed_terms: list[dict[str, str]]) -> tuple[list[str], bool]:
    warnings: list[str] = []
    should_block = False
    risk_text = _adapter_risk_text(text)
    has_people = _adapter_contains_any(risk_text, ADAPTER_PERSON_TERMS)
    has_mature_context = _adapter_contains_any(risk_text, ADAPTER_MATURE_CONTEXT_TERMS)
    has_sexual = _adapter_contains_any(risk_text, ADAPTER_SEXUAL_TERMS)
    has_explicit = _adapter_contains_any(risk_text, ADAPTER_EXPLICIT_TERMS)
    has_graphic_violence = _adapter_contains_any(risk_text, ADAPTER_GRAPHIC_VIOLENCE_TERMS)
    has_real_person_risk = _adapter_contains_any(risk_text, ADAPTER_REAL_PERSON_RISK_TERMS)
    has_hard_block_minor = _adapter_contains_any(risk_text, ADAPTER_HARD_BLOCK_MINOR_TERMS)

    if has_people and has_mature_context and not _adapter_contains_any(text, ("clearly adult", "明确成年", "成年人", "adult woman", "adult women")):
        warnings.append("人物提示词包含成熟穿搭、亲密姿态或镜头风险，已要求明确成年。")
    if "body_focus" in flags:
        warnings.append("检测到身体局部焦点，已转向服装剪裁、造型轮廓和完整构图。")
    if "transparent_exposure" in flags:
        warnings.append("检测到透明/透视服装表达，已转为叠层面料和不透明内层。")
    if "low_angle" in flags or "foot_foreground" in flags:
        warnings.append("检测到低机位或腿脚前景表达，已要求受控电影机位和非局部凝视。")
    if "private_scene" in flags and has_sexual:
        warnings.append("私密场景叠加性化表达风险较高，已转为非露骨室内/生活方式摄影语境。")
    if task_type.get("id") == "children_family" and has_sexual:
        warnings.append("儿童/家庭场景不能包含任何性化、暴露或亲密暗示。")
    if has_hard_block_minor and (has_mature_context or has_sexual or has_explicit):
        warnings.append("未成年或幼态词与性化/暴露表达组合，不能通过换词作为原意生成。")
        should_block = True
    if has_explicit:
        warnings.append("检测到明确色情、非同意或偷拍相关表达，将交给安全改写转为非露骨替代主题。")
    if has_graphic_violence:
        warnings.append("检测到真实血腥、肢解、酷刑或伤口特写风险，需要改成非图形化动作场景。")
    if has_real_person_risk:
        warnings.append("检测到真实人物色情化、深度伪造或私密场景风险，将交给安全改写转为原创角色。")
    if score >= 7:
        warnings.append("风险分较高，已按时尚/电影/角色定妆语境大幅改写。")
    elif score >= 3:
        warnings.append("提示词包含中等风险组合，已进行风险词替换和约束补全。")
    if changed_terms:
        warnings.append(f"已按词典替换 {len(changed_terms)} 处高风险表达。")
    return warnings, should_block


def analyze_prompt_adapter(text: str) -> dict[str, Any]:
    original_text = str(text or "").strip()
    task_type = _classify_adapter_task_type(original_text)
    risk_score, flags = _score_adapter_prompt(original_text)
    rewritten_seed, changed_terms = _apply_adapter_replacements(original_text)
    intent = _extract_adapter_intent(original_text, rewritten_seed, task_type)
    warnings, should_block = _adapter_warnings(original_text, risk_score, flags, task_type, changed_terms)
    return {
        "task_type": task_type,
        "intent": intent,
        "risk_score": risk_score,
        "risk_level": _adapter_risk_level(risk_score),
        "risk_flags": flags,
        "changed_terms": changed_terms,
        "warnings": warnings,
        "rewritten_seed": rewritten_seed,
        "blocked": should_block,
    }


def _build_adapter_fallback_prompt(analysis: dict[str, Any]) -> str:
    seed = str(analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    intent = analysis.get("intent") if isinstance(analysis.get("intent"), dict) else {}
    hint = str(task_type.get("template_hint") or "").strip()
    return _build_structured_adapter_prompt(seed, analysis, hint=hint, language="zh")


def _build_adapter_fallback_prompts(analysis: dict[str, Any]) -> dict[str, str]:
    seed = str(analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    hint = str(task_type.get("template_hint") or "").strip()
    return {
        "zh_prompt": _build_structured_adapter_prompt(seed, analysis, hint=hint, language="zh"),
        "en_prompt": _build_structured_adapter_prompt(seed, analysis, hint=hint, language="en"),
    }


def _adapter_intent_items(intent: dict[str, Any], key: str, fallback: str = "") -> str:
    value = intent.get(key)
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(items[:5]) if items else fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _is_structured_adapter_prompt(text: str) -> bool:
    cleaned = str(text or "")
    return all(re.search(rf"\[{index}\.\s*[^\]]+\]", cleaned) for index in range(1, len(SAFE_REWRITE_STRUCTURED_SECTIONS) + 1))


def _build_structured_adapter_prompt(source_text: str, analysis: dict[str, Any], hint: str = "", language: str = "en") -> str:
    source = str(source_text or analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    intent = analysis.get("intent") if isinstance(analysis.get("intent"), dict) else {}
    task_label = str(task_type.get("label") or task_type.get("id") or "通用图像").strip()
    task_hint = str(hint or task_type.get("template_hint") or "").strip()
    if language == "zh":
        aspect_ratio = _adapter_intent_items(intent, "aspect_ratio", "按原提示词指定画幅")
        subject = _adapter_intent_items(intent, "subject", "原提示词主体")
        identity = _adapter_intent_items(intent, "identity", "如涉及人物需明确成年")
        action = _adapter_intent_items(intent, "action", "自然、克制、平衡的姿态")
        clothing = _adapter_intent_items(intent, "clothing", "服装结构、面料层次、轮廓、配饰与造型")
        scene = _adapter_intent_items(intent, "scene", "原提示词场景与世界观背景")
        camera = _adapter_intent_items(intent, "camera", "完整构图、受控透视")
        style = _adapter_intent_items(intent, "style", "电影感 / 编辑感图像风格")
        sections = [
            ("1. 画布", f"{aspect_ratio}；高质量图像生成；适合作为壁纸、角色定妆照或主视觉。"),
            ("2. 图像类型", f"{task_label}。{style}。{task_hint}".strip("。")),
            ("3. 主体", f"{subject}；{identity}；如涉及成熟造型、时尚姿态、袜装、贴身服装或低机位镜头，人物必须明确成年。"),
            ("4. 角色 / 世界观", source or "保留原始角色身份、世界观、时代线索、色彩倾向与艺术意图。"),
            ("5. 姿态 / 动作", f"{action}；姿态动态但克制、自然、平衡，强调角色气场，不形成身体局部凝视。"),
            ("6. 服装 / 造型", f"{clothing}；强调服装剪裁、面料层次、颜色协调、配饰细节与角色身份感。"),
            ("7. 构图 / 镜头", f"{camera}；主体完整入镜，控制透视，避免切头切脚、偷窥感或身体局部强调。"),
            ("8. 场景 / 背景", f"{scene}；背景元素服务主体，层次清晰但不抢主体，标识或文字非必要时模糊且不可读。"),
            ("9. 光线 / 色彩", "电影级布光，主体与背景清晰分离，控制高光、阴影、对比度与高级调色，可加入轻微胶片颗粒。"),
            ("10. 材质 / 渲染", "皮肤自然，发丝、布料、金属、皮革等材质细节清晰；具备真实反射、粗糙度变化与高质量成片质感。"),
            ("11. 约束", "Safety constraints: non-explicit, no nudity, no minors, no watermark. 非露骨、无裸露、无未成年人、无水印；避免恋物化构图、身体局部凝视和无意义乱码。"),
        ]
    else:
        aspect_ratio = _adapter_intent_items(intent, "aspect_ratio", "Use the requested aspect ratio")
        subject = _adapter_intent_items(intent, "subject", "the requested main subject")
        identity = _adapter_intent_items(intent, "identity", "clearly adult subject if people are involved")
        action = _adapter_intent_items(intent, "action", "natural, restrained, balanced pose")
        clothing = _adapter_intent_items(intent, "clothing", "costume, fabric layers, silhouette, accessories, and styling")
        scene = _adapter_intent_items(intent, "scene", "the requested scene and worldbuilding context")
        camera = _adapter_intent_items(intent, "camera", "balanced full composition with controlled perspective")
        style = _adapter_intent_items(intent, "style", "cinematic/editorial image generation style")
        sections = [
            ("1. Canvas", f"{aspect_ratio}; high-quality image generation; polished wallpaper / character lookbook / key visual format when appropriate."),
            ("2. Image Type", f"{task_label}. {task_hint or style}."),
            ("3. Subject", f"{subject}; {identity}; clearly adult when any mature styling, fashion pose, stockings, tight clothing, or low-angle camera is involved."),
            ("4. Role / Worldbuilding", source or "Preserve the original role, setting, story cues, color palette, and artistic intent."),
            ("5. Pose / Action", f"{action}; dynamic but restrained, balanced and natural, emphasizing character presence rather than body-part focus."),
            ("6. Clothing / Styling", f"{clothing}; emphasize garment construction, layered fabric, tailoring, color harmony, accessories, and costume craftsmanship."),
            ("7. Composition / Camera", f"{camera}; complete subject framing, controlled perspective, no cropped head/feet, no voyeuristic or body-part-focused angle."),
            ("8. Scene / Background", f"{scene}; background elements support the subject, with signage or text blurred unless intentionally required."),
            ("9. Lighting / Color", "Cinematic lighting, clear subject separation, controlled highlights and shadows, refined color grade, optional subtle film grain."),
            ("10. Material / Rendering", "Natural skin texture, detailed hair, realistic fabric/metal/leather response, PBR-like material detail when suitable, high visual clarity."),
            ("11. Constraints", "Safety constraints: non-explicit, no nudity, no minors, no watermark. Also avoid fetish framing, body-part-focused composition, and unreadable random text unless intentionally blurred."),
        ]
    return "\n\n".join(f"[{title}]\n{body}" for title, body in sections).strip()


def _ensure_structured_safe_rewrite(text: str, analysis: dict[str, Any]) -> str:
    cleaned = _clean_safe_rewrite_output(text)
    if _is_structured_adapter_prompt(cleaned):
        return cleaned
    return _build_structured_adapter_prompt(cleaned, analysis)


def _extract_safe_rewrite_prompts(text: str, analysis: dict[str, Any]) -> dict[str, str]:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(_extract_first_json_block(cleaned))
        if isinstance(data, dict):
            zh_prompt = str(data.get("zh_prompt") or data.get("chinese_prompt") or data.get("中文提示") or "").strip()
            en_prompt = str(data.get("en_prompt") or data.get("english_prompt") or data.get("英文提示") or "").strip()
            if zh_prompt or en_prompt:
                fallback = _build_adapter_fallback_prompts(analysis)
                zh_prompt = zh_prompt or fallback["zh_prompt"]
                en_prompt = en_prompt or fallback["en_prompt"]
                return {
                    "zh_prompt": zh_prompt if _is_structured_adapter_prompt(zh_prompt) else _build_structured_adapter_prompt(zh_prompt, analysis, language="zh"),
                    "en_prompt": en_prompt if _is_structured_adapter_prompt(en_prompt) else _build_structured_adapter_prompt(en_prompt, analysis, language="en"),
                }
    except Exception:
        pass

    zh_match = re.search(r"(?:中文提示|改写后的中文提示|zh_prompt)\s*[:：]\s*(.+?)(?=\n\s*(?:英文提示|English Prompt|en_prompt)\s*[:：]|\Z)", cleaned, re.I | re.S)
    en_match = re.search(r"(?:英文提示|English Prompt|en_prompt)\s*[:：]\s*(.+)$", cleaned, re.I | re.S)
    fallback = _build_adapter_fallback_prompts(analysis)
    zh_prompt = _clean_safe_rewrite_output(zh_match.group(1) if zh_match else cleaned) or fallback["zh_prompt"]
    en_prompt = _clean_safe_rewrite_output(en_match.group(1) if en_match else "") or fallback["en_prompt"]
    return {
        "zh_prompt": zh_prompt if _is_structured_adapter_prompt(zh_prompt) else _build_structured_adapter_prompt(zh_prompt, analysis, language="zh"),
        "en_prompt": en_prompt if _is_structured_adapter_prompt(en_prompt) else _build_structured_adapter_prompt(en_prompt, analysis, language="en"),
    }


def _clean_safe_rewrite_output(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith(("text", "prompt")):
            cleaned = cleaned.split("\n", 1)[-1].strip()
    prefixes = (
        "Rewritten prompt:",
        "Rewritten Prompt:",
        "Safe rewritten prompt:",
        "Safe prompt:",
        "改写后的提示词：",
        "安全审核版提示词：",
        "提示词：",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                changed = True
    return cleaned.strip()


def _ensure_safe_rewrite_constraints(text: str) -> str:
    cleaned = _clean_safe_rewrite_output(text)
    lower = cleaned.lower()
    required_markers = ("non-explicit", "no nudity", "no minors", "no watermark")
    if all(marker in lower for marker in required_markers):
        return cleaned
    return _append_sentence_once(cleaned, SAFE_REWRITE_CONSTRAINT)


def safe_rewrite_prompt(text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rewrite one image prompt through the standalone safe image prompt adapter."""
    options = options or {}
    original_text = str(text or "").strip()
    if not original_text:
        raise ValueError("缺少要安全改写的提示词")
    adapter = analyze_prompt_adapter(original_text)
    if adapter.get("blocked"):
        warning_text = "；".join(adapter.get("warnings") or [])
        raise ValueError(f"该提示词包含不能通过安全改写处理的风险：{warning_text or '请改成安全替代主题'}")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    model = _choose_model(provider_id, str(options.get("model") or config.get("model") or "").strip())
    requested_effort = str(options.get("reasoning_effort") or "").strip().lower()
    reasoning_effort = requested_effort if requested_effort in GPT_REASONING_EFFORTS else "low"
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = "low"

    style = options.get("style") if isinstance(options.get("style"), dict) else {}
    style_text = str(style.get("promptTemplate") or style.get("prompt_style") or style.get("description") or "").strip()
    style_title = str(style.get("title") or style.get("name") or "").strip()
    user_prompt = "\n".join(part for part in [
        "Rewrite this image prompt with the safe image-generation adapter.",
        "Apply the role instructions and the high-risk wording replacement table exactly.",
        "Return exactly two final prompts: one rewritten Chinese prompt and one rewritten English prompt.",
        "Both zh_prompt and en_prompt must use the 11-section prompt skeleton.",
        "zh_prompt headings must be [1. 画布] through [11. 约束].",
        "en_prompt headings must be [1. Canvas] through [11. Constraints].",
        "Keep both prompts directly usable as final image-generation prompts.",
        "Return strict JSON only with keys zh_prompt and en_prompt.",
        "Use this local adapter analysis as mandatory guidance:",
        json.dumps(
            {
                "task_type": adapter.get("task_type"),
                "intent": adapter.get("intent"),
                "risk_score": adapter.get("risk_score"),
                "risk_level": adapter.get("risk_level"),
                "risk_flags": adapter.get("risk_flags"),
                "changed_terms": adapter.get("changed_terms"),
                "warnings": adapter.get("warnings"),
                "rewritten_seed": adapter.get("rewritten_seed"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        f"Style context: {style_title}\n{style_text}" if (style_title or style_text) else "",
        "User image prompt:",
        "<<<",
        original_text,
        ">>>",
    ] if part).strip()

    started = time.time()
    adapter_warning = ""
    prompt_payload: dict[str, str]
    try:
        raw_rewritten, provider_id, model, reasoning_effort, fallback_warning = _call_prompt_provider_with_pool_fallback(
            provider_id,
            user_prompt,
            SAFE_REWRITE_SYSTEM,
            model,
            reasoning_effort,
            "安全改写",
        )
        adapter_warning = fallback_warning
        prompt_payload = _extract_safe_rewrite_prompts(raw_rewritten, adapter)
    except Exception as exc:
        adapter_warning = f"模型安全改写失败，已使用本地词典降级结果：{exc}"
        prompt_payload = _build_adapter_fallback_prompts(adapter)
        adapter.setdefault("warnings", []).append(adapter_warning)
    zh_prompt = _ensure_safe_rewrite_constraints(prompt_payload.get("zh_prompt") or "")
    en_prompt = _ensure_safe_rewrite_constraints(prompt_payload.get("en_prompt") or "")
    if not zh_prompt or not en_prompt:
        raise RuntimeError("安全改写模型没有返回内容")
    return {
        "ok": True,
        "rewritten_prompt": zh_prompt,
        "prompt": zh_prompt,
        "zh_prompt": zh_prompt,
        "en_prompt": en_prompt,
        "rewritten_prompts": {
            "zh": zh_prompt,
            "en": en_prompt,
        },
        "task_type": adapter.get("task_type"),
        "intent": adapter.get("intent"),
        "risk_score": adapter.get("risk_score"),
        "risk_level": adapter.get("risk_level"),
        "risk_flags": adapter.get("risk_flags"),
        "changed_terms": adapter.get("changed_terms"),
        "changedTerms": adapter.get("changed_terms"),
        "warnings": adapter.get("warnings"),
        "adapter_warning": adapter_warning,
        "adapter": adapter,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
    }


def _assistant_chat_request(text: str, message: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    current_text = str(text or "").strip()
    user_message = str(message or "").strip()
    if not current_text and not user_message:
        raise ValueError("请输入聊天内容或选择文本节点")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    model = _choose_model(provider_id, str(options.get("model") or config.get("model") or "").strip())
    requested_effort = str(options.get("reasoning_effort") or "").strip().lower()
    reasoning_effort = requested_effort if requested_effort in GPT_REASONING_EFFORTS else "low"
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = str(config.get("reasoning_effort") or "medium").strip().lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = "medium"

    style = options.get("style") if isinstance(options.get("style"), dict) else {}
    style_text = str(style.get("promptTemplate") or style.get("prompt_style") or style.get("description") or "").strip()
    style_title = str(style.get("title") or style.get("name") or "").strip()
    history = options.get("history") if isinstance(options.get("history"), list) else []
    history_lines = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = "用户" if str(item.get("role") or "") == "user" else "助手"
        content = str(item.get("text") or item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content[:1200]}")

    prompt = "\n".join(part for part in [
        "请围绕当前文本节点内容和用户消息进行提示词方向讨论。",
        "不要调用或模拟正式多版本候选生成；如果用户需要正式版本，请建议他们使用“生成版本”。",
        f"当前文本节点内容：\n<<<\n{current_text}\n>>>" if current_text else "当前文本节点内容：空",
        f"当前风格预设：{style_title}\n{style_text}" if (style_title or style_text) else "",
        "最近对话：\n" + "\n".join(history_lines) if history_lines else "",
        f"用户消息：\n{user_message}" if user_message else "用户消息：请基于当前文本节点给出方向建议。",
    ] if part).strip()

    return {
        "prompt": prompt,
        "provider_id": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def assistant_chat(text: str, message: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lightweight prompt-direction chat that avoids the heavy V7 candidate flow."""
    request = _assistant_chat_request(text, message, options)
    provider_id = request["provider_id"]
    model = request["model"]
    reasoning_effort = request["reasoning_effort"]
    started = time.time()
    warning = ""
    try:
        reply = _call_prompt_provider(provider_id, request["prompt"], ASSISTANT_CHAT_SYSTEM, model, reasoning_effort)
    except Exception as exc:
        if not _should_fallback_prompt_chat_to_pool(provider_id, exc):
            raise
        reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], ASSISTANT_CHAT_SYSTEM, exc)
        provider_id = "chatgpt_pool"
        reasoning_effort = ""
    if not reply:
        raise RuntimeError("聊天模型没有返回内容")
    result = {
        "ok": True,
        "reply": reply,
        "message": reply,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
    }
    if warning:
        result["warning"] = warning
        result["fallback"] = "chatgpt_pool_chat"
    return result


def _split_rule_module_labels(split_rule: dict[str, Any] | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for module in (split_rule or {}).get("modules") or []:
        if not isinstance(module, dict) or module.get("enabled") is False:
            continue
        key = str(module.get("key") or "").strip()
        if key:
            labels[key] = str(module.get("label") or key).strip() or key
    return labels


def _normalize_prompt_block_type(value: Any, module_labels: dict[str, str] | None = None) -> str:
    raw = str(value or "custom").strip().lower().replace("-", "_").replace(" ", "_")
    labels = {**PROMPT_BLOCK_MODULE_LABELS, **(module_labels or {})}
    if raw in labels:
        return raw
    normalized = PROMPT_BLOCK_MODULE_ALIASES.get(raw, raw)
    if normalized not in labels:
        return "custom"
    return normalized


PROMPT_BLOCK_TYPE_HINTS = (
    ("storyboard", ("分镜", "镜头脚本", "storyboard", "shot list")),
    ("infographic", ("信息图", "数据图表", "流程图", "仪表盘", "infographic", "data visualization", "dashboard")),
    ("pattern", ("无缝图案", "连续纹样", "平铺纹理", "seamless pattern", "repeat pattern")),
    ("three_d", ("3d视觉", "3d 视觉", "三维渲染", "立体渲染", "3d render", "cgi render")),
    ("fashion", ("服装设计", "时装", "穿搭", "秀场", "lookbook", "fashion editorial")),
    ("food", ("美食", "食物摄影", "菜品", "餐饮", "food photography", "dish", "cuisine")),
    ("interior", ("室内设计", "室内空间", "客厅", "卧室", "interior design")),
    ("architecture", ("建筑外观", "建筑设计", "建筑摄影", "architecture", "facade")),
    ("product", ("商品", "产品图", "电商", "包装设计", "product shot", "e-commerce", "packaging")),
    ("animal", ("动物", "宠物", "猫咪", "小狗", "wildlife", "pet portrait")),
    ("landscape", ("风景", "自然景观", "山川", "海岸", "landscape", "scenery")),
    ("character", ("角色设定", "角色设计", "人物设定", "character design", "character sheet")),
    ("scene_concept", ("场景概念", "环境概念", "世界观场景", "concept environment", "environment design")),
    ("social", ("小红书", "社交媒体", "社媒", "公众号首图", "social media", "instagram post")),
    ("poster", ("海报", "主视觉", "kv", "banner", "poster", "key visual", "book cover", "封面")),
    ("portrait", ("人像", "肖像", "人物写真", "portrait", "headshot")),
    ("illustration", ("插画", "漫画", "绘本", "illustration", "comic")),
)


def _infer_prompt_block_primary_type_from_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    for primary_type, markers in PROMPT_BLOCK_TYPE_HINTS:
        if any(marker in normalized for marker in markers):
            return primary_type
    return ""


def _infer_prompt_block_primary_type_from_modules(data: Any) -> str:
    payload = data if isinstance(data, dict) else {}
    raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    scores: dict[str, int] = {}
    for item in raw_blocks:
        if not isinstance(item, dict):
            continue
        module_type = _normalize_prompt_block_type(item.get("module_type") or item.get("type"))
        for owner in PROMPT_BLOCK_MODULE_TYPE_OWNERS.get(module_type, set()):
            scores[owner] = scores.get(owner, 0) + 1
    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return ""
    return ranked[0][0]


def _prompt_block_template_context(primary_type: str, split_rule: dict[str, Any] | None = None) -> str:
    template = split_rule or PROMPT_BLOCK_TEMPLATES.get(str(primary_type or "").strip())
    if not template:
        return "拆分规则：未指定；请根据原文判断 primary_type，并按通用语义拆分。"
    modules = []
    for module in template.get("modules") or []:
        if not isinstance(module, dict) or module.get("enabled") is False:
            continue
        key = str(module.get("key") or "").strip()
        label = str(module.get("label") or "").strip()
        hint = str(module.get("hint") or "").strip()
        if key:
            required = "，重点模块" if module.get("required") else ""
            modules.append(f"- {key}（{label or key}{required}）：{hint}" if hint else f"- {key}（{label or key}{required}）")
    options = template.get("options") if isinstance(template.get("options"), dict) else {}
    granularity = {"compact": "精简", "balanced": "均衡", "detailed": "详细"}.get(str(options.get("granularity") or "balanced"), "均衡")
    max_blocks = max(3, min(30, int(options.get("max_blocks") or 18)))
    return "\n".join([
        f"拆分规则：{template.get('name') or primary_type}（rule_id={template.get('id') or 'system'}，version={template.get('version') or 1}，primary_type={primary_type}）",
        f"拆分粒度：{granularity}；最多输出 {max_blocks} 个素材块。",
        "该类型允许并优先使用以下模块；原文没有对应信息时不要强行生成：",
        *modules,
    ])


def _normalize_extracted_prompt_blocks(
    data: Any,
    primary_type: str = "",
    split_rule: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    payload = data if isinstance(data, dict) else {}
    raw_blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    applicable_type = str(primary_type or "").strip()
    if applicable_type not in PROMPT_BLOCK_PRIMARY_TYPES:
        applicable_type = ""
    blocks: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    module_labels = _split_rule_module_labels(split_rule)
    allowed_modules = set(module_labels)
    options = (split_rule or {}).get("options") if isinstance((split_rule or {}).get("options"), dict) else {}
    max_blocks = max(3, min(30, int(options.get("max_blocks") or 24)))
    for item in raw_blocks[:30]:
        if not isinstance(item, dict):
            continue
        content = _clean_string(item.get("content") or item.get("text"), 12000)
        if not content:
            continue
        module_type = _normalize_prompt_block_type(item.get("module_type") or item.get("type"), module_labels)
        if allowed_modules and module_type not in allowed_modules:
            continue
        name = _clean_string(item.get("name") or item.get("label"), 120)
        if not name:
            name = module_labels.get(module_type) or PROMPT_BLOCK_MODULE_LABELS.get(module_type, "素材块")
        key = (module_type, re.sub(r"\s+", " ", content).lower())
        if key in seen:
            continue
        seen.add(key)
        tags = []
        for tag in item.get("tags") if isinstance(item.get("tags"), list) else []:
            clean_tag = _clean_string(tag, 32).lstrip("#")
            if clean_tag and clean_tag not in tags:
                tags.append(clean_tag)
        blocks.append({
            "name": name,
            "module_type": module_type,
            "content": content,
            "compact_content": _clean_string(item.get("compact_content") or item.get("compact"), 6000),
            "english_content": _clean_string(item.get("english_content") or item.get("english"), 12000),
            "applicable_types": [applicable_type] if applicable_type else [],
            "tags": tags[:12],
        })
    if not blocks:
        raise ValueError("没有从输入内容中拆出有效素材块")
    return blocks[:max_blocks]


def _split_rule_snapshot(split_rule: dict[str, Any] | None) -> dict[str, Any]:
    if not split_rule:
        return {}
    return {
        "id": str(split_rule.get("id") or ""),
        "name": str(split_rule.get("name") or ""),
        "primary_type": str(split_rule.get("primary_type") or ""),
        "version": int(split_rule.get("version") or 1),
        "system": bool(split_rule.get("system")),
        "base_template_id": str(split_rule.get("base_template_id") or ""),
        "modules": [dict(module) for module in (split_rule.get("modules") or []) if isinstance(module, dict)],
        "options": dict(split_rule.get("options") or {}),
    }


def extract_reusable_prompt_blocks(
    text: str,
    primary_type: str = "",
    options: dict[str, Any] | None = None,
    split_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Split one full image prompt into independently reusable prompt blocks."""
    source_text = str(text or "").strip()
    if not source_text:
        raise ValueError("缺少要拆分的完整提示词")
    options = options or {}
    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    requested_model = str(options.get("model") or config.get("model") or "").strip()
    original_provider_id = provider_id
    provider_id, model, model_warning = _select_prompt_provider_model_with_pool_fallback(
        provider_id,
        requested_model,
        "素材块拆分",
    )
    reasoning_effort = str(options.get("reasoning_effort") or options.get("reasoningEffort") or "low").strip().lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = "low"
    requested_type = str(primary_type or "").strip()
    if requested_type not in PROMPT_BLOCK_PRIMARY_TYPES:
        requested_type = ""
    suggested_type = requested_type or _infer_prompt_block_primary_type_from_text(source_text)
    prompt = "\n".join([
        f"适用内容类型：{requested_type or '自动判断'}",
        f"自动类型初步判断：{suggested_type or '未知，请根据原文判断'}",
        _prompt_block_template_context(suggested_type, split_rule),
        "请把下面的完整图像生成提示词拆成可独立复用的素材块：",
        "<<<",
        source_text[:50000],
        ">>>",
    ])
    started = time.time()
    raw_text, provider_id, model, reasoning_effort, warning = _call_prompt_provider_with_pool_fallback(
        provider_id,
        prompt,
        PROMPT_BLOCK_EXTRACTION_SYSTEM,
        model,
        reasoning_effort,
        "素材块拆分",
    )
    warning = warning or model_warning
    try:
        if not raw_text:
            raise RuntimeError("素材块拆分模型没有返回内容")
        parsed = json.loads(_extract_first_json_block(raw_text))
        model_type = str(parsed.get("primary_type") or parsed.get("primaryType") or "").strip() if isinstance(parsed, dict) else ""
        resolved_type = requested_type or (model_type if model_type in PROMPT_BLOCK_PRIMARY_TYPES else "") or suggested_type or _infer_prompt_block_primary_type_from_modules(parsed)
        blocks = _normalize_extracted_prompt_blocks(parsed, resolved_type, split_rule)
    except Exception as exc:
        if provider_id == "chatgpt_pool" or not _should_fallback_prompt_chat_to_pool(original_provider_id, exc):
            raise
        raw_text, model = _chatgpt_pool_chat_reply(prompt, PROMPT_BLOCK_EXTRACTION_SYSTEM)
        parsed = json.loads(_extract_first_json_block(raw_text))
        model_type = str(parsed.get("primary_type") or parsed.get("primaryType") or "").strip() if isinstance(parsed, dict) else ""
        resolved_type = requested_type or (model_type if model_type in PROMPT_BLOCK_PRIMARY_TYPES else "") or suggested_type or _infer_prompt_block_primary_type_from_modules(parsed)
        blocks = _normalize_extracted_prompt_blocks(parsed, resolved_type, split_rule)
        provider_id = "chatgpt_pool"
        reasoning_effort = ""
        warning = f"{_prompt_pool_fallback_reason(exc)}素材块拆分：{exc}"
        print(f"⚠️ Prompt Skill 素材块拆分 validation fallback to account pool: {exc}")
    result = {
        "ok": True,
        "mode": "text",
        "blocks": blocks,
        "primary_type": resolved_type,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
    }
    rule_snapshot = _split_rule_snapshot(split_rule)
    if rule_snapshot:
        result["split_rule"] = rule_snapshot
    if warning:
        result["warning"] = warning
        result["fallback"] = "chatgpt_pool_chat"
    return result


def assistant_chat_stream(text: str, message: str, options: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Stream lightweight prompt-direction chat deltas."""
    request = _assistant_chat_request(text, message, options)
    provider_id = request["provider_id"]
    model = request["model"]
    reasoning_effort = request["reasoning_effort"]
    started = time.time()
    yield {
        "type": "meta",
        "ok": True,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }
    chunks: list[str] = []
    emitted = False
    warning = ""
    try:
        for chunk in _call_prompt_provider_stream(provider_id, request["prompt"], ASSISTANT_CHAT_SYSTEM, model, reasoning_effort):
            text_chunk = str(chunk or "")
            if not text_chunk:
                continue
            emitted = True
            chunks.append(text_chunk)
            yield {"type": "delta", "text": text_chunk}
    except Exception as stream_error:
        if emitted:
            raise
        if _should_fallback_prompt_chat_to_pool(provider_id, stream_error):
            reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], ASSISTANT_CHAT_SYSTEM, stream_error)
            provider_id = "chatgpt_pool"
            reasoning_effort = ""
        else:
            try:
                reply = _call_prompt_provider(provider_id, request["prompt"], ASSISTANT_CHAT_SYSTEM, model, reasoning_effort)
            except Exception as full_error:
                if not _should_fallback_prompt_chat_to_pool(provider_id, full_error):
                    raise
                reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], ASSISTANT_CHAT_SYSTEM, full_error)
                provider_id = "chatgpt_pool"
                reasoning_effort = ""
        if not reply:
            raise RuntimeError("聊天模型没有返回内容")
        chunks = [reply]
        yield {"type": "delta", "text": reply}

    reply = "".join(chunks).strip()
    if not reply:
        raise RuntimeError("聊天模型没有返回内容")
    yield {
        "type": "done",
        "ok": True,
        "reply": reply,
        "message": reply,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
        **({"warning": warning, "fallback": "chatgpt_pool_chat"} if warning else {}),
    }


IMAGE_ANALYSIS_SPECIALIZED_FLAGS = {
    "layout_prompt": "layout_design",
    "cover_template_prompt": "cover_template",
    "table_card_layout_prompt": "table_card",
    "web_design_style_prompt": "web_design",
}
IMAGE_ANALYSIS_FLAG_HINTS = {
    "layout_design": (
        "排版",
        "版式",
        "平面设计",
        "海报",
        "poster",
        "信息图",
        "infographic",
        "杂志",
        "画册",
        "宣传页",
        "广告图",
        "banner",
        "视觉层级",
        "图文布局",
    ),
    "cover_template": (
        "封面",
        "cover",
        "小红书",
        "缩略图",
        "thumbnail",
        "杂志封面",
        "书封",
        "专辑封面",
        "视频封面",
        "首图",
        "标题区",
    ),
    "table_card": (
        "表格",
        "table",
        "卡片",
        "card",
        "信息卡",
        "资料卡",
        "产品卡",
        "价格卡",
        "对比表",
        "图表",
        "chart",
        "dashboard",
        "仪表盘",
        "规格",
        "列表",
        "数据",
    ),
    "web_design": (
        "网页",
        "网站",
        "web",
        "landing",
        "官网",
        "页面",
        "ui",
        "界面",
        "app",
        "dashboard",
        "后台",
        "组件",
        "导航栏",
        "按钮",
        "hero",
    ),
}


IMAGE_PROMPT_ANALYSIS_SYSTEM = """你是“图片提示词拆解”专家，服务于一个桌面画布里的提示词助手。
你的任务不是生图，也不是图像编辑，而是把输入图片拆解成可独立用于文生图的提示词和结构化模块。

必须遵守：
1. 默认不要在主候选提示词里生成、复制或保留图片中的文字、品牌名、价格、型号、Logo、二维码、水印。
2. 图片里的文字只用于理解层级、版式、信息密度和视觉结构；OCR 内容单独放进 text_markdown 和 text_regions，供用户手动编辑。
3. 如果用户明确要求保留文字，也仍然只把 OCR 放入 text_markdown，不要直接混进 main_prompt_no_text。
4. 多图输入的第一张用于分析视觉结构；其他图片暂不参与首版文生图结果，只记录为后续扩展输入，不要擅自混合主体。
5. 除 text_markdown 中的 OCR 原文可以保留图片原始文字语言外，其余所有 prompt_blocks、visual_summary、layout、generation_hints、warnings、type_rationale 都必须使用简体中文表达。可以保留必要英文专有名词，但句子主体必须是中文。
6. negative_prompt 必须根据当前图片分析“这张图不应该出现什么”来写，不能使用通用负面词清单。它应围绕当前图片的主体、版式、色彩、光影、材质、文字风险、UI/封面/卡片结构等具体错误来描述。
7. 所有 prompt_blocks 必须是 standalone 文生图提示词，不得要求模型参考、保留、复刻、改动某张图片，也不得出现“参考图”“原图”“同款”“image1”“以图生图”“图像编辑”等依赖外部图片的词。
8. 主候选提示词只写对生成图像有意义的视觉描述，不要出现“区域”“占位”“请勾选”“OCR”“编辑稿”“保留图中文字”等工具话术；文字槽位和原文只写入 text_regions/text_markdown。
9. 主候选必须细拆人物主体：姿态、动作、手势、手臂位置、头部角度、表情、视线方向、身体裁切、完整服装造型、妆发、配饰、前后景遮挡关系。有人像时不要只写“人物肖像/半身像”。
   - 完整服装造型必须从上到下检查：发饰/头饰、上衣/外套/领口/袖型、腰部/腰带、裙装或裤装、腿部覆盖物、袜装、鞋履、手套、包袋、首饰和其他配饰。
   - 袜装/腿部覆盖物是独立服饰层级，必须中性描述颜色、长度、材质和覆盖范围；例如白色连裤袜、黑色裤袜、长筒袜、短袜、裸腿、靴袜、过膝袜、透明/不透明质感等。只要画面可见，就必须写入 subjects.outfit 和 main_prompt_no_text，不要因为它属于丝袜/袜装/贴身服饰而省略。
   - 若腿部或脚部被裁切/遮挡，也要在 body_crop 或 outfit 中说明“腿部被裁切/袜装不可见/鞋履不可见”，避免默认忽略下半身服饰。
10. 主候选必须细拆非文字叠加视觉元素：局部彩色图层、矩形框选框、控制点、鼠标指针、裁切框、蒙版、半透明色块、网点纹理、几何框、发光描边、插入图片面板等。若这些元素出现在目标画面内部，要当作画面设计元素描述，不要当作工具说明删除。
11. 主候选必须先判断媒介与渲染语言：真实摄影、CG/3D、扁平矢量、手绘插画、漫画/动漫、水彩、拼贴、像素风、低多边形、UI 截图等不能混淆。不要把像素风误写成写实摄影、普通插画或柔和矢量。
12. 风格不是默认全局滤镜，必须判断作用范围：主体、背景、物件、装饰、文字/标题、留白底版可能分别使用不同媒介。主候选必须写清楚“哪一部分是某种风格”，不得把局部像素风套到所有文字、Logo、标题或整张版式上。
13. visual_style.style_regions 必须逐区域列出风格作用范围：每一项说明 target（作用对象/区域）、medium（媒介类型）、rendering（渲染方式）、edge_quality（边缘质量）、texture（纹理/颗粒）、palette（色板）、notes（额外限制）。例如中心插画可为像素风，标题文字可为平滑无衬线，留白底版可为干净平面色块。
14. 如果文字/标题不是像素字体，而是平滑粗体无衬线、干净矢量字体、现代排版字体或日文字体，必须明确写出文字风格独立于像素插画，不要像素化文字。只有当文字边缘也明显是像素块/位图字体时，才允许写“像素字体”。
15. visual_style 必须描述媒介、渲染方式、风格作用范围、主体/背景风格、文字/标题风格、区域风格列表、边缘质量、纹理颗粒、色板/渐变方式和分辨率语言。像素风只是其中一种媒介，不能成为默认全局规则。
16. subjects 必须描述主体身份、姿态/动作、表情/视线、身体裁切、完整服装造型、位置和与叠加元素的关系。服装造型不能只概括为“制服/连衣裙/学院风”，必须保留可见的颜色、版型、材质、层次、腿部袜装/连裤袜/长袜/鞋履/配饰等关键差异。
17. overlays 必须列出每个明显叠加层或编辑视觉元素的位置、形状、颜色、边框/控制点/指针、透明度/纹理、层级关系和覆盖对象。
18. 模块分层必须准确：
   - 全类型必出：main_prompt_no_text、universal_style_prompt、negative_prompt、no_text_prompt、text_markdown、完整 JSON。
   - 专项命中才出：layout_prompt、cover_template_prompt、table_card_layout_prompt、web_design_style_prompt。
   - 不要为了填满卡片而输出专项提示词；未命中类型时对应字段必须为空字符串，并将对应 image_type_flags 设为 false。
19. 专项模板模块必须使用可替换占位符，为后续主体参考图融合和文字替换预留槽位。占位符必须写成英文大写方括号，例如 [SUBJECT_GROUP]、[POSE_OR_EXPRESSION]、[OUTFIT_STYLE]、[MAIN_OBJECT]、[BACKGROUND_SCENE]、[MAIN_TITLE]、[SUBTITLE]、[SUPPORTING_TEXT]。占位符不是“参考图/原图”依赖，也不是工具话术；它们只代表未来可替换内容。
20. 专项模块判定：
   - layout_prompt：仅当图像是海报、信息图、平面设计、杂志/画册版式、图文排版或明显 layout design 时输出。
   - cover_template_prompt：仅当图像是封面、社媒首图/小红书封面、视频缩略图、杂志/书籍/专辑封面时输出。
   - table_card_layout_prompt：仅当图像是资料卡、产品卡、表格、图表、对比页、仪表盘、信息卡等信息块布局时输出。
   - web_design_style_prompt：仅当图像是网页、落地页、后台、App/UI 截图、组件化界面时输出。
21. text_regions 必须按画面从上到下、从左到右列出可见文字槽位；每个槽位要有稳定 id（T1、T2...）、识别文字、语义角色、相对位置、对齐、字号层级、字重/字体气质和颜色/风格。text_markdown 必须使用这些 T 编号，不能包裹代码围栏。
22. placeholder_slots 必须列出本次分析中可替换的主体/姿态/服装/物件/背景/文字槽位；文字类槽位要尽量关联 text_regions 的 T 编号。
23. 输出必须是合法 JSON 对象，不要 markdown，不要解释，不要代码围栏。

JSON 形状：
{
  "image_kind": "海报 / 封面 / 信息图 / 表格卡片 / 网页截图 / 产品图 / 摄影 / 插画 / 其他",
  "image_type_flags": {"layout_design":false,"cover_template":false,"table_card":false,"web_design":false},
  "type_rationale": {"layout_design":"","cover_template":"","table_card":"","web_design":""},
  "visual_summary": "一句话描述画面和用途",
  "visual_style": {"medium":"","rendering":"","style_scope":"","subject_background_style":"","typography_style":"","text_style_is_pixelated":false,"style_regions":[{"target":"","medium":"","rendering":"","edge_quality":"","texture":"","palette":"","notes":""}],"edge_quality":"","texture":"","palette":"","resolution_language":""},
  "prompt_blocks": {
    "main_prompt_no_text": "默认主候选提示词，禁止生成任何可读文字",
    "universal_style_prompt": "通用风格提示词",
    "layout_prompt": "仅 layout_design=true 时输出排版布局提示词，否则空字符串",
    "negative_prompt": "基于当前图片具体分析出来的不应出现内容，必须中文、必须图像特定、不能是通用清单",
    "cover_template_prompt": "仅 cover_template=true 时输出封面模板提示词，否则空字符串",
    "table_card_layout_prompt": "仅 table_card=true 时输出表格/卡片信息布局提示词，否则空字符串",
    "web_design_style_prompt": "仅 web_design=true 时输出网页设计风格词，否则空字符串",
    "no_text_prompt": "明确禁止生成文字的约束"
  },
  "text_markdown": "按 Markdown 整理图片中的可见文字；没有则为空字符串",
  "text_regions": [
    {"id":"T1","text":"识别文字","role":"刊期/标题/正文/按钮等","position":"顶部左侧/中部/底部右侧等","anchor":"top-left/top-center/center/bottom-right 等","alignment":"left/center/right","size":"small/medium/large/hero","style":"字体气质、字重、颜色、大小写、行距等"}
  ],
  "placeholder_slots": [
    {"slot":"[SUBJECT_GROUP]","label":"主体组","kind":"subject","description":"后续主体参考图融合或替换主体身份","source_region_id":""},
    {"slot":"[MAIN_TITLE]","label":"主标题","kind":"text","description":"主标题文字槽位","source_region_id":"T1"}
  ],
  "layout": {"aspect_ratio":"","composition":"","hierarchy":"","spacing":"","alignment":""},
  "subjects": [{"name":"","role":"","visual_traits":"","pose":"","expression":"","gaze":"","body_crop":"","outfit":"","makeup_hair":"","accessories":"","placement":"","relationship":""}],
  "overlays": [{"id":"O1","type":"selection_frame/inset_image/cursor/mask/shape/texture/other","position":"","appearance":"","layering":"","relationship":""}],
  "generation_hints": {"aspect_ratio":"","medium":"","camera":"","lighting":"","palette":"","rendering":"","style_keywords":[]},
  "confidence": {"overall":0.0,"ocr":0.0,"layout":0.0},
  "warnings": ["必要提醒"]
}""".strip()


def _clean_string(value: Any, limit: int = 8000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _image_analysis_limits() -> tuple[int, int, int, int]:
    max_edge = _safe_int(PROMPT_IMAGE_ANALYSIS_MAX_EDGE, 1800, 512, 4096)
    max_bytes = _safe_int(PROMPT_IMAGE_ANALYSIS_MAX_BYTES, 3 * 1024 * 1024, 512 * 1024, 12 * 1024 * 1024)
    quality = _safe_int(PROMPT_IMAGE_ANALYSIS_JPEG_QUALITY, 86, 50, 95)
    min_quality = _safe_int(PROMPT_IMAGE_ANALYSIS_MIN_JPEG_QUALITY, 68, 40, quality)
    return max_edge, max_bytes, quality, min_quality


def _data_image_parts(image_url: str) -> tuple[str, str] | None:
    match = re.match(r"^data:(image/[a-z0-9.+-]+);base64,(.*)$", str(image_url or "").strip(), re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return str(match.group(1) or "image/png").lower(), re.sub(r"\s+", "", str(match.group(2) or ""))


def _analysis_image_mime_type(image_url: str, fallback: str = "image/png") -> str:
    parts = _data_image_parts(image_url)
    if parts:
        return parts[0]
    return _clean_string(fallback or "image/png", 80) or "image/png"


def _image_resampling_lanczos() -> Any:
    if Image is None:
        return 1
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", getattr(Image, "LANCZOS", 1))


def _image_to_analysis_jpeg_data_url(image: Any) -> str:
    if Image is None or ImageOps is None:
        raise RuntimeError("Pillow unavailable")
    max_edge, max_bytes, quality, min_quality = _image_analysis_limits()
    image = ImageOps.exif_transpose(image)
    if max(image.size or (0, 0)) > max_edge:
        image.thumbnail((max_edge, max_edge), _image_resampling_lanczos())
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and image.info.get("transparency") is not None):
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha_source = image.convert("RGBA")
        background.paste(alpha_source, mask=alpha_source.getchannel("A"))
        rgb = background
    else:
        rgb = image.convert("RGB")

    current_quality = quality
    for _ in range(8):
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=current_quality, optimize=True, progressive=True)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
        if current_quality > min_quality:
            current_quality = max(min_quality, current_quality - 8)
            continue
        width, height = rgb.size
        next_width = max(1, int(width * 0.82))
        next_height = max(1, int(height * 0.82))
        if next_width >= width and next_height >= height:
            break
        rgb = rgb.resize((next_width, next_height), _image_resampling_lanczos())
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _prepare_image_analysis_image_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return _clean_string(raw, 8000)
    parts = _data_image_parts(raw)
    if not parts:
        return raw
    _, payload = parts
    if Image is None or ImageOps is None:
        if len(raw) > 40_000_000:
            raise ValueError("图片过大且当前环境无法压缩，请换一张较小的参考图")
        return raw
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("图片数据不是有效的 base64，请重新选择图片") from exc
    max_edge, max_bytes, _, _ = _image_analysis_limits()
    if len(data) <= max_bytes and len(raw) <= 40_000_000:
        try:
            image = Image.open(BytesIO(data))
            image.load()
        except (UnidentifiedImageError, OSError, ValueError):
            return raw
        if max(image.size or (0, 0)) <= max_edge:
            return raw
        return _image_to_analysis_jpeg_data_url(image)
    try:
        image = Image.open(BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("图片数据过大且无法解析压缩，请重新选择图片") from exc
    return _image_to_analysis_jpeg_data_url(image)


def _first_text(data: dict[str, Any], *keys: str, limit: int = 8000) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_string(value, limit)
    return ""


def _normalize_image_analysis_inputs(images: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            continue
        image_url = _prepare_image_analysis_image_url(
            item.get("data_url")
            or item.get("dataUrl")
            or item.get("imageData")
            or item.get("base64")
            or item.get("url")
            or item.get("imageUrl")
        )
        if not image_url:
            continue
        if not (image_url.startswith("data:image/") or image_url.startswith("http://") or image_url.startswith("https://")):
            continue
        image_id = _clean_string(item.get("id") or f"image{index + 1}", 32) or f"image{index + 1}"
        normalized.append(
            {
                "id": image_id,
                "label": _clean_string(item.get("label") or item.get("name") or image_id, 120),
                "source_node_id": _clean_string(item.get("sourceNodeId") or item.get("source_node_id"), 120),
                "mime_type": _analysis_image_mime_type(
                    image_url,
                    str(item.get("mime_type") or item.get("mimeType") or item.get("type") or "image/png"),
                ),
                "image_url": image_url,
                "role": "primary" if not normalized else "fusion_reserved",
            }
        )
    return normalized


def _build_image_analysis_user_prompt(message: str, images: list[dict[str, Any]]) -> str:
    primary = images[0]
    extra = images[1:]
    extra_lines = [
        f"- {item['id']}：{item.get('label') or item['id']}（仅记录为后续扩展输入，不参与首版文生图提示词）"
        for item in extra
    ]
    return "\n".join(
        part
        for part in [
            "请分析第一张输入图片，并输出用于提示词助手的结构化结果。",
            f"输入图片名称：{primary.get('label') or primary['id']}",
            "补充图片：\n" + "\n".join(extra_lines) if extra_lines else "",
            f"用户补充要求：\n{message}" if message else "用户补充要求：默认提取可独立用于文生图的视觉结构、风格、版式和可复用提示词。",
            "主候选必须默认不包含任何可读文字；如画面是海报、网页、表格、卡片，也只描述文字区域、信息层级和排版关系。",
            "请特别检查主体姿态/表情/手势/身体裁切，以及画面内的局部彩色图层、框选边框、控制点、鼠标指针、蒙版、几何叠加和前后景遮挡关系。",
            "请特别检查媒介与渲染语言及其作用范围：真实摄影、普通插画、扁平矢量、3D、像素风、动漫、水彩等必须区分；像素风要写清楚作用于主体/背景/物件还是也作用于文字。文字若是平滑粗体或干净矢量字体，不要写成像素字体。",
            "模块策略：通用风格提示词、负面提示词、图中文字 Markdown、完整 JSON 是全类型结果；排版布局、封面模板、表格/卡片、网页设计四类提示词只有在 image_type_flags 对应类型命中时才输出，未命中必须留空。",
        ]
        if part
    ).strip()


def _compose_no_text_prompt(blocks: dict[str, Any], data: dict[str, Any]) -> str:
    main = _first_text(blocks, "main_prompt_no_text", "main_prompt", "prompt", "完整提示词", limit=12000)
    if main:
        return _append_sentence_once(main, NO_TEXT_CHINESE_CONSTRAINT)

    pieces = [
        _first_text(data, "visual_summary", "summary", limit=1200),
        _first_text(blocks, "universal_style_prompt", "style_prompt", limit=2400),
        _first_text(blocks, "layout_prompt", "composition_prompt", limit=2400),
        _first_text(blocks, "cover_template_prompt", "template_prompt", limit=2000),
        _first_text(blocks, "table_card_layout_prompt", limit=1600),
        _first_text(blocks, "web_design_style_prompt", limit=1600),
    ]
    composed = "\n\n".join(piece for piece in pieces if piece).strip()
    if not composed:
        composed = "生成一张高质量文生图画面，采用清晰构图、统一风格、稳定色彩关系、明确光影质感、准确材质表现、丰富空间层级和自然视觉节奏。"
    negative = _first_text(blocks, "negative_prompt", "negative", limit=2000)
    no_text = _prefer_chinese_prompt(_first_text(blocks, "no_text_prompt", limit=1200), NO_TEXT_CHINESE_CONSTRAINT)
    if negative:
        composed = f"{composed}\n\n负面约束：{negative}"
    return _append_sentence_once(composed, no_text)


def _module_text(blocks: dict[str, Any], data: dict[str, Any], key: str, *fallback_keys: str) -> str:
    return _first_text(blocks, key, *fallback_keys, limit=12000) or _first_text(data, key, *fallback_keys, limit=12000)


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "on", "命中", "是", "适用", "yes."}:
        return True
    if text in {"0", "false", "no", "n", "off", "未命中", "否", "不适用", "none"}:
        return False
    return None


def _has_image_analysis_hint(text: str, flag: str) -> bool:
    combined = str(text or "")
    lowered = combined.lower()
    return any(hint in combined or hint in lowered for hint in IMAGE_ANALYSIS_FLAG_HINTS.get(flag, ()))


def _normalize_image_type_flags(data: dict[str, Any], blocks: dict[str, Any]) -> dict[str, bool]:
    raw_flags = _as_dict(data.get("image_type_flags") or data.get("imageTypeFlags") or data.get("type_flags") or data.get("typeFlags"))
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    visual_summary = _first_text(data, "visual_summary", "summary", limit=2000)
    layout = _as_dict(data.get("layout"))
    generation_hints = _as_dict(data.get("generation_hints") or data.get("generationHints"))
    combined = " ".join(
        [
            image_kind,
            visual_summary,
            " ".join(str(value) for value in layout.values()),
            " ".join(str(value) for value in generation_hints.values()),
        ]
    )
    flags: dict[str, bool] = {}
    for flag in IMAGE_ANALYSIS_FLAG_HINTS:
        explicit = _boolish(raw_flags.get(flag))
        if explicit is None:
            explicit = _boolish(raw_flags.get(flag.replace("_", "")))
        flags[flag] = bool(explicit) if explicit is not None else _has_image_analysis_hint(combined, flag)

    # Web/UI screenshots are also layout designs, but not every layout design is a web page.
    if flags.get("web_design"):
        flags["layout_design"] = True
    if flags.get("cover_template"):
        flags["layout_design"] = True

    # If a legacy model omitted flags entirely, allow a non-empty specialized block to
    # rescue the obvious type. With explicit flags present, the flags win.
    if not raw_flags:
        for block_key, flag in IMAGE_ANALYSIS_SPECIALIZED_FLAGS.items():
            if _first_text(blocks, block_key, limit=400) and _has_image_analysis_hint(
                f"{combined} {_first_text(blocks, block_key, limit=1200)}",
                flag,
            ):
                flags[flag] = True
                if flag in {"cover_template", "web_design"}:
                    flags["layout_design"] = True
    return flags


def _compact_context_text(data: dict[str, Any]) -> str:
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    visual_summary = _first_text(data, "visual_summary", "summary", limit=600)
    return "，".join(part for part in [image_kind, visual_summary] if part)


REFERENCE_DEPENDENCY_MARKERS = (
    "参考图",
    "原图",
    "同款",
    "image1",
    "image 1",
    "以图生图",
    "图像编辑",
    "图片编辑",
    "改图",
    "基于图片",
    "基于这张图",
    "保留原",
)


def _has_reference_dependency(text: str) -> bool:
    cleaned = str(text or "")
    lowered = cleaned.lower()
    return any(marker in cleaned or marker in lowered for marker in REFERENCE_DEPENDENCY_MARKERS)


def _clean_standalone_context(text: str, limit: int = 900) -> str:
    cleaned = _clean_string(text, limit)
    if not cleaned:
        return ""
    replacements = (
        ("参考图同款", ""),
        ("参考图", "画面"),
        ("原图", "画面"),
        ("同款", ""),
        ("image1", ""),
        ("image 1", ""),
        ("以图生图", "文生图"),
        ("图像编辑", "图像生成"),
        ("图片编辑", "图像生成"),
        ("改图", "图像生成"),
        ("基于图片", "根据视觉描述"),
        ("基于这张图", "根据视觉描述"),
        ("保留原有", "采用"),
        ("保留原", "采用"),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[，、；：]\s*[，、；：]+", "，", cleaned)
    cleaned = re.sub(r"^[，、；：。.\s]+|[，、；：。.\s]+$", "", cleaned)
    return cleaned


def _standalone_context_text(data: dict[str, Any]) -> str:
    return _clean_standalone_context(_compact_context_text(data))


PIXEL_STYLE_MARKERS = (
    "像素",
    "pixel",
    "pixel art",
    "sprite",
    "8-bit",
    "8bit",
    "16-bit",
    "16bit",
    "低分辨率",
    "low-res",
    "low resolution",
    "方块",
    "块状",
    "阶梯",
    "锯齿",
    "tile",
    "tileset",
)


def _text_has_pixel_style(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in PIXEL_STYLE_MARKERS)


def _normalize_visual_style_regions(raw_style: dict[str, Any]) -> list[dict[str, str]]:
    raw_regions = (
        raw_style.get("style_regions")
        or raw_style.get("styleRegions")
        or raw_style.get("scoped_styles")
        or raw_style.get("scopedStyles")
        or raw_style.get("region_styles")
        or raw_style.get("regionStyles")
        or []
    )
    regions: list[dict[str, str]] = []
    for item in _as_list(raw_regions):
        if isinstance(item, dict):
            region = {
                "target": _clean_standalone_context(_first_text(item, "target", "area", "region", "scope", "applies_to", "appliesTo", limit=240), 240),
                "medium": _clean_standalone_context(_first_text(item, "medium", "style", limit=240), 240),
                "rendering": _clean_standalone_context(_first_text(item, "rendering", "render", limit=360), 360),
                "edge_quality": _clean_standalone_context(_first_text(item, "edge_quality", "edgeQuality", "edges", limit=240), 240),
                "texture": _clean_standalone_context(_first_text(item, "texture", "grain", limit=300), 300),
                "palette": _clean_standalone_context(_first_text(item, "palette", "color_palette", "colorPalette", limit=300), 300),
                "notes": _clean_standalone_context(_first_text(item, "notes", "description", "constraint", limit=420), 420),
            }
        else:
            region = {
                "target": "",
                "medium": "",
                "rendering": _clean_standalone_context(str(item), 360),
                "edge_quality": "",
                "texture": "",
                "palette": "",
                "notes": "",
            }
        if any(value for value in region.values()):
            regions.append(region)
    return regions[:10]


def _normalize_visual_style(data: dict[str, Any]) -> dict[str, Any]:
    raw_style = _as_dict(data.get("visual_style") or data.get("visualStyle") or data.get("style_profile") or data.get("styleProfile"))
    hints = _as_dict(data.get("generation_hints") or data.get("generationHints"))
    style_keywords = _as_list(raw_style.get("style_keywords") or raw_style.get("styleKeywords") or hints.get("style_keywords") or hints.get("styleKeywords"))
    normalized = {
        "medium": _clean_standalone_context(_first_text(raw_style, "medium", limit=300) or _first_text(hints, "medium", limit=300), 300),
        "rendering": _clean_standalone_context(_first_text(raw_style, "rendering", "render", limit=500) or _first_text(hints, "rendering", "render", limit=500), 500),
        "style_scope": _clean_standalone_context(_first_text(raw_style, "style_scope", "styleScope", "scope", "applies_to", "appliesTo", limit=500), 500),
        "subject_background_style": _clean_standalone_context(_first_text(raw_style, "subject_background_style", "subjectBackgroundStyle", "scene_style", "sceneStyle", limit=500), 500),
        "typography_style": _clean_standalone_context(_first_text(raw_style, "typography_style", "typographyStyle", "text_style", "textStyle", limit=500), 500),
        "text_style_is_pixelated": bool(_boolish(raw_style.get("text_style_is_pixelated") or raw_style.get("textStyleIsPixelated") or raw_style.get("pixelated_text") or raw_style.get("pixelatedText"))),
        "style_regions": _normalize_visual_style_regions(raw_style),
        "edge_quality": _clean_standalone_context(_first_text(raw_style, "edge_quality", "edgeQuality", "edges", limit=300), 300),
        "texture": _clean_standalone_context(_first_text(raw_style, "texture", "grain", limit=400), 400),
        "palette": _clean_standalone_context(_first_text(raw_style, "palette", "color_palette", "colorPalette", limit=500) or _first_text(hints, "palette", limit=500), 500),
        "resolution_language": _clean_standalone_context(_first_text(raw_style, "resolution_language", "resolutionLanguage", "resolution", limit=300), 300),
        "style_keywords": [
            _clean_standalone_context(str(item), 120)
            for item in style_keywords
            if str(item or "").strip()
        ][:12],
    }
    return normalized


def _visual_style_context_text(data: dict[str, Any]) -> str:
    style = _normalize_visual_style(data)
    # Keep this as the compact global style line only. Scope, subject/background,
    # typography, and region details are appended with labels by
    # _format_visual_style_prompt(); including them here duplicates the same
    # information and makes generated prompts repeat phrases such as “真实摄影”.
    parts = [
        style.get("medium"),
        style.get("rendering"),
        style.get("edge_quality"),
        style.get("texture"),
        style.get("palette"),
        style.get("resolution_language"),
        "，".join(style.get("style_keywords") or []),
    ]
    return "，".join(part for part in parts if part)


def _region_has_pixel_style(region: dict[str, str]) -> bool:
    positive_style_text = " ".join(
        str(region.get(key) or "")
        for key in ("medium", "rendering", "edge_quality", "texture", "palette")
    )
    return _text_has_pixel_style(positive_style_text)


def _has_pixel_style(data: dict[str, Any]) -> bool:
    style = _normalize_visual_style(data)
    base_context = " ".join(
        str(part or "")
        for part in [
            _first_text(data, "image_kind", "imageKind", limit=120),
            _first_text(data, "visual_summary", "summary", limit=1200),
            style.get("medium"),
            style.get("rendering"),
            style.get("style_scope"),
            style.get("subject_background_style"),
            style.get("edge_quality"),
            style.get("texture"),
            style.get("palette"),
            style.get("resolution_language"),
            " ".join(style.get("style_keywords") or []),
            " ".join(str(value) for value in _as_dict(data.get("generation_hints") or data.get("generationHints")).values()),
        ]
    )
    return _text_has_pixel_style(base_context) or any(_region_has_pixel_style(region) for region in style.get("style_regions") or [])


def _format_visual_style_regions(style: dict[str, Any]) -> str:
    lines: list[str] = []
    global_medium = str(style.get("medium") or "").strip()
    for region in style.get("style_regions") or []:
        region_medium = str(region.get("medium") or "").strip()
        parts = [
            "" if region_medium and region_medium == global_medium else region_medium,
            region.get("rendering"),
            region.get("edge_quality"),
            region.get("texture"),
            region.get("palette"),
            region.get("notes"),
        ]
        detail = "，".join(part for part in dict.fromkeys(parts) if part)
        target = region.get("target") or "局部区域"
        if not detail:
            continue
        if _region_has_pixel_style(region):
            detail = f"{detail}，该区域保留清晰方块像素、低分辨率像素网格、硬边无柔化抗锯齿、阶梯状斜线、有限色板、块状阴影和 sprite/tile-like 结构"
        lines.append(f"{target}：{detail}")
    return "；".join(lines)


def _format_visual_style_prompt(data: dict[str, Any]) -> str:
    style = _normalize_visual_style(data)
    style_context = _visual_style_context_text(data)
    region_text = _format_visual_style_regions(style)
    if not style_context and not region_text and not _has_pixel_style(data):
        return ""
    scope_parts = []
    if style.get("style_scope"):
        scope_parts.append(f"整体作用范围：{style['style_scope']}")
    if style.get("subject_background_style"):
        scope_parts.append(f"主体/背景：{style['subject_background_style']}")
    if region_text:
        scope_parts.append(f"区域风格：{region_text}")
    typography_style = style.get("typography_style") or ""
    if typography_style:
        scope_parts.append(f"文字/标题：{typography_style}")
    if _has_pixel_style(data) and not style.get("text_style_is_pixelated"):
        scope_parts.append("文字/标题按 text_regions 的字体风格独立处理，未明确为像素字体时不要强制像素化")
    elif style.get("text_style_is_pixelated"):
        scope_parts.append("文字也识别为像素/位图字体时才使用像素字体边缘")
    details = "；".join(part for part in scope_parts if part)
    if style_context and details:
        return f"媒介与渲染：{style_context}；{details}。"
    if details:
        return f"媒介与渲染：{details}。"
    return f"媒介与渲染：{style_context}。"


def _normalize_subjects(data: dict[str, Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(_as_list(data.get("subjects") or data.get("subject_details") or data.get("subjectDetails"))):
        if isinstance(item, dict):
            outfit_parts = [
                _clean_standalone_context(_first_text(item, "outfit", "styling", "clothing", "costume", "wardrobe", limit=500), 500),
                _clean_standalone_context(_first_text(item, "outfit_details", "outfitDetails", "clothing_details", "clothingDetails", "costume_details", "costumeDetails", limit=500), 500),
                _clean_standalone_context(_first_text(item, "top", "upper_body_clothing", "upperBodyClothing", "shirt", "outerwear", limit=240), 240),
                _clean_standalone_context(_first_text(item, "bottom", "lower_body_clothing", "lowerBodyClothing", "skirt", "pants", limit=240), 240),
                _clean_standalone_context(_first_text(item, "legwear", "hosiery", "tights", "pantyhose", "stockings", "socks", "袜装", "腿部覆盖物", limit=260), 260),
                _clean_standalone_context(_first_text(item, "footwear", "shoes", "boots", "鞋履", limit=220), 220),
            ]
            outfit = "，".join(part for part in dict.fromkeys(outfit_parts) if part)
            subject = {
                "name": _clean_standalone_context(_first_text(item, "name", "title", limit=120), 120) or f"主体{index + 1}",
                "role": _clean_standalone_context(_first_text(item, "role", limit=160), 160),
                "visual_traits": _clean_standalone_context(_first_text(item, "visual_traits", "visualTraits", "traits", limit=500), 500),
                "pose": _clean_standalone_context(_first_text(item, "pose", "action", "gesture", limit=500), 500),
                "expression": _clean_standalone_context(_first_text(item, "expression", "mood", limit=300), 300),
                "gaze": _clean_standalone_context(_first_text(item, "gaze", "view_direction", "viewDirection", limit=240), 240),
                "body_crop": _clean_standalone_context(_first_text(item, "body_crop", "bodyCrop", "crop", "framing", limit=300), 300),
                "outfit": _clean_standalone_context(outfit, 900),
                "makeup_hair": _clean_standalone_context(_first_text(item, "makeup_hair", "makeupHair", "hair_makeup", "hairMakeup", "hairstyle", "hair", "makeup", "妆发", limit=600), 600),
                "accessories": _clean_standalone_context(_first_text(item, "accessories", "props", "jewelry", "headwear", "hair_accessories", "hairAccessories", "配饰", limit=500), 500),
                "placement": _clean_standalone_context(_first_text(item, "placement", "position", limit=300), 300),
                "relationship": _clean_standalone_context(_first_text(item, "relationship", "relation", limit=500), 500),
            }
        else:
            subject = {
                "name": f"主体{index + 1}",
                "role": "",
                "visual_traits": _clean_standalone_context(str(item), 500),
                "pose": "",
                "expression": "",
                "gaze": "",
                "body_crop": "",
                "outfit": "",
                "makeup_hair": "",
                "accessories": "",
                "placement": "",
                "relationship": "",
            }
        if any(value for key, value in subject.items() if key != "name"):
            normalized.append(subject)
    return normalized[:6]


def _normalize_overlay_elements(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = (
        data.get("overlays")
        or data.get("overlay_elements")
        or data.get("overlayElements")
        or data.get("graphic_overlays")
        or data.get("graphicOverlays")
        or data.get("foreground_overlays")
        or data.get("foregroundOverlays")
        or []
    )
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(_as_list(raw)):
        overlay_id = f"O{index + 1}"
        if isinstance(item, dict):
            overlay = {
                "id": _clean_string(item.get("id") or overlay_id, 32) or overlay_id,
                "type": _clean_standalone_context(_first_text(item, "type", "kind", limit=120), 120),
                "position": _clean_standalone_context(_first_text(item, "position", "placement", limit=300), 300),
                "appearance": _clean_standalone_context(_first_text(item, "appearance", "visual_traits", "visualTraits", "description", limit=700), 700),
                "layering": _clean_standalone_context(_first_text(item, "layering", "layer", "z_index", "zIndex", limit=400), 400),
                "relationship": _clean_standalone_context(_first_text(item, "relationship", "relation", "covers", limit=500), 500),
            }
        else:
            overlay = {
                "id": overlay_id,
                "type": "",
                "position": "",
                "appearance": _clean_standalone_context(str(item), 700),
                "layering": "",
                "relationship": "",
            }
        if any(value for key, value in overlay.items() if key != "id"):
            normalized.append(overlay)
    return normalized[:8]


def _format_subject_detail_prompt(subjects: list[dict[str, str]]) -> str:
    detail_lines: list[str] = []
    for subject in subjects[:3]:
        parts = [
            subject.get("name") or subject.get("role"),
            subject.get("placement"),
            subject.get("visual_traits"),
            subject.get("pose"),
            subject.get("expression"),
            subject.get("gaze"),
            subject.get("body_crop"),
            subject.get("outfit"),
            subject.get("makeup_hair"),
            subject.get("accessories"),
            subject.get("relationship"),
        ]
        line = "，".join(part for part in dict.fromkeys(parts) if part)
        if line:
            detail_lines.append(line)
    if not detail_lines:
        return ""
    return "主体细节：" + "；".join(detail_lines) + "。"


def _format_overlay_detail_prompt(overlays: list[dict[str, str]]) -> str:
    detail_lines: list[str] = []
    for overlay in overlays[:5]:
        parts = [
            overlay.get("type"),
            overlay.get("position"),
            overlay.get("appearance"),
            overlay.get("layering"),
            overlay.get("relationship"),
        ]
        line = "，".join(part for part in dict.fromkeys(parts) if part)
        if line:
            detail_lines.append(line)
    if not detail_lines:
        return ""
    return "叠加视觉元素：" + "；".join(detail_lines) + "。"


def _main_prompt_detail_additions(data: dict[str, Any]) -> list[str]:
    return [
        detail
        for detail in [
            _format_visual_style_prompt(data),
            _format_subject_detail_prompt(_normalize_subjects(data)),
            _format_overlay_detail_prompt(_normalize_overlay_elements(data)),
        ]
        if detail
    ]


def _enhance_main_prompt_details(text: str, data: dict[str, Any]) -> str:
    cleaned = str(text or "").strip()
    additions = [detail for detail in _main_prompt_detail_additions(data) if detail and detail not in cleaned]
    if not additions:
        return cleaned
    if NO_TEXT_CHINESE_CONSTRAINT in cleaned:
        cleaned = cleaned.replace(NO_TEXT_CHINESE_CONSTRAINT, "").strip()
        cleaned = re.sub(r"[，、；：。.\s]+$", "", cleaned)
    enhanced = f"{cleaned}\n\n" + "\n".join(additions)
    return _append_sentence_once(enhanced, NO_TEXT_CHINESE_CONSTRAINT)


def _enhance_universal_style_details(text: str, data: dict[str, Any]) -> str:
    cleaned = str(text or "").strip()
    style_detail = _format_visual_style_prompt(data)
    if not style_detail or style_detail in cleaned:
        return cleaned
    return f"{style_detail}{cleaned}".strip()



BASE_IMAGE_PLACEHOLDER_SLOTS = (
    ("[SUBJECT_GROUP]", "主体组", "subject", "后续主体参考图融合或替换主体身份"),
    ("[POSE_OR_EXPRESSION]", "姿态 / 表情", "subject_attribute", "替换主体动作、表情和情绪状态"),
    ("[OUTFIT_STYLE]", "服装 / 造型", "subject_attribute", "替换主体穿搭、发型、妆容或造型风格"),
    ("[MAIN_OBJECT]", "主要物件 / 装饰", "object", "替换画面中的关键道具、装饰物或符号元素"),
    ("[BACKGROUND_SCENE]", "背景场景", "scene", "替换背景环境、空间和场景气质"),
)


def _has_placeholder_slot(text: str) -> bool:
    return bool(re.search(r"\[[A-Z][A-Z0-9_]{2,}\]", str(text or "")))


def _text_placeholder_for_region(region: dict[str, str], index: int = 0) -> tuple[str, str]:
    role = str(region.get("role") or "").lower()
    size = str(region.get("size") or "").lower()
    text = str(region.get("text") or "")
    combined = f"{role} {size} {text}".lower()
    if any(marker in combined for marker in ("主标题", "大标题", "标题", "title", "hero")):
        return "[MAIN_TITLE]", "主标题"
    if any(marker in combined for marker in ("副标题", "subtitle", "sub title")):
        return "[SUBTITLE]", "副标题"
    if any(marker in combined for marker in ("刊期", "日期", "时间", "期号", "编号", "vol", "date", "meta")):
        return "[DATE_OR_META]", "日期 / 元信息"
    if any(marker in combined for marker in ("按钮", "行动", "cta", "button")):
        return "[CTA_TEXT]", "按钮 / 行动文案"
    if any(marker in combined for marker in ("品牌", "logo", "商标")):
        return "[BRAND_OR_LOGO_TEXT]", "品牌 / 标识文字"
    if any(marker in combined for marker in ("价格", "金额", "price")):
        return "[PRICE_OR_VALUE]", "价格 / 数值"
    if any(marker in combined for marker in ("正文", "说明", "卖点", "栏目", "描述", "support", "body")):
        return "[SUPPORTING_TEXT]", "辅助说明"
    return f"[TEXT_SLOT_{index + 1}]", f"文字槽位 {index + 1}"


def _build_placeholder_slots(text_regions: list[dict[str, str]], image_type_flags: dict[str, bool]) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = [
        {
            "slot": slot,
            "label": label,
            "kind": kind,
            "description": description,
            "source_region_id": "",
        }
        for slot, label, kind, description in BASE_IMAGE_PLACEHOLDER_SLOTS
    ]
    if image_type_flags.get("table_card"):
        slots.extend([
            {"slot": "[CARD_TITLE]", "label": "卡片标题", "kind": "text", "description": "资料卡、产品卡或表格标题槽位", "source_region_id": ""},
            {"slot": "[DATA_GROUP]", "label": "数据组", "kind": "data", "description": "表格、图表或数值分组槽位", "source_region_id": ""},
            {"slot": "[KEY_VALUE_ITEMS]", "label": "键值信息", "kind": "data", "description": "多条字段和值的可替换信息槽位", "source_region_id": ""},
            {"slot": "[STATUS_TAG]", "label": "状态标签", "kind": "text", "description": "状态、分类或标签文本槽位", "source_region_id": ""},
        ])
    if image_type_flags.get("web_design"):
        slots.extend([
            {"slot": "[PAGE_TITLE]", "label": "页面标题", "kind": "text", "description": "网页 Hero 或页面主标题槽位", "source_region_id": ""},
            {"slot": "[NAV_ITEMS]", "label": "导航项", "kind": "text", "description": "导航栏项目槽位", "source_region_id": ""},
            {"slot": "[CONTENT_CARD_GROUP]", "label": "内容卡片组", "kind": "component", "description": "网页或 App 内容卡片组槽位", "source_region_id": ""},
        ])
    for index, region in enumerate(text_regions or []):
        slot, label = _text_placeholder_for_region(region, index)
        slots.append({
            "slot": slot,
            "label": label,
            "kind": "text",
            "description": f"{label}文字槽位，位置：{region.get('position') or '按版式关系'}",
            "source_region_id": str(region.get("id") or ""),
        })
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in slots:
        slot = item.get("slot") or ""
        region_id = item.get("source_region_id") or ""
        key = f"{slot}:{region_id}" if region_id else slot
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _format_placeholder_slots_markdown(slots: list[dict[str, str]]) -> str:
    lines = []
    for item in slots:
        region = f"；来源：{item.get('source_region_id')}" if item.get("source_region_id") else ""
        lines.append(f"{item.get('slot')}：{item.get('label')}；{item.get('description')}{region}")
    return "\n".join(lines).strip()


def _build_chinese_main_prompt(data: dict[str, Any], image_type_flags: dict[str, bool]) -> str:
    context = _standalone_context_text(data) or "具有明确视觉特征的图像"
    pieces = [f"生成一张独立文生图画面：{context}。"]
    if image_type_flags.get("layout_design"):
        pieces.append("采用清晰的版式层级、视觉重心、留白节奏、网格秩序、边距关系和整体信息密度。")
    if image_type_flags.get("cover_template"):
        pieces.append("强化封面式主视觉、主体焦点、杂志/社媒首图构图和醒目的编辑感。")
    if image_type_flags.get("table_card"):
        pieces.append("保持卡片、表格、图表或信息块的清晰分组、边界关系、视觉对齐和阅读顺序。")
    if image_type_flags.get("web_design"):
        pieces.append("呈现网页/UI 的导航结构、卡片系统、按钮形态、区块间距、组件层级和产品界面质感。")
    if not any(image_type_flags.values()):
        pieces.append("重点描述主体、场景、构图、色彩、光影、材质、空间层次和整体风格。")
    pieces.extend(_main_prompt_detail_additions(data))
    pieces.append(NO_TEXT_CHINESE_CONSTRAINT)
    return "".join(pieces)


def _build_chinese_universal_style_prompt(data: dict[str, Any]) -> str:
    context = _standalone_context_text(data)
    style_context = _format_visual_style_prompt(data)
    prefix = f"围绕“{context}”，" if context else ""
    style_clause = f"{style_context}" if style_context else "准确保留媒介类型、渲染方式、边缘质量、纹理颗粒、色板关系和分辨率语言。"
    return f"{prefix}提取可复用的整体视觉语言：{style_clause}统一画面气质、主体层级、构图节奏、色彩关系、光影方向、材质质感、空间深度和成片精致度，避免风格混杂和视觉目标偏移。"


def _build_chinese_specialized_prompt(block_key: str, data: dict[str, Any], image_type_flags: dict[str, bool], text_regions: list[dict[str, str]] | None = None) -> str:
    context = _standalone_context_text(data) or "该视觉类型"
    has_text = bool(text_regions)
    detected_slots = [slot for slot, _ in (_text_placeholder_for_region(region, index) for index, region in enumerate(text_regions or []))]
    common_slots = ["[MAIN_TITLE]", "[SUBTITLE]", "[SUPPORTING_TEXT]", *detected_slots]
    common_text_slots = "、".join(dict.fromkeys(common_slots))
    if block_key == "layout_prompt" and image_type_flags.get("layout_design"):
        return f"排版布局模板提示词：{context}；以 [SUBJECT_GROUP] 作为主视觉主体，使用 [POSE_OR_EXPRESSION] 控制动作/表情，[OUTFIT_STYLE] 控制造型，[MAIN_OBJECT] 放置关键道具或装饰，[BACKGROUND_SCENE] 控制背景场景；文字使用 {common_text_slots} 等槽位按原有信息层级排列，保持画面比例、主次视觉层级、留白、对齐、网格、边距、视觉动线和整体层级关系。"
    if block_key == "cover_template_prompt" and image_type_flags.get("cover_template"):
        text_clause = f"文字槽位使用 {common_text_slots}" if has_text else "可选文字槽位使用 [MAIN_TITLE]、[SUBTITLE]、[SUPPORTING_TEXT]"
        return f"封面模板提示词：一张{context}，画面主体为 [SUBJECT_GROUP]，表情/动作设为 [POSE_OR_EXPRESSION]，服装造型为 [OUTFIT_STYLE]；[SUBJECT_GROUP] 按封面主视觉位置裁切并形成明确焦点，[MAIN_OBJECT] 作为关键装饰或符号元素，[BACKGROUND_SCENE] 提供背景层次；{text_clause}，按标题、辅助信息、说明文字的视觉层级排列；保持封面边距、主体裁切、视觉重心、醒目编辑感和可复用首图结构。"
    if block_key == "table_card_layout_prompt" and image_type_flags.get("table_card"):
        return f"表格/卡片信息布局提示词：{context}；使用 [CARD_TITLE] 定义卡片或表格标题，[DATA_GROUP] 组织数据区块，[KEY_VALUE_ITEMS] 放置字段和值，[STATUS_TAG] 放置状态标签；如有主体图或产品图，用 [SUBJECT_GROUP] 或 [MAIN_OBJECT] 承载；保持卡片分组、表格列宽、图表区域、状态块、数据层级、间距、对齐和阅读顺序。"
    if block_key == "web_design_style_prompt" and image_type_flags.get("web_design"):
        return f"网页/UI 设计风格词：{context}；使用 [NAV_ITEMS] 表示导航内容，[PAGE_TITLE] 表示 Hero 或页面标题，[SUBJECT_GROUP] 表示主视觉人物/产品/插图，[CTA_TEXT] 表示按钮文案，[CONTENT_CARD_GROUP] 表示内容卡片组；描述导航、Hero 区、内容卡片、按钮、表单、数据区、组件圆角、阴影、边框、配色、字体气质和响应式界面层级。"
    return ""


def _build_image_specific_negative_prompt(data: dict[str, Any], image_type_flags: dict[str, bool]) -> str:
    context = _standalone_context_text(data) or "该画面类型"
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    text_markdown = _first_text(data, "text_markdown", "textMarkdown", "ocr_text", "ocrText", limit=400)
    pieces = [f"针对{context}，避免主体关系失衡、构图重心偏移、色彩气质不一致、光影方向混乱和媒介质感跑偏。"]
    if image_type_flags.get("layout_design"):
        pieces.append("避免版式层级错乱、留白节奏被破坏、图文占位失衡、网格对齐松散、视觉动线不清。")
    if image_type_flags.get("cover_template"):
        pieces.append("避免封面标题区失衡、主体裁切失去焦点、刊号/副标题占位杂乱、封面质感变成普通广告图。")
    if image_type_flags.get("table_card"):
        pieces.append("避免卡片边界混乱、表格列宽不齐、数据块拥挤、标签错位、图表比例失真和信息层级不清。")
    if image_type_flags.get("web_design"):
        pieces.append("避免导航、按钮、卡片、表单和内容区错位，避免廉价模板感、组件层级混乱和网页截图式噪点。")
    if _visual_style_context_text(data):
        pieces.append("避免把某一区域的媒介风格错误扩散到所有文字、Logo、标题、留白底版或整张版式；避免区域之间的渲染方式、边缘质量、纹理颗粒和色板关系互相污染。")
    if _has_pixel_style(data):
        pieces.append("对于识别为像素风的区域，避免转成真实摄影、柔和矢量插画、3D 渲染或水彩笔触；避免作用范围内出现平滑渐变、细腻真实材质、抗锯齿过强、像素边缘被磨平、块状结构丢失。")
    if any(keyword in image_kind for keyword in ("摄影", "人像", "照片")):
        pieces.append("避免肤色失真、五官变形、肢体异常、过度磨皮、背景抢主体和廉价影楼感。")
    if any(keyword in image_kind for keyword in ("产品", "商品", "包装")):
        pieces.append("避免产品比例失真、材质错误、反光脏乱、边缘变形、商标乱写和包装文字乱码。")
    if any(keyword in image_kind for keyword in ("插画", "海报", "信息图")):
        pieces.append("避免风格混杂、笔触质感不统一、装饰元素喧宾夺主和信息密度失控。")
    if text_markdown:
        pieces.append("避免自动生成未经确认的可读文字、日期、刊号、品牌名、二维码、价格或随机字母数字。")
    else:
        pieces.append("避免凭空添加可读文字、Logo、水印、二维码、价格、品牌标识或随机字符。")
    return "".join(pieces)


def _is_polluted_visual_prompt(text: str) -> bool:
    cleaned = str(text or "")
    if _has_reference_dependency(cleaned):
        return True
    hard_markers = ("OCR", "ocr", "保留图中文字", "编辑稿", "请按以下", "勾选", "除非用户", "text_markdown")
    if any(marker in cleaned for marker in hard_markers):
        return True
    soft_groups = (
        ("文字", "占位"),
        ("文字", "可读"),
        ("文字", "生成"),
        ("字母", "数字"),
        ("Logo", "水印"),
        ("二维码", "价格"),
    )
    return any(all(marker in cleaned for marker in group) for group in soft_groups)


def _clean_ocr_markdown(text: str) -> str:
    cleaned = _strip_code_fences(str(text or "").strip())
    lines = cleaned.splitlines()
    if lines and lines[0].strip().lower() in {"markdown", "md"}:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _normalize_text_regions(data: dict[str, Any], text_markdown: str) -> list[dict[str, str]]:
    raw_regions = data.get("text_regions") or data.get("textRegions") or data.get("ocr_regions") or data.get("ocrRegions")
    regions: list[dict[str, str]] = []
    if isinstance(raw_regions, list):
        for index, item in enumerate(raw_regions):
            if not isinstance(item, dict):
                continue
            text = _clean_string(item.get("text") or item.get("original_text") or item.get("originalText"), 1200)
            if not text:
                continue
            region_id = _clean_string(item.get("id") or item.get("slot") or f"T{len(regions) + 1}", 16).upper()
            if not re.match(r"^T\d+$", region_id):
                region_id = f"T{len(regions) + 1}"
            regions.append({
                "id": region_id,
                "text": text,
                "role": _clean_string(item.get("role") or item.get("label") or "文字", 80),
                "position": _clean_string(item.get("position") or item.get("placement") or "", 160),
                "anchor": _clean_string(item.get("anchor") or "", 80),
                "alignment": _clean_string(item.get("alignment") or item.get("align") or "", 40),
                "size": _clean_string(item.get("size") or item.get("scale") or item.get("level") or "", 40),
                "style": _clean_string(item.get("style") or item.get("font_style") or item.get("fontStyle") or "", 240),
            })
    if regions:
        return regions

    cleaned = _clean_ocr_markdown(text_markdown)
    if not cleaned:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in cleaned.splitlines() if line.strip()]
    fallback_positions = ("顶部区域", "上半部分", "画面中部", "下半部分", "底部区域")
    for index, block in enumerate(blocks):
        regions.append({
            "id": f"T{index + 1}",
            "text": block,
            "role": "文字",
            "position": fallback_positions[min(index, len(fallback_positions) - 1)],
            "anchor": "",
            "alignment": "",
            "size": "",
            "style": "",
        })
    return regions


def _format_text_regions_markdown(regions: list[dict[str, str]], fallback_text: str = "") -> str:
    if not regions:
        return _clean_ocr_markdown(fallback_text)
    blocks = []
    for region in regions:
        meta = []
        if region.get("role"):
            meta.append(region["role"])
        if region.get("position"):
            meta.append(f"位置：{region['position']}")
        if region.get("alignment"):
            meta.append(f"对齐：{region['alignment']}")
        if region.get("size"):
            meta.append(f"字号：{region['size']}")
        if region.get("style"):
            meta.append(f"样式：{region['style']}")
        header = f"{region.get('id') or 'T?'}｜" + "｜".join(meta)
        blocks.append(f"{header}\n{region.get('text') or ''}".strip())
    return "\n\n".join(blocks).strip()


def _prefer_chinese_prompt(text: str, fallback: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned and _has_han(cleaned):
        return cleaned
    return fallback


def _prefer_standalone_chinese_prompt(text: str, fallback: str, *, reject_tool_words: bool = False) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or not _has_han(cleaned):
        return fallback
    if _has_reference_dependency(cleaned):
        return fallback
    if reject_tool_words and _is_polluted_visual_prompt(cleaned):
        return fallback
    return cleaned


def _normalize_prompt_image_analysis(data: dict[str, Any], images: list[dict[str, Any]], provider_id: str, model: str, reasoning_effort: str, started: float) -> dict[str, Any]:
    blocks = _as_dict(data.get("prompt_blocks") or data.get("promptBlocks"))
    image_type_flags = _normalize_image_type_flags(data, blocks)
    for block_key, flag in IMAGE_ANALYSIS_SPECIALIZED_FLAGS.items():
        if not image_type_flags.get(flag):
            blocks[block_key] = ""
    raw_main = _first_text(blocks, "main_prompt_no_text", "main_prompt", "prompt", "完整提示词", limit=12000)
    if not raw_main or not _has_han(raw_main) or _is_polluted_visual_prompt(raw_main):
        blocks["main_prompt_no_text"] = _build_chinese_main_prompt(data, image_type_flags)
    visual_style = _normalize_visual_style(data)
    subjects = _normalize_subjects(data)
    overlays = _normalize_overlay_elements(data)
    main_prompt = _enhance_main_prompt_details(_compose_no_text_prompt(blocks, data), data)
    raw_text_markdown = _first_text(data, "text_markdown", "textMarkdown", "ocr_text", "ocrText", limit=12000)
    text_regions = _normalize_text_regions(data, raw_text_markdown)
    text_markdown = _format_text_regions_markdown(text_regions, raw_text_markdown)
    placeholder_slots = _build_placeholder_slots(text_regions, image_type_flags)
    placeholder_slots_text = _format_placeholder_slots_markdown(placeholder_slots)
    analysis_id = f"image_analysis_{int(time.time())}_{os.urandom(3).hex()}"
    now = int(time.time())
    universal_style_prompt = _enhance_universal_style_details(
        _prefer_standalone_chinese_prompt(
            _module_text(blocks, data, "universal_style_prompt", "style_prompt"),
            _build_chinese_universal_style_prompt(data),
        ),
        data,
    )
    negative_prompt = _prefer_standalone_chinese_prompt(
        _module_text(blocks, data, "negative_prompt", "negative"),
        _build_image_specific_negative_prompt({**data, "text_markdown": text_markdown}, image_type_flags),
    )
    context_negative = _build_image_specific_negative_prompt({**data, "text_markdown": text_markdown}, image_type_flags)
    if context_negative and context_negative not in negative_prompt:
        generic_markers = ("低质量", "low quality", "blurry", "bad anatomy", "watermark", "logo")
        if len(negative_prompt) < 80 or any(marker in negative_prompt.lower() for marker in generic_markers):
            negative_prompt = context_negative
    def slot_prompt(block_key: str, *fallback_keys: str) -> str:
        raw = _module_text(blocks, data, block_key, *fallback_keys)
        fallback = _build_chinese_specialized_prompt(block_key, data, image_type_flags, text_regions)
        if raw and not _has_placeholder_slot(raw):
            raw = ""
        return _prefer_standalone_chinese_prompt(raw, fallback, reject_tool_words=True)

    specialized_prompts = {
        "layout_prompt": slot_prompt("layout_prompt", "composition_prompt"),
        "cover_template_prompt": slot_prompt("cover_template_prompt", "template_prompt"),
        "table_card_layout_prompt": slot_prompt("table_card_layout_prompt"),
        "web_design_style_prompt": slot_prompt("web_design_style_prompt"),
    }
    analysis = {
        "schema_version": "image_prompt_analysis_v1",
        "analysis_id": analysis_id,
        "image_kind": _clean_standalone_context(_first_text(data, "image_kind", "imageKind", limit=80) or "图片分析"),
        "image_type_flags": image_type_flags,
        "type_rationale": _as_dict(data.get("type_rationale") or data.get("typeRationale")),
        "visual_summary": _clean_standalone_context(_first_text(data, "visual_summary", "summary", limit=2000), 2000),
        "visual_style": visual_style,
        "prompt_blocks": {
            "main_prompt_no_text": main_prompt,
            "universal_style_prompt": universal_style_prompt,
            "layout_prompt": specialized_prompts["layout_prompt"],
            "negative_prompt": negative_prompt,
            "cover_template_prompt": specialized_prompts["cover_template_prompt"],
            "table_card_layout_prompt": specialized_prompts["table_card_layout_prompt"],
            "web_design_style_prompt": specialized_prompts["web_design_style_prompt"],
            "no_text_prompt": _prefer_chinese_prompt(_module_text(blocks, data, "no_text_prompt"), NO_TEXT_CHINESE_CONSTRAINT),
        },
        "text_markdown": text_markdown,
        "text_regions": text_regions,
        "placeholder_slots": placeholder_slots,
        "layout": _as_dict(data.get("layout")),
        "subjects": subjects,
        "overlays": overlays,
        "generation_hints": _as_dict(data.get("generation_hints") or data.get("generationHints")),
        "confidence": _as_dict(data.get("confidence")),
        "warnings": [str(item) for item in _as_list(data.get("warnings")) if str(item).strip()],
        "input_images": [
            {key: value for key, value in image.items() if key != "image_url"}
            for image in images
        ],
    }
    if not analysis["warnings"]:
        analysis["warnings"] = ["主候选默认不生成可读文字；如需生成图片中文字，请在展开面板内编辑 OCR 后打开“保留图中文字”。"]

    candidate = {
        "id": f"image_analysis_main_{now}",
        "kind": "image_analysis_main",
        "label": "主候选提示词",
        "badge": "默认不含文字",
        "text": main_prompt,
        "base_text": main_prompt,
        "language": "mixed",
        "analysis_id": analysis_id,
        "created_at": now,
    }
    module_specs = [
        ("placeholder_slots", "占位符槽位", placeholder_slots_text, "summary", False),
        ("universal_style_prompt", "通用风格提示词", analysis["prompt_blocks"]["universal_style_prompt"], "prompt", False),
        ("layout_prompt", "排版布局提示词", analysis["prompt_blocks"]["layout_prompt"], "prompt", False),
        ("negative_prompt", "负面提示词", analysis["prompt_blocks"]["negative_prompt"], "prompt", False),
        ("cover_template_prompt", "封面模板提示词", analysis["prompt_blocks"]["cover_template_prompt"], "prompt", False),
        ("table_card_layout_prompt", "表格/卡片信息布局提示词", analysis["prompt_blocks"]["table_card_layout_prompt"], "prompt", False),
        ("web_design_style_prompt", "网页设计风格词", analysis["prompt_blocks"]["web_design_style_prompt"], "prompt", False),
    ]
    modules = [
        {"id": mid, "title": title, "text": text, "kind": kind, "editable": editable}
        for mid, title, text, kind, editable in module_specs
        if text
    ]
    modules.append({
        "id": "full_json",
        "title": "完整 JSON",
        "kind": "json",
        "text": json.dumps(analysis, ensure_ascii=False, indent=2),
        "json": analysis,
    })
    return {
        "ok": True,
        "analysis_id": analysis_id,
        "analysis": analysis,
        "modules": modules,
        "candidate": candidate,
        "candidates": [candidate],
        "fusion": {
            "subject_reference": None,
            "reserved_images": [
                {key: value for key, value in image.items() if key != "image_url"}
                for image in images[1:]
            ],
            "options": {
                "keepOriginalHair": False,
                "keepOriginalPose": False,
                "keepTextLayers": False,
            },
        },
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
    }


def analyze_prompt_image(message: str, images: list[Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze reference images into prompt candidates and structured modules."""
    options = options or {}
    normalized_images = _normalize_image_analysis_inputs(images if isinstance(images, list) else [])
    if not normalized_images:
        raise ValueError("缺少要分析的图片")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    requested_model = str(options.get("model") or config.get("model") or "").strip()
    original_provider_id = provider_id
    provider_id, model, fallback_warning = _select_prompt_provider_model_with_pool_fallback(
        provider_id,
        requested_model,
        "图片分析",
    )
    requested_effort = str(options.get("reasoning_effort") or options.get("reasoningEffort") or "medium").strip().lower()
    reasoning_effort = requested_effort if requested_effort in GPT_REASONING_EFFORTS else "medium"
    prompt = _build_image_analysis_user_prompt(str(message or "").strip(), normalized_images)
    started = time.time()
    image_urls = [normalized_images[0]["image_url"]]

    def parse_analysis(raw_text: str) -> dict[str, Any]:
        if not raw_text:
            raise RuntimeError("图片分析模型没有返回内容")
        data = json.loads(_extract_first_json_block(raw_text))
        if not isinstance(data, dict) or not any(
            data.get(key)
            for key in ("image_kind", "imageKind", "visual_summary", "summary", "visual_style", "prompt_blocks", "subjects", "layout")
        ):
            raise ValueError("图片分析模型返回的 JSON 结构不完整")
        return _normalize_prompt_image_analysis(data, normalized_images, provider_id, model, reasoning_effort, started)

    if provider_id == "chatgpt_pool":
        raw_text, model = _chatgpt_pool_image_json_reply(prompt, IMAGE_PROMPT_ANALYSIS_SYSTEM, image_urls)
        reasoning_effort = ""
        result = parse_analysis(raw_text)
    else:
        try:
            raw_text = _call_prompt_provider_image_json(
                provider_id,
                prompt,
                IMAGE_PROMPT_ANALYSIS_SYSTEM,
                image_urls,
                model,
                reasoning_effort,
            )
            result = parse_analysis(raw_text)
        except Exception as exc:
            if not _should_fallback_prompt_chat_to_pool(original_provider_id, exc):
                raise
            raw_text, fallback_model, fallback_warning = _fallback_prompt_image_analysis_to_pool(
                prompt,
                IMAGE_PROMPT_ANALYSIS_SYSTEM,
                image_urls,
                exc,
            )
            provider_id = "chatgpt_pool"
            model = fallback_model
            reasoning_effort = ""
            result = parse_analysis(raw_text)
    if fallback_warning:
        result["warning"] = fallback_warning
        result["fallback"] = "chatgpt_pool_multimodal_chat"
    return result


def _join_prompt_block_parts(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if isinstance(value, dict):
            candidates = value.values()
        elif isinstance(value, (list, tuple, set)):
            candidates = value
        else:
            candidates = [value]
        for candidate in candidates:
            text = _clean_string(candidate, 5000)
            if text and text not in parts:
                parts.append(text)
    return "；".join(parts)


def _prompt_block_has_markers(text: str, chinese: tuple[str, ...] = (), english: tuple[str, ...] = ()) -> bool:
    normalized = str(text or "").lower()
    if any(marker in normalized for marker in chinese):
        return True
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(marker.lower())}(?![a-z0-9])", normalized)
        for marker in english
    )


def _prompt_block_has_human_evidence(text: str) -> bool:
    return _prompt_block_has_markers(
        text,
        ("人物", "人像", "肖像", "女性", "男性", "女孩", "男孩", "女士", "男士", "模特", "少女", "少年"),
        ("person", "portrait", "human", "woman", "man", "girl", "boy", "lady", "gentleman", "people", "adult", "child", "teenager", "businesswoman", "businessman"),
    )


def _infer_prompt_block_primary_type(analysis: dict[str, Any], requested: str = "") -> str:
    clean_requested = str(requested or "").strip()
    if clean_requested in PROMPT_BLOCK_PRIMARY_TYPES:
        return clean_requested
    flags = _as_dict(analysis.get("image_type_flags"))
    kind = _clean_string(analysis.get("image_kind"), 120).lower()
    summary = _clean_string(analysis.get("visual_summary"), 600).lower()
    subjects = [item for item in _as_list(analysis.get("subjects")) if isinstance(item, dict)]
    subject_evidence = " ".join(
        _clean_string(subject.get(key), 500).lower()
        for subject in subjects
        for key in ("name", "role", "visual_traits", "outfit", "makeup_hair", "accessories")
        if subject.get(key)
    )
    primary_evidence = f"{kind} {summary}"
    combined = f"{primary_evidence} {subject_evidence}"

    if flags.get("web_design") or _prompt_block_has_markers(combined, ("网页", "网站界面", "应用界面"), ("web design", "landing page", "app interface", "website")):
        return "social"
    if flags.get("cover_template") or _prompt_block_has_markers(combined, ("海报", "封面", "主视觉"), ("poster", "cover", "key visual")):
        return "poster"
    if flags.get("table_card") or _prompt_block_has_markers(combined, ("信息图", "图表", "卡片"), ("infographic", "data chart")):
        return "infographic"
    if _prompt_block_has_markers(combined, ("分镜", "镜头脚本"), ("storyboard", "shot list")):
        return "storyboard"
    if _prompt_block_has_markers(combined, ("无缝图案", "连续纹样", "平铺纹理"), ("seamless pattern", "repeat pattern")):
        return "pattern"
    if _prompt_block_has_markers(combined, ("3d视觉", "3d 视觉", "三维渲染", "立体渲染"), ("3d render", "cgi render")):
        return "three_d"
    if _prompt_block_has_markers(combined, ("服装设计", "时装", "穿搭", "秀场"), ("lookbook", "fashion editorial", "garment design")):
        return "fashion"

    category_markers = (
        ("food", ("美食", "食物", "菜品", "餐饮", "料理", "甜点", "蛋糕"), ("food", "cuisine", "dish", "meal", "dessert", "cake", "cupcake", "hot dog")),
        ("animal", ("动物", "宠物", "猫", "狗", "犬"), ("wildlife", "pet portrait", "dog", "cat", "retriever")),
        ("interior", ("室内", "客厅", "卧室"), ("interior", "living room", "bedroom")),
        ("architecture", ("建筑", "立面", "住宅", "房屋", "大楼"), ("architecture", "facade", "building", "house", "residence")),
        ("product", ("产品", "商品", "包装", "电商", "瓶", "罐", "盒", "杯", "腕表", "手表", "手机", "耳机", "香水"), ("product", "e-commerce", "bottle", "package", "packaging", "cup", "mug", "watch", "phone", "headphone", "headphones", "perfume", "cosmetic", "cosmetics", "device")),
        ("landscape", ("风景", "自然景观", "山川", "海岸"), ("landscape", "scenery")),
        ("character", ("角色设定", "角色设计", "人物设定"), ("character design", "character sheet")),
        ("scene_concept", ("场景概念", "环境概念", "世界观场景"), ("concept environment", "environment design")),
        ("social", ("社交媒体", "社媒", "小红书"), ("social media", "instagram post")),
        ("illustration", ("插画", "漫画", "绘本"), ("illustration", "comic")),
        ("portrait", ("人像", "肖像", "人物写真"), ("portrait", "headshot")),
    )
    for primary_type, chinese, english in category_markers:
        if _prompt_block_has_markers(primary_evidence, chinese, english):
            return primary_type

    for primary_type, chinese, english in category_markers[:4]:
        if _prompt_block_has_markers(subject_evidence, chinese, english):
            return primary_type
    if _prompt_block_has_human_evidence(subject_evidence):
        return "portrait"
    for primary_type, chinese, english in category_markers[4:]:
        if _prompt_block_has_markers(subject_evidence, chinese, english):
            return primary_type
    return "illustration"


def _prompt_blocks_from_image_analysis(
    result: dict[str, Any],
    primary_type: str = "",
    split_rule: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    analysis = _as_dict(result.get("analysis"))
    resolved_type = _infer_prompt_block_primary_type(analysis, primary_type)
    candidates: list[dict[str, Any]] = []

    def add(name: str, module_type: str, content: Any, tags: list[str] | None = None) -> None:
        clean_content = _clean_string(content, 12000)
        if not clean_content:
            return
        candidates.append({
            "name": name,
            "module_type": module_type,
            "content": clean_content,
            "compact_content": clean_content[:240] if len(clean_content) > 240 else clean_content,
            "english_content": "",
            "applicable_types": [resolved_type],
            "tags": ["图片解析", *(tags or [])][:12],
        })

    subjects = [item for item in _as_list(analysis.get("subjects")) if isinstance(item, dict)]
    subject_identity = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("name"), subject.get("role"), subject.get("relationship"))
        for subject in subjects
    ])
    appearance = _join_prompt_block_parts(*[subject.get("visual_traits") for subject in subjects])
    pose = _join_prompt_block_parts(*[subject.get("pose") for subject in subjects])
    expression = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("expression"), subject.get("gaze")) for subject in subjects
    ])
    clothing = _join_prompt_block_parts(*[subject.get("outfit") for subject in subjects])
    makeup_hair = _join_prompt_block_parts(*[subject.get("makeup_hair") for subject in subjects])
    accessories = _join_prompt_block_parts(*[subject.get("accessories") for subject in subjects])
    relationship = _join_prompt_block_parts(*[subject.get("relationship") for subject in subjects])
    subject_placement = _join_prompt_block_parts(*[
        _join_prompt_block_parts(subject.get("placement"), subject.get("body_crop")) for subject in subjects
    ])

    visual_summary = _clean_string(analysis.get("visual_summary"), 2000)
    layout = _as_dict(analysis.get("layout"))
    composition = _join_prompt_block_parts(layout, subject_placement)
    hints = _as_dict(analysis.get("generation_hints"))
    camera = _join_prompt_block_parts(hints.get("camera"), hints.get("aspect_ratio"))
    lighting = _join_prompt_block_parts(hints.get("lighting"))
    visual_style = _as_dict(analysis.get("visual_style"))
    color = _join_prompt_block_parts(hints.get("palette"), visual_style.get("palette"))
    prompt_blocks = _as_dict(analysis.get("prompt_blocks"))
    main_prompt = _join_prompt_block_parts(prompt_blocks.get("main_prompt_no_text"))
    style = _join_prompt_block_parts(
        prompt_blocks.get("universal_style_prompt"),
        visual_style.get("medium"), visual_style.get("rendering"), visual_style.get("style_scope"),
    )
    material = _join_prompt_block_parts(
        visual_style.get("texture"), visual_style.get("edge_quality"),
        visual_style.get("resolution_language"), hints.get("rendering"),
    )
    constraints = _join_prompt_block_parts(prompt_blocks.get("negative_prompt"))
    text_regions = [item for item in _as_list(analysis.get("text_regions")) if isinstance(item, dict)]
    text_evidence = _join_prompt_block_parts(*[
        _join_prompt_block_parts(item.get("text"), item.get("role"), item.get("position"), item.get("style"))
        for item in text_regions
    ])
    overlays = [item for item in _as_list(analysis.get("overlays")) if isinstance(item, dict)]
    overlay_evidence = _join_prompt_block_parts(*[
        _join_prompt_block_parts(item.get("type"), item.get("position"), item.get("appearance"), item.get("layering"), item.get("relationship"))
        for item in overlays
    ])

    subject_evidence = _join_prompt_block_parts(subject_identity, appearance)
    has_human_subject = _prompt_block_has_human_evidence(subject_evidence)
    if subjects and (has_human_subject or resolved_type in {"portrait", "character", "fashion"}):
        add("主体身份", "identity", subject_identity)
        add("外貌特征", "appearance", appearance)
        add("动作姿态", "pose", pose)
        add("表情视线", "expression", expression)
        add("服装造型", "clothing", clothing)
        add("妆发细节", "makeup_hair", makeup_hair)
        add("配饰道具", "accessories", accessories)
    elif subjects:
        add("主体特征", "subject", _join_prompt_block_parts(subject_identity, appearance, main_prompt, visual_summary))

    specific_blocks: dict[str, list[tuple[str, str, Any]]] = {
        "portrait": [
            ("人体约束", "anatomy_constraints", constraints),
        ],
        "landscape": [
            ("地貌环境", "landform", visual_summary),
            ("大气效果", "atmosphere", _join_prompt_block_parts(visual_summary, lighting)),
            ("前中后景", "depth", composition),
        ],
        "product": [
            ("商品结构", "product_structure", _join_prompt_block_parts(appearance, main_prompt, visual_summary)),
            ("材质工艺", "craft", material),
            ("核心卖点", "selling_points", visual_summary),
            ("商品摆放", "placement", composition),
            ("商业布光", "commercial_lighting", lighting),
            ("品牌限制", "brand_constraints", _join_prompt_block_parts(text_evidence, color)),
        ],
        "food": [
            ("食材状态", "ingredients", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("摆盘方式", "plating", composition),
            ("食物质感", "food_texture", material),
            ("温度气息", "steam", _join_prompt_block_parts(visual_summary, lighting)),
        ],
        "architecture": [
            ("建筑风格", "architectural_style", style),
            ("建筑体量", "massing", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("立面细节", "facade", _join_prompt_block_parts(appearance, material)),
            ("场地环境", "site", _join_prompt_block_parts(visual_summary, composition)),
        ],
        "interior": [
            ("空间布局", "space_layout", composition),
            ("家具陈设", "furniture", visual_summary),
            ("空间材质", "surface_materials", material),
            ("软装细节", "soft_furnishing", _join_prompt_block_parts(visual_summary, color)),
        ],
        "character": [
            ("角色身份", "character_identity", subject_identity),
            ("世界观", "worldbuilding", _join_prompt_block_parts(visual_summary, style)),
            ("角色轮廓", "silhouette", appearance),
            ("装备道具", "equipment", accessories),
            ("设定视图", "turnaround", composition),
        ],
        "scene_concept": [
            ("世界观", "worldbuilding", _join_prompt_block_parts(visual_summary, style)),
            ("地理环境", "geography", visual_summary),
            ("文明痕迹", "civilization", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("环境叙事", "environment_story", overlay_evidence),
            ("尺度关系", "scale", composition),
        ],
        "animal": [
            ("物种品种", "species", _join_prompt_block_parts(subject_identity, visual_summary)),
            ("毛发羽毛", "fur", _join_prompt_block_parts(appearance, material)),
            ("动作神态", "animal_action", _join_prompt_block_parts(pose, expression)),
            ("栖息环境", "habitat", visual_summary),
        ],
        "fashion": [
            ("服装版型", "garment_shape", clothing),
            ("面料质感", "fabric", _join_prompt_block_parts(clothing, material)),
            ("服装工艺", "craft", material),
            ("整体搭配", "styling", _join_prompt_block_parts(clothing, accessories, color)),
            ("展示姿态", "lookbook_pose", _join_prompt_block_parts(pose, composition)),
        ],
        "storyboard": [
            ("景别", "shot_size", composition),
            ("机位", "camera_position", camera),
            ("人物调度", "blocking", _join_prompt_block_parts(subject_placement, relationship)),
            ("镜头动作", "action", pose),
            ("运镜", "camera_motion", camera),
            ("连续性", "continuity", constraints),
        ],
        "illustration": [
            ("叙事瞬间", "story_moment", visual_summary),
            ("角色关系", "character_relation", _join_prompt_block_parts(subject_identity, relationship)),
            ("线条表现", "linework", style),
            ("上色方式", "rendering", _join_prompt_block_parts(style, material)),
            ("对白区域", "speech_area", _join_prompt_block_parts(text_evidence, composition)),
        ],
        "poster": [
            ("核心视觉", "key_visual", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("文案", "copy", text_evidence),
            ("信息层级", "information_hierarchy", _join_prompt_block_parts(layout, text_evidence)),
            ("版式", "layout", composition),
            ("文字区域", "text_region", text_evidence),
            ("品牌色", "brand_color", color),
            ("Logo 区域", "logo_region", overlay_evidence),
        ],
        "social": [
            ("视觉钩子", "visual_hook", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("标题区域", "headline", text_evidence),
            ("品牌系统", "brand_system", _join_prompt_block_parts(style, color)),
            ("平台安全区", "safe_area", composition),
        ],
        "infographic": [
            ("信息范围", "data_scope", _join_prompt_block_parts(visual_summary, text_evidence)),
            ("信息结构", "information_structure", composition),
            ("图形关系", "diagram", _join_prompt_block_parts(overlay_evidence, layout)),
            ("标注文字", "annotation", text_evidence),
            ("可读性", "readability", _join_prompt_block_parts(layout, constraints)),
        ],
        "three_d": [
            ("建模形态", "model_shape", _join_prompt_block_parts(appearance, main_prompt, visual_summary)),
            ("材质着色", "shader", material),
            ("渲染表现", "render_engine", style),
            ("摄影棚", "studio", _join_prompt_block_parts(visual_summary, lighting)),
        ],
        "pattern": [
            ("图案元素", "motif", _join_prompt_block_parts(main_prompt, visual_summary)),
            ("重复规则", "repeat", _join_prompt_block_parts(layout, composition)),
            ("元素密度", "density", composition),
            ("接缝要求", "seam", constraints),
        ],
    }
    for name, module_type, content in specific_blocks.get(resolved_type, []):
        add(name, module_type, content, ["拆分规则"])

    add("场景主题", "scene", visual_summary)
    add("构图布局", "composition", composition)
    add("镜头视角", "camera", camera)
    add("光线氛围", "lighting", lighting)
    add("色彩方案", "color", color)
    add("视觉风格", "style", style)
    add("材质渲染", "material", material)
    add("负面约束", "constraints", constraints)
    if overlays:
        add("叠加元素", "custom", overlay_evidence)
    if not candidates:
        raise ValueError("图片分析完成，但没有得到可保存的素材块")
    return _normalize_extracted_prompt_blocks({"blocks": candidates}, resolved_type, split_rule), resolved_type


def extract_reusable_prompt_blocks_from_image(
    message: str,
    images: list[Any],
    primary_type: str = "",
    options: dict[str, Any] | None = None,
    split_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze an uploaded image and convert the visual evidence into reusable blocks."""
    result = analyze_prompt_image(message, images, options)
    blocks, resolved_type = _prompt_blocks_from_image_analysis(result, primary_type, split_rule)
    response = {
        "ok": True,
        "mode": "image",
        "blocks": blocks,
        "primary_type": resolved_type,
        "analysis_id": result.get("analysis_id"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "reasoning_effort": result.get("reasoning_effort"),
        "latency_seconds": result.get("latency_seconds"),
        **({"warning": result.get("warning"), "fallback": result.get("fallback")} if result.get("warning") else {}),
    }
    rule_snapshot = _split_rule_snapshot(split_rule)
    if rule_snapshot:
        response["split_rule"] = rule_snapshot
    return response


def _fallback_style_extract(text: str, message: str, candidate: str) -> dict[str, Any]:
    source = " ".join(part for part in [message, candidate, text] if str(part or "").strip())
    compact = " ".join(str(source or "自定义风格").split())[:420]
    name = "自定义风格"
    for marker, label in [
        ("电影", "电影感"),
        ("产品", "产品感"),
        ("敦煌", "敦煌"),
        ("皮影", "皮影戏"),
        ("写实", "超写实"),
        ("冷调", "冷调克制"),
        ("广告", "去广告感"),
    ]:
        if marker in source:
            name = label
            break
    prompt_style = compact or "保持主体清晰，强化构图、光影、材质和整体情绪，避免无关元素发散。"
    return {
        "name": name,
        "description": "从当前文本节点和提示词助手讨论中提取的风格预设。",
        "positive_style": prompt_style,
        "avoid": "避免改变主体身份、过度商业广告感、无关装饰堆砌、画面跑题。",
        "best_for": "文本节点提示词复用",
        "prompt_style": prompt_style,
        "tags": [],
    }


def extract_style_preset(text: str, message: str = "", options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract a reusable style preset from text-node context."""
    options = options or {}
    current_text = str(text or "").strip()
    user_message = str(message or "").strip()
    candidate = str(options.get("candidate") or "").strip()
    if not current_text and not user_message and not candidate:
        raise ValueError("缺少可提取风格的内容")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    model = _choose_model(provider_id, str(options.get("model") or config.get("model") or "").strip())
    reasoning_effort = str(options.get("reasoning_effort") or "low").strip().lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = "low"
    history = options.get("history") if isinstance(options.get("history"), list) else []
    history_lines = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = "用户" if str(item.get("role") or "") == "user" else "助手"
        content = str(item.get("text") or item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content[:1200]}")

    prompt = "\n".join(part for part in [
        "请提取一个可复用的文本节点风格预设，字段必须包含：name, description, positive_style, avoid, best_for, prompt_style, tags。",
        "prompt_style 必须是可直接追加到提示词后的风格提示片段，避免包含具体角色名、具体任务、节点或模型参数。",
        f"文本节点内容：\n<<<\n{current_text}\n>>>" if current_text else "",
        f"用户意图：\n{user_message}" if user_message else "",
        f"候选提示词：\n<<<\n{candidate}\n>>>" if candidate else "",
        "最近聊天：\n" + "\n".join(history_lines) if history_lines else "",
    ] if part).strip()

    started = time.time()
    fallback_warning = ""
    try:
        raw_text, provider_id, model, reasoning_effort, fallback_warning = _call_prompt_provider_with_pool_fallback(
            provider_id,
            prompt,
            STYLE_EXTRACT_SYSTEM,
            model,
            reasoning_effort,
            "风格提取",
        )
        data = json.loads(_extract_first_json_block(raw_text))
    except Exception:
        data = _fallback_style_extract(current_text, user_message, candidate)

    name = str(data.get("name") or data.get("title") or "").strip()[:48] or "自定义风格"
    prompt_style = str(data.get("prompt_style") or data.get("promptTemplate") or data.get("positive_style") or "").strip()
    if not prompt_style:
        prompt_style = _fallback_style_extract(current_text, user_message, candidate)["prompt_style"]
    result = {
        "ok": True,
        "name": name,
        "title": name,
        "description": str(data.get("description") or "").strip()[:500],
        "positive_style": str(data.get("positive_style") or prompt_style).strip(),
        "avoid": str(data.get("avoid") or "").strip(),
        "best_for": str(data.get("best_for") or "").strip(),
        "prompt_style": prompt_style,
        "promptTemplate": prompt_style,
        "tags": data.get("tags") if isinstance(data.get("tags"), list) else [],
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
    }
    if fallback_warning:
        result["warning"] = fallback_warning
        result["fallback"] = "chatgpt_pool_chat"
    return result


def _is_full_prompt_too_short(result: dict[str, Any]) -> bool:
    full_prompt = str(result.get("full_prompt") or "").strip()
    if len(full_prompt) < MIN_FULL_PROMPT_CHARS:
        return True
    return _paragraph_count(full_prompt) < MIN_FULL_PROMPT_PARAGRAPHS


def _build_expand_prompt(original_text: str, result: dict[str, Any]) -> str:
    return "\n".join(
        [
            "上一轮 full_prompt 仍然太短，未达到 V7 完整度规格。请基于原始文本和上一轮 JSON 重新扩写。",
            "",
            "硬性要求：",
            f"- full_prompt 至少 {MIN_FULL_PROMPT_CHARS} 个中文字符。",
            f"- full_prompt 至少 {MIN_FULL_PROMPT_PARAGRAPHS} 个自然段，推荐 6 到 12 段。",
            "- 先判断组织策略：情绪法、结构法、混合法、媒介法、设计系统法、约束法、叙事法或变量模板法；默认使用混合法。",
            "- 按“先锁画面、再锁结构、再补气氛、再锁媒介、再锁空间、再锁构图、再锁质感、最后防跑偏”的顺序展开。",
            "- 每个自然段都必须有明确职责，例如主体段、结构段、媒介段、场景段、构图/版式段、情绪段、光线材质段、载体适配段或负面约束段。",
            "- 最后一段必须是“负面约束：...”。",
            "- compact_prompt 保持 160 到 320 个中文字符。",
            "- modules 必须保留上一轮已调用模块，并补齐 V7 要求模块。",
            "- 只返回合法 JSON 对象，不要 markdown，不要解释。",
            "",
            "原始文本：",
            "<<<",
            original_text,
            ">>>",
            "",
            "上一轮 JSON：",
            json.dumps(
                {
                    "full_prompt": result.get("full_prompt", ""),
                    "compact_prompt": result.get("compact_prompt", ""),
                    "modules": result.get("modules", []),
                    "warnings": result.get("warnings", []),
                    "router_summary": result.get("router_summary", ""),
                },
                ensure_ascii=False,
            ),
        ]
    )


def _normalize_polish_result(data: dict[str, Any], original_text: str) -> dict[str, Any]:
    return _apply_formula_guards(data, original_text)


def polish_prompt(text: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    original_text = str(text or "").strip()
    if not original_text:
        raise ValueError("缺少要润色的文本")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    skill_id = str(options.get("skill") or config.get("skill") or DEFAULT_PROMPT_SKILL_ID).strip()
    reasoning_effort = str(options.get("reasoning_effort") or config.get("reasoning_effort") or "medium").strip().lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = "medium"
    model = _choose_model(provider_id, str(options.get("model") or config.get("model") or "").strip())
    skill_prompt = _load_skill_prompt(skill_id)
    user_prompt = "\n".join(
        [
            "请用当前 skill 处理下面的文本节点内容。",
            "严格执行 V7 Router、条件模块库、词库附录、失败修复和输出格式。",
            "这是通用图像提示词 skill，不要默认套摄影人像公式。壁纸、插画、海报、手办、设计稿、UI、产品图等都要按各自类型调用模块。",
            "在调用模块前必须先判断提示词组织策略：情绪法、结构法、混合法、媒介法、设计系统法、约束法、叙事法或变量模板法；默认使用混合法。",
            "full_prompt 必须按“先锁画面、再锁结构、再补气氛、再锁媒介、再锁空间、再锁构图、再锁质感、最后防跑偏”组织，每个自然段都要有明确职责。",
            "如果输入涉及女性人像、身材、身体局部、性感化或网红写真，必须启用 M1/M12；发生风险转译时必须启用 M13；始终包含 M0/M2/M3/M7/M14。",
            "摄影、手机抓拍、POV、插画、3D、手办、UI、壁纸、海报都属于 M3 媒介与渲染模式的子模式，不要为某个风格单独膨胀模块。",
            "如果输入涉及光线、暗调、强对比、轮廓光、低曝光、烟雾承光或主体背景分离，必须执行 M8 光线分配规则；暗调强对比额外启用 M12。",
            "full_prompt 和 compact_prompt 都必须包含当前图像相关的最小必要负面约束。",
            f"full_prompt 必须是长版完整成片提示词，至少 {MIN_FULL_PROMPT_CHARS} 个中文字符、至少 {MIN_FULL_PROMPT_PARAGRAPHS} 个自然段，最后一段必须是负面约束。",
            "不要把 full_prompt 写成摘要或一段短润色。",
            "只返回合法 JSON 对象，不要 markdown，不要解释。",
            "",
            "文本节点内容：",
            "<<<",
            original_text,
            ">>>",
        ]
    )

    started = time.time()
    fallback_warning = ""
    raw_text, provider_id, model, reasoning_effort, fallback_warning = _call_prompt_provider_with_pool_fallback(
        provider_id,
        user_prompt,
        skill_prompt,
        model,
        reasoning_effort,
        "润色",
    )
    data = json.loads(_extract_first_json_block(raw_text))
    result = _normalize_polish_result(data, original_text)
    expanded = False
    if _is_full_prompt_too_short(result):
        expand_prompt = _build_expand_prompt(original_text, result)
        expanded_text, provider_id, model, reasoning_effort, expand_warning = _call_prompt_provider_with_pool_fallback(
            provider_id,
            expand_prompt,
            skill_prompt,
            model,
            reasoning_effort,
            "润色扩写",
        )
        fallback_warning = fallback_warning or expand_warning
        expanded_data = json.loads(_extract_first_json_block(expanded_text))
        result = _normalize_polish_result(expanded_data, original_text)
        expanded = True
    result.update(
        {
            "ok": True,
            "provider": provider_id,
            "skill": skill_id,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "expanded": expanded,
            "latency_seconds": round(time.time() - started, 2),
        }
    )
    if fallback_warning:
        result["warning"] = fallback_warning
        result["fallback"] = "chatgpt_pool_chat"
    return result
