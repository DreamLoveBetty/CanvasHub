#!/usr/bin/env python3
"""Prompt-skill model discovery, provider calls and prompt workflows.

This module owns provider and model selection, the GPT OAuth / OpenAI-compatible calls
and the Codex -> ChatGPT account-pool fallback, the generic-19 result cache, and the
public entry points (chat, polish, rewrite, block extraction, image / video analysis).
The pure rules those entries apply live in backend/services/prompt_*_rules.py and are
imported here, so existing `prompt_skill_client.<name>` imports keep working.
"""

from __future__ import annotations

import json
import os
import re
import requests
import sys
import time
import hashlib
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
from .services.prompt_video import summarize_video_references, video_summaries_prompt_context
from .services.prompt_text_rules import (
    MODULE_ORDER,
    PERSON_HINTS,
    FEMALE_HINTS,
    PHOTO_HINTS,
    MOBILE_PHOTO_HINTS,
    PREGNANCY_HINTS,
    SCENE_HINTS,
    TEXTURE_HINTS,
    FORMAT_HINTS,
    PRODUCT_HINTS,
    STRUCTURE_HINTS,
    STYLE_HINTS,
    LAYOUT_HINTS,
    MEDIUM_HINTS,
    LIGHTING_HINTS,
    HIGH_CONTRAST_LIGHTING_HINTS,
    LIGHTING_CONSTRAINT_HINTS,
    RISK_HINTS,
    CONSTRAINT_HINTS,
    BODY_SAFETY_CONSTRAINT_HINTS,
    BODY_SAFETY_FULL_CONSTRAINT,
    BODY_SAFETY_COMPACT_CONSTRAINT,
    PREGNANCY_CONSTRAINT_HINTS,
    PREGNANCY_FULL_CONSTRAINT,
    PREGNANCY_COMPACT_CONSTRAINT,
    HIGH_CONTRAST_FULL_CONSTRAINT,
    HIGH_CONTRAST_COMPACT_CONSTRAINT,
    GENERIC_CONSTRAINT,
    _as_dict,
    _as_list,
    _has_han,
    _paragraph_count,
    _extract_first_json_block,
    _fallback_style_extract,
    _normalize_polish_result,
)
from .services.prompt_adapter_rules import (
    SAFE_REWRITE_CONSTRAINT,
    SAFE_REWRITE_STRUCTURED_SECTIONS,
    ADAPTER_TASK_TYPES,
    ADAPTER_REPLACEMENTS,
    ADAPTER_MATURE_CONTEXT_TERMS,
    ADAPTER_PERSON_TERMS,
    ADAPTER_SEXUAL_TERMS,
    ADAPTER_EXPLICIT_TERMS,
    ADAPTER_GRAPHIC_VIOLENCE_TERMS,
    ADAPTER_REAL_PERSON_RISK_TERMS,
    ADAPTER_HARD_BLOCK_MINOR_TERMS,
    ADAPTER_SCORE_RULES,
    ADAPTER_INTENT_TERMS,
    analyze_prompt_adapter,
    _build_adapter_fallback_prompts,
    _extract_safe_rewrite_prompts,
    _ensure_safe_rewrite_constraints,
)
from .services.prompt_image_analysis_rules import (
    NO_TEXT_CHINESE_CONSTRAINT,
    IMAGE_ANALYSIS_SPECIALIZED_FLAGS,
    IMAGE_ANALYSIS_FLAG_HINTS,
    _clean_string,
    _safe_int,
    _data_image_parts,
    _analysis_image_mime_type,
    _first_text,
    _build_image_analysis_user_prompt,
    _compose_no_text_prompt,
    _module_text,
    _normalize_image_type_flags,
    REFERENCE_DEPENDENCY_MARKERS,
    _clean_standalone_context,
    PIXEL_STYLE_MARKERS,
    _normalize_visual_style,
    _format_visual_style_prompt,
    _normalize_subjects,
    _normalize_overlay_elements,
    _enhance_main_prompt_details,
    _enhance_universal_style_details,
    BASE_IMAGE_PLACEHOLDER_SLOTS,
    _has_placeholder_slot,
    _build_placeholder_slots,
    _format_placeholder_slots_markdown,
    _build_chinese_main_prompt,
    _build_chinese_universal_style_prompt,
    _build_chinese_specialized_prompt,
    _build_image_specific_negative_prompt,
    _is_polluted_visual_prompt,
    _normalize_text_regions,
    _format_text_regions_markdown,
    _prefer_chinese_prompt,
    _prefer_standalone_chinese_prompt,
)
from .services.prompt_block_rules import (
    PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM,
    PROMPT_BLOCK_MODULE_ALIASES,
    PROMPT_BLOCK_GENERIC_MODULE_LABELS,
    PROMPT_BLOCK_GENERIC_MODULE_DETAIL_HINTS,
    PROMPT_BLOCK_GENERIC_MIN_DETAIL_CHARS,
    PROMPT_BLOCK_GENERIC_MIN_DETAIL_CLAUSES,
    PROMPT_BLOCK_GENERIC_VISUAL_MODULES,
    PROMPT_BLOCK_GENERIC_BASE_REQUIRED_MODULES,
    PROMPT_BLOCK_GENERIC_REQUIRED_MODULES_BY_TYPE,
    PROMPT_BLOCK_GENERIC_MIN_MODULES_BY_TYPE,
    PROMPT_BLOCK_GENERIC_MIN_ANCHORS,
    PROMPT_BLOCK_GENERIC_ANCHOR_ATTRIBUTES,
    PROMPT_BLOCK_GENERIC_ANCHOR_IMPORTANCE,
    PROMPT_BLOCK_GENERIC_ANCHOR_CONFIDENCE,
    PROMPT_BLOCK_GENERIC_TYPE_FIDELITY_CONTEXT,
    PROMPT_BLOCK_GENERIC_ANALYSIS_MARKERS,
    PROMPT_BLOCK_GENERIC_EMPTY_DETAIL_PHRASES,
    PROMPT_BLOCK_GENERIC_DETAIL_EVIDENCE_PATTERNS,
    PROMPT_BLOCK_MODULE_LABELS,
    PROMPT_BLOCK_TEMPLATES,
    PROMPT_BLOCK_PRIMARY_TYPES,
    PROMPT_BLOCK_MODULE_TYPE_OWNERS,
    PROMPT_BLOCK_TYPE_HINTS,
    _infer_prompt_block_primary_type_from_text,
    _infer_prompt_block_primary_type_from_modules,
    _prompt_block_template_context,
    _normalize_extracted_prompt_blocks,
    _split_rule_snapshot,
    generic_19_prompt_block_split_rule,
    _generic_19_cache_key,
    _generic_19_type_context,
    _generic_19_content_fingerprint,
    _generic_19_enrich_block_from_anchors,
    _generic_19_prepare_blueprint_blocks,
    _generic_19_apply_source_geometry,
    _generic_19_dedupe_blocks,
    _generic_19_prompt_block_quality,
    _generic_19_block_quality_rank,
    _merge_generic_19_repaired_blocks,
    _prompt_blocks_from_image_analysis,
)

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
GENERIC_19_CACHE_DIR = Path(
    os.environ.get("PROMPT_GENERIC_19_CACHE_DIR", "/tmp/tg-mini-app-img-gen-generic19-cache")
).expanduser()
GENERIC_19_CACHE_TTL_SECONDS = int(os.environ.get("PROMPT_GENERIC_19_CACHE_TTL", str(24 * 60 * 60)))
GENERIC_19_CACHE_MAX_ITEMS = int(os.environ.get("PROMPT_GENERIC_19_CACHE_MAX_ITEMS", "32"))
MIN_FULL_PROMPT_CHARS = int(os.environ.get("PROMPT_SKILL_MIN_FULL_CHARS", "900"))
MIN_FULL_PROMPT_PARAGRAPHS = int(os.environ.get("PROMPT_SKILL_MIN_FULL_PARAGRAPHS", "5"))
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
        # The desktop-wide cache may also contain models belonging to another
        # provider. Passing one of those ids to the ChatGPT-account Codex API
        # produces a hard 400 and needlessly drops image analysis to the
        # lower-fidelity account-pool fallback.
        if not re.match(r"^(?:gpt-|codex-|o[134](?:-|$))", model_id, re.IGNORECASE):
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
    if (
        provider_id == DEFAULT_PROMPT_SKILL_PROVIDER
        and default_model
        and re.match(r"^(?:gpt-|codex-|o[134](?:-|$))", default_model, re.IGNORECASE)
        and all(str(item.get("id") or "") != default_model for item in models)
    ):
        # A configured Codex model remains usable even when the shared cache is
        # stale or was last refreshed by another provider.
        models.insert(0, {
            "id": default_model,
            "label": default_model,
            "description": "当前已配置的 Codex 模型",
            "default_reasoning_effort": "",
            "reasoning_efforts": list(GPT_REASONING_EFFORTS),
            "available": True,
        })
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


def _call_gpt_oauth_stream(prompt: str, system: str, model: str, reasoning_effort: str, images: list[str] | None = None) -> Iterator[str]:
    if not build_text_request or not extract_text or not codex_headers or not get_codex_auth or not iter_sse_events or not codex_api_base:
        raise RuntimeError("Codex OAuth 流式客户端不可用")
    _, env_overrides = _gpt_oauth_env_overrides()
    request = _build_multimodal_text_request(prompt, images, system, model, reasoning_effort) if images else build_text_request(
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


def _call_openai_compatible_stream(provider: dict[str, Any], prompt: str, system: str, model: str, images: list[str] | None = None) -> Iterator[str]:
    api_base = str(provider.get("api_base") or "").rstrip("/")
    api_key = str(provider.get("api_key") or os.environ.get(str(provider.get("api_key_env") or "")) or "")
    if not api_base:
        raise RuntimeError("第三方 provider 未配置 api_base")
    content = ([{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": image_url}} for image_url in images
    ]) if images else prompt
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
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


def _call_prompt_provider_stream(provider_id: str, prompt: str, system: str, model: str, reasoning_effort: str, images: list[str] | None = None) -> Iterator[str]:
    if images and provider_id == "chatgpt_pool":
        reply, _ = _chatgpt_pool_image_json_reply(prompt, system, images)
        yield reply
        return
    image_options = {"images": images} if images else {}
    if provider_id == DEFAULT_PROMPT_SKILL_PROVIDER:
        yield from _call_gpt_oauth_stream(prompt, system, model, reasoning_effort, **image_options)
        return
    yield from _call_openai_compatible_stream(_as_dict(_provider_settings().get(provider_id)), prompt, system, model, **image_options)


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


def _call_prompt_provider(provider_id: str, prompt: str, system: str, model: str, reasoning_effort: str, images: list[str] | None = None) -> str:
    if images:
        return _call_prompt_provider_image_json(provider_id, prompt, system, images, model, reasoning_effort)
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


def _fallback_prompt_chat_to_pool(prompt: str, system: str, error: Exception, images: list[str] | None = None) -> tuple[str, str, str]:
    reply, model = _chatgpt_pool_image_json_reply(prompt, system, images) if images else _chatgpt_pool_chat_reply(prompt, system)
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


def call_prompt_model(
    prompt: str,
    system: str,
    options: dict[str, Any] | None = None,
    images: list[Any] | None = None,
    error_label: str = "生成",
) -> dict[str, Any]:
    """Call the configured prompt model without applying image-prompt rules.

    Domain-specific prompt compilers use this entry point so provider/model
    selection, multimodal transport, and the Codex-to-account-pool fallback
    remain consistent with the existing prompt assistant.
    """
    options = options or {}
    user_prompt = str(prompt or "").strip()
    system_prompt = str(system or "").strip()
    if not user_prompt:
        raise ValueError("缺少模型请求内容")
    if not system_prompt:
        raise ValueError("缺少模型系统指令")

    config = get_prompt_skill_config()
    requested_provider = str(
        options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER
    ).strip()
    requested_model = str(options.get("model") or config.get("model") or "").strip()
    provider_id, model, selection_warning = _select_prompt_provider_model_with_pool_fallback(
        requested_provider,
        requested_model,
        str(error_label or "生成"),
    )
    requested_effort = str(
        options.get("reasoning_effort")
        or options.get("reasoningEffort")
        or config.get("reasoning_effort")
        or "medium"
    ).strip().lower()
    reasoning_effort = requested_effort if requested_effort in GPT_REASONING_EFFORTS else "medium"

    image_urls: list[str] = []
    for item in (images or [])[:8]:
        if isinstance(item, dict):
            value = (
                item.get("data_url")
                or item.get("dataUrl")
                or item.get("image_data")
                or item.get("imageData")
                or item.get("base64")
                or item.get("url")
                or item.get("image_url")
                or item.get("imageUrl")
            )
        else:
            value = item
        if not str(value or "").strip():
            continue
        image_url = _prepare_image_analysis_image_url(value)
        if not image_url.startswith(("data:image/", "http://", "https://")):
            raise ValueError("参考图必须是 data URL 或 HTTP(S) URL")
        image_urls.append(image_url)

    started = time.time()
    warnings = [selection_warning] if selection_warning else []
    fallback = ""
    if not image_urls:
        raw_text, provider_id, model, reasoning_effort, call_warning = _call_prompt_provider_with_pool_fallback(
            provider_id,
            user_prompt,
            system_prompt,
            model,
            reasoning_effort,
            str(error_label or "生成"),
        )
        if call_warning:
            warnings.append(call_warning)
        if provider_id == "chatgpt_pool" and requested_provider != "chatgpt_pool":
            fallback = "chatgpt_pool_chat"
    elif provider_id == "chatgpt_pool":
        raw_text, model = _chatgpt_pool_image_json_reply(user_prompt, system_prompt, image_urls)
        reasoning_effort = ""
        if requested_provider != "chatgpt_pool":
            fallback = "chatgpt_pool_multimodal_chat"
    else:
        try:
            raw_text = _call_prompt_provider_image_json(
                provider_id,
                user_prompt,
                system_prompt,
                image_urls,
                model,
                reasoning_effort,
            )
        except Exception as exc:
            if not _should_fallback_prompt_chat_to_pool(requested_provider, exc):
                raise
            raw_text, model = _chatgpt_pool_image_json_reply(user_prompt, system_prompt, image_urls)
            provider_id = "chatgpt_pool"
            reasoning_effort = ""
            fallback = "chatgpt_pool_multimodal_chat"
            warning = f"{_prompt_pool_fallback_reason(exc)}{str(error_label or '生成')}：{exc}"
            warnings.append(warning)
            print(f"⚠️ Prompt Model {error_label} fallback to account pool multimodal chat: {exc}")

    raw_text = str(raw_text or "").strip()
    if not raw_text:
        raise RuntimeError("提示词模型没有返回内容")
    result = {
        "ok": True,
        "text": raw_text,
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "image_count": len(image_urls),
        "latency_seconds": round(time.time() - started, 2),
    }
    if warnings:
        result["warning"] = "；".join(dict.fromkeys(warnings))
    if fallback:
        result["fallback"] = fallback
    return result


ASSISTANT_CHAT_SYSTEM = """你是桌面画布中文本节点的提示词创作助手。
你的任务是帮助用户讨论、判断和收敛图像提示词方向，而不是默认生成完整候选提示词。
回答必须专业、精准、可执行；长度由问题复杂度决定，不强制简短，但避免客套、模板化废话和无关扩写。
除非用户明确要求整理为正式提示词，否则不要输出完整成片提示词，不要输出多版本候选列表。
你可以诊断当前文本的问题、提出改写策略、比较风格方向、指出容易跑偏的词，并在方向不清楚时提出关键追问。"""

H3_ASSISTANT_CHAT_SYSTEM = """你是桌面画布中的 MiniMax H3 视频提示词助手。
当前第一期只支持 I2VA，也就是从一张首帧图片连续生成 4 到 15 秒的有声视频。
你的任务是帮助用户讨论并收敛视频意图，重点检查首帧锚点、主体动作路径、镜头运动、时间节奏、连续性、环境声、对白和非画面配乐。
不要把视频提示词当成静态图像描述，不要套用图像 V7 模块、图像负面约束或堆砌画质词。
除非用户明确要求查看格式示例，否则不要直接输出最终三段正式提示词；正式版本由“生成版本”按钮调用官方 H3 编译器产生。
最终 H3 正文使用英文，但对白、歌词和画面文字保留用户原语言。回答用户时使用用户当前语言，保持专业、具体、可执行。"""

PROMPT_BLOCK_EXTRACTION_SYSTEM = """你是图像生成提示词素材块拆分器。
你的唯一任务是把用户给出的完整提示词拆成可以单独复用和快速插入的短提示词素材块。

必须遵守：
1. 不要输出完整提示词，不要把原文整体作为一个素材块。
2. 按语义拆分；人物优先拆成身份、外貌、体形身材、动作姿态、表情视线、服装造型、妆发、配饰。外貌只写面部与皮肤，体形身材独立记录可见身体比例和体量。
3. 其他内容按生成目标、主体、场景、构图、镜头、光线、色彩、视觉风格、材质细节、质量要求、负面约束等拆分。
4. 每个素材块必须能脱离原文独立插入，保留关键限定词，但不得凭空增加原文没有的信息。
5. 合并重复内容；忽略空泛套话。遵循本次拆分规则给出的粒度和数量上限；未指定时通常输出 3-18 个素材块。
6. name 使用 4-16 个字概括内容；content 使用原提示词语言；compact_content 是更短的同义版本。
7. module_type 只使用 snake_case 标识；优先使用本次任务提供的拆分规则模块。通用素材块可使用 goal、identity、appearance、body_shape、pose、expression、clothing、makeup_hair、accessories、subject、scene、composition、camera、lighting、color、style、material、quality、constraints、custom；body_shape 仅用于人物、时尚和角色，确实无法归类时使用 custom。
8. 输出严格 JSON 对象，不要 Markdown、解释或代码围栏。

JSON 形状：
{"primary_type":"portrait/landscape/product/...","blocks":[{"name":"","module_type":"","content":"","compact_content":"","english_content":"","tags":[]}]}"""

PROMPT_BLOCK_GENERIC_PORTRAIT_CORE_MODULES = {
    "identity", "appearance", "body_shape", "pose", "expression", "clothing", "composition", "camera", "lighting", "color",
}

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

ADAPTER_MINOR_TERMS = (
    "minor", "minors", "child", "children", "young girl", "teen", "teenage", "schoolgirl", "loli", "childlike",
    "未成年", "儿童", "孩子", "小孩", "少女", "幼态", "学生妹",
)


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
    image_inputs = options.get("images", [])
    if not isinstance(image_inputs, list) or len(image_inputs) > 4:
        raise ValueError("引用图片必须是列表，最多支持 4 张图片")
    images = _normalize_image_analysis_inputs(image_inputs)
    if len(images) != len(image_inputs):
        raise ValueError("引用图片缺少有效图像数据，请重新选择图片")
    supplied_video_summaries = options.get("video_summaries")
    if supplied_video_summaries is not None and not isinstance(supplied_video_summaries, list):
        raise ValueError("视频分析摘要必须是列表")
    video_summaries = supplied_video_summaries or summarize_video_references(
        options.get("videos", []),
        call_model=call_prompt_model,
        options={
            "provider": options.get("provider"),
            "model": options.get("model"),
            "reasoning_effort": options.get("reasoning_effort") or options.get("reasoningEffort") or "low",
        },
    )
    video_context = video_summaries_prompt_context(video_summaries)

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
    task_context = options.get("task_context") if isinstance(options.get("task_context"), dict) else {}
    is_h3 = (
        str(task_context.get("task_domain") or "").lower() == "video"
        and str(task_context.get("target_model") or task_context.get("model_family") or "").lower() == "minimax_h3"
    )
    history_lines = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        role = "用户" if str(item.get("role") or "") == "user" else "助手"
        content = str(item.get("text") or item.get("content") or "").strip()
        if content:
            history_lines.append(f"{role}: {content[:1200]}")

    prompt = "\n".join(part for part in [
        (
            "请围绕当前文本节点内容、首帧关系和用户消息讨论 MiniMax H3 I2VA 视频方向。"
            if is_h3
            else "请围绕当前文本节点内容和用户消息进行提示词方向讨论。"
        ),
        "不要调用或模拟正式多版本候选生成；如果用户需要正式版本，请建议他们使用“生成版本”。",
        (
            "H3 任务上下文：\n" + json.dumps({
                "mode": task_context.get("mode") or "I2VA",
                "duration_seconds": task_context.get("duration_seconds"),
                "aspect_ratio": task_context.get("aspect_ratio"),
                "first_frame": task_context.get("first_frame"),
            }, ensure_ascii=False)
            if is_h3 else ""
        ),
        f"当前文本节点内容：\n<<<\n{current_text}\n>>>" if current_text else "当前文本节点内容：空",
        f"当前风格预设：{style_title}\n{style_text}" if (style_title or style_text) else "",
        (
            "本轮实际附带图片（按附件顺序对应引用编号，请直接查看图像内容）：\n"
            + "\n".join(f"第 {index + 1} 张：{item['id']}（{item['label']}）" for index, item in enumerate(images))
        ) if images else "",
        (
            "本轮 @ 引用视频的 12--24 帧时序分析（这是参考素材，不是待生成视频的首帧）：\n"
            + video_context
        ) if video_context else "",
        "最近对话：\n" + "\n".join(history_lines) if history_lines else "",
        f"用户消息：\n{user_message}" if user_message else "用户消息：请基于当前文本节点给出方向建议。",
    ] if part).strip()

    return {
        "prompt": prompt,
        "provider_id": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "system": H3_ASSISTANT_CHAT_SYSTEM if is_h3 else ASSISTANT_CHAT_SYSTEM,
        "task_domain": "video" if is_h3 else "image",
        "images": [item["image_url"] for item in images],
        "video_summaries": video_summaries,
    }


def assistant_chat(text: str, message: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lightweight prompt-direction chat that avoids the heavy V7 candidate flow."""
    request = _assistant_chat_request(text, message, options)
    provider_id = request["provider_id"]
    model = request["model"]
    reasoning_effort = request["reasoning_effort"]
    system_prompt = str(request.get("system") or ASSISTANT_CHAT_SYSTEM)
    image_options = {"images": request["images"]} if request.get("images") else {}
    started = time.time()
    warning = ""
    try:
        reply = _call_prompt_provider(provider_id, request["prompt"], system_prompt, model, reasoning_effort, **image_options)
    except Exception as exc:
        if not _should_fallback_prompt_chat_to_pool(provider_id, exc):
            raise
        reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], system_prompt, exc, **image_options)
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


def _generic_19_cached_result(cache_key: str, started: float) -> dict[str, Any] | None:
    if not cache_key or GENERIC_19_CACHE_TTL_SECONDS <= 0:
        return None
    path = GENERIC_19_CACHE_DIR / f"{cache_key}.json"
    try:
        if not path.is_file() or time.time() - path.stat().st_mtime > GENERIC_19_CACHE_TTL_SECONDS:
            if path.exists():
                path.unlink(missing_ok=True)
            return None
        result = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    blocks = result.get("blocks")
    coverage = float(result.get("anchor_coverage") or result.get("fidelity_score") or 0.0)
    if not result.get("ok") or not isinstance(blocks, list) or not (1 <= len(blocks) <= len(PROMPT_BLOCK_GENERIC_MODULE_LABELS)) or coverage < 0.9:
        return None
    cached = dict(result)
    cached["analysis_id"] = f"image_blocks_{int(time.time())}_{os.urandom(3).hex()}"
    cached["latency_seconds"] = round(time.time() - started, 2)
    cached["cache_hit"] = True
    return cached


def _store_generic_19_cached_result(cache_key: str, result: dict[str, Any]) -> None:
    if not cache_key or GENERIC_19_CACHE_TTL_SECONDS <= 0:
        return
    coverage = float(result.get("anchor_coverage") or result.get("fidelity_score") or 0.0)
    blocks = result.get("blocks")
    if result.get("warning") or coverage < 0.9 or not isinstance(blocks, list) or not (1 <= len(blocks) <= len(PROMPT_BLOCK_GENERIC_MODULE_LABELS)):
        return
    try:
        GENERIC_19_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = GENERIC_19_CACHE_DIR / f"{cache_key}.json"
        temp_path = GENERIC_19_CACHE_DIR / f".{cache_key}.{os.getpid()}.{os.urandom(2).hex()}.tmp"
        temp_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp_path, path)
        cached_files = sorted(
            GENERIC_19_CACHE_DIR.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for stale_path in cached_files[max(1, GENERIC_19_CACHE_MAX_ITEMS):]:
            stale_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"⚠️ Generic 19 cache write skipped: {exc}")


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
    system_prompt = str(request.get("system") or ASSISTANT_CHAT_SYSTEM)
    image_options = {"images": request["images"]} if request.get("images") else {}
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
        for chunk in _call_prompt_provider_stream(provider_id, request["prompt"], system_prompt, model, reasoning_effort, **image_options):
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
            reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], system_prompt, stream_error, **image_options)
            provider_id = "chatgpt_pool"
            reasoning_effort = ""
        else:
            try:
                reply = _call_prompt_provider(provider_id, request["prompt"], system_prompt, model, reasoning_effort, **image_options)
            except Exception as full_error:
                if not _should_fallback_prompt_chat_to_pool(provider_id, full_error):
                    raise
                reply, model, warning = _fallback_prompt_chat_to_pool(request["prompt"], system_prompt, full_error, **image_options)
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


def _image_analysis_limits() -> tuple[int, int, int, int]:
    max_edge = _safe_int(PROMPT_IMAGE_ANALYSIS_MAX_EDGE, 1800, 512, 4096)
    max_bytes = _safe_int(PROMPT_IMAGE_ANALYSIS_MAX_BYTES, 3 * 1024 * 1024, 512 * 1024, 12 * 1024 * 1024)
    quality = _safe_int(PROMPT_IMAGE_ANALYSIS_JPEG_QUALITY, 86, 50, 95)
    min_quality = _safe_int(PROMPT_IMAGE_ANALYSIS_MIN_JPEG_QUALITY, 68, 40, quality)
    return max_edge, max_bytes, quality, min_quality


_PROMPT_IMAGE_SUPPORTED_RATIOS = (
    ("1:1", 1.0),
    ("2:3", 2 / 3),
    ("3:2", 3 / 2),
    ("3:4", 3 / 4),
    ("4:3", 4 / 3),
    ("4:5", 4 / 5),
    ("5:4", 5 / 4),
    ("9:16", 9 / 16),
    ("16:9", 16 / 9),
    ("9:21", 9 / 21),
    ("21:9", 21 / 9),
)


def _image_source_geometry(value: Any) -> dict[str, Any]:
    parts = _data_image_parts(str(value or ""))
    if not parts or Image is None:
        return {}
    try:
        data = base64.b64decode(parts[1], validate=True)
        image = Image.open(BytesIO(data))
        image.load()
        if ImageOps is not None:
            image = ImageOps.exif_transpose(image)
        width, height = image.size
    except (binascii.Error, UnidentifiedImageError, OSError, ValueError):
        return {}
    if width <= 0 or height <= 0:
        return {}
    aspect_ratio = width / height
    recommended_ratio, recommended_value = min(
        _PROMPT_IMAGE_SUPPORTED_RATIOS,
        key=lambda item: abs(aspect_ratio - item[1]),
    )
    orientation = "square" if abs(aspect_ratio - 1.0) <= 0.03 else ("landscape" if width > height else "portrait")
    return {
        "width": int(width),
        "height": int(height),
        "aspect_ratio": round(aspect_ratio, 4),
        "orientation": orientation,
        "recommended_ratio": recommended_ratio,
        "recommended_ratio_error": round(abs(aspect_ratio - recommended_value), 4),
    }


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


def _normalize_image_analysis_inputs(images: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(images):
        if not isinstance(item, dict):
            continue
        raw_image_value = (
            item.get("data_url")
            or item.get("dataUrl")
            or item.get("imageData")
            or item.get("base64")
            or item.get("url")
            or item.get("imageUrl")
        )
        source_geometry = _image_source_geometry(raw_image_value)
        image_url = _prepare_image_analysis_image_url(raw_image_value)
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
                "source_geometry": source_geometry,
                "role": "primary" if not normalized else "fusion_reserved",
            }
        )
    return normalized


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


VIDEO_PROMPT_ANALYSIS_SYSTEM = """你是视频参考素材分析器。你会收到由 12--24 个等距关键帧分批得到的时序摘要，可能还附带少量图片参考。
请把证据整理成可用于图像或视频创作的分析结果。不要把参考视频误称为首帧，不要声称看到了未提供的音频，也不要虚构摘要中不存在的事件。
只输出一个 JSON 对象，不要 Markdown。字段必须为：visual_summary、motion、camera、timing、style、visible_text、prompt_candidate、warnings。
其中 warnings 必须是字符串数组，其余字段必须是字符串。prompt_candidate 应是一段可直接投喂生成模型、同时保留主体、时序动作、镜头、光色与风格锚点的中文提示词。"""


def analyze_prompt_video(
    message: str,
    videos: list[Any],
    options: dict[str, Any] | None = None,
    *,
    images: list[Any] | None = None,
) -> dict[str, Any]:
    """Analyze browser-sampled video references without transporting raw video."""
    options = options or {}
    started = time.time()
    model_options = {
        "provider": options.get("provider"),
        "model": options.get("model"),
        "reasoning_effort": options.get("reasoning_effort") or options.get("reasoningEffort") or "medium",
    }
    summaries = summarize_video_references(
        videos,
        call_model=call_prompt_model,
        options=model_options,
    )
    if not summaries:
        raise ValueError("缺少要分析的视频")

    normalized_images = _normalize_image_analysis_inputs(images if isinstance(images, list) else [])
    if images and len(normalized_images) != len(images):
        raise ValueError("附加图片缺少有效图像数据，请重新选择图片")
    video_context = video_summaries_prompt_context(summaries)
    prompt = "\n\n".join(part for part in [
        f"用户分析要求：{str(message or '').strip()}" if str(message or "").strip() else "用户分析要求：提取可复用的视觉与运动方向。",
        "视频关键帧时序摘要：\n" + video_context,
        (
            "另有图片参考：" + "、".join(
                f"{item.get('id')}（{item.get('label')}）" for item in normalized_images
            )
        ) if normalized_images else "",
        "综合各批摘要的先后关系；如果跨批无法确认连续动作，请在 warnings 中说明。",
    ] if part)
    final_result = call_prompt_model(
        prompt,
        VIDEO_PROMPT_ANALYSIS_SYSTEM,
        model_options,
        images=[item["image_url"] for item in normalized_images[:4]],
        error_label="视频参考分析",
    )
    raw_text = str(final_result.get("text") or "").strip()
    if not raw_text:
        raise RuntimeError("视频参考分析模型没有返回内容")
    try:
        parsed = json.loads(_extract_first_json_block(raw_text))
    except Exception as exc:
        raise ValueError(f"视频参考分析模型返回的 JSON 无效：{exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("视频参考分析模型返回的 JSON 结构无效")

    def clean_field(key: str, fallback: str = "") -> str:
        value = parsed.get(key)
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False)
        clean = str(value or fallback).strip()
        return clean[:12_000]

    warnings_value = parsed.get("warnings")
    warnings = [str(item).strip() for item in warnings_value] if isinstance(warnings_value, list) else []
    warnings = [item for item in warnings if item]
    for summary in summaries:
        warnings.extend(str(item).strip() for item in summary.get("warnings") or [] if str(item).strip())
        if not summary.get("recommended_frame_minimum_met"):
            warnings.append(f"{summary.get('label') or summary.get('id')} 少于建议的 12 帧，时序判断可信度较低。")
    warnings = list(dict.fromkeys(warnings))

    visual_summary = clean_field("visual_summary", summaries[0].get("summary") or "")
    motion = clean_field("motion")
    camera = clean_field("camera")
    timing = clean_field("timing")
    style = clean_field("style")
    visible_text = clean_field("visible_text")
    prompt_candidate = clean_field("prompt_candidate") or "；".join(
        value for value in (visual_summary, motion, camera, timing, style) if value
    )
    if not prompt_candidate:
        raise ValueError("视频参考分析缺少可用提示词候选")

    public_summaries = [{
        key: copy_value
        for key, copy_value in summary.items()
        if key != "batch_summaries"
    } for summary in summaries]
    analysis = {
        "visual_summary": visual_summary,
        "motion": motion,
        "camera": camera,
        "timing": timing,
        "style": style,
        "visible_text": visible_text,
        "warnings": warnings,
        "video_references": public_summaries,
        "sampling": {
            "strategy": "browser_uniform_frames",
            "frame_range": "12-24",
            "batch_size": 8,
        },
    }
    analysis_id = f"video_analysis_{int(time.time())}_{hashlib.sha1(video_context.encode('utf-8')).hexdigest()[:8]}"
    candidate = {
        "id": f"{analysis_id}_main",
        "kind": "video_analysis_main",
        "label": "视频参考分析主候选",
        "badge": "视频",
        "text": prompt_candidate,
        "base_text": prompt_candidate,
    }
    module_specs = [
        ("visual_summary", "视觉概述", visual_summary, "summary"),
        ("motion", "动作变化", motion, "summary"),
        ("camera", "镜头语言", camera, "summary"),
        ("timing", "节奏与时序", timing, "summary"),
        ("style", "光色与风格", style, "prompt"),
        ("visible_text", "可见文字", visible_text, "text"),
        ("warnings", "不确定项", "\n".join(warnings), "summary"),
    ]
    modules = [
        {"id": module_id, "title": title, "text": text, "kind": kind, "editable": False}
        for module_id, title, text, kind in module_specs
        if text
    ]
    modules.append({
        "id": "full_json",
        "title": "完整 JSON",
        "kind": "json",
        "text": json.dumps(analysis, ensure_ascii=False, indent=2),
        "json": analysis,
    })
    result = {
        "ok": True,
        "mode": "video",
        "analysis_id": analysis_id,
        "analysis": analysis,
        "candidate": candidate,
        "candidates": [candidate],
        "modules": modules,
        "provider": final_result.get("provider"),
        "model": final_result.get("model"),
        "reasoning_effort": final_result.get("reasoning_effort"),
        "latency_seconds": round(time.time() - started, 2),
    }
    if final_result.get("warning"):
        result["warning"] = final_result["warning"]
    if final_result.get("fallback"):
        result["fallback"] = final_result["fallback"]
    return result


def _extract_generic_19_prompt_blocks_from_image(
    message: str,
    images: list[Any],
    primary_type: str = "",
    options: dict[str, Any] | None = None,
    split_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read an image directly into the high-fidelity reusable prompt modules."""
    options = options or {}
    normalized_images = _normalize_image_analysis_inputs(images if isinstance(images, list) else [])
    if not normalized_images:
        raise ValueError("缺少要拆分的图片")

    config = get_prompt_skill_config()
    provider_id = str(options.get("provider") or config.get("provider") or DEFAULT_PROMPT_SKILL_PROVIDER).strip()
    requested_model = str(options.get("model") or config.get("model") or "").strip()
    original_provider_id = provider_id
    provider_id, model, warning = _select_prompt_provider_model_with_pool_fallback(
        provider_id,
        requested_model,
        "图片素材块拆分",
    )
    requested_effort = str(options.get("reasoning_effort") or options.get("reasoningEffort") or "high").strip().lower()
    reasoning_effort = requested_effort if requested_effort in GPT_REASONING_EFFORTS else "high"
    requested_type = str(primary_type or "").strip()
    if requested_type not in PROMPT_BLOCK_PRIMARY_TYPES:
        requested_type = ""

    primary_image = normalized_images[0]
    source_geometry = primary_image.get("source_geometry") if isinstance(primary_image.get("source_geometry"), dict) else {}
    geometry_context = ""
    if source_geometry:
        geometry_context = (
            f"原图几何：{source_geometry.get('width')}×{source_geometry.get('height')}，"
            f"宽高比 {source_geometry.get('aspect_ratio')}，方向 {source_geometry.get('orientation')}；"
            f"最近支持比例为 {source_geometry.get('recommended_ratio')}。"
            "源画幅、主体占比和边缘裁切只写入 composition；goal 不得复述这些几何信息；"
            "constraints 只保留一条简短的错误比例限制，不得复述原图尺寸、主体占比或裁切细节。"
        )
    user_direction = _clean_string(message, 4000)
    prompt = "\n".join(part for part in [
        "请直接读取第一张图片，先建立唯一视觉蓝图，再严格按高保真模块体系输出视觉指纹；人物身体区域可见时必须单独输出 body_shape（体形身材）。",
        "目标是让重新生成尽可能保持同一视觉身份；优先识别可把类别区分开的几何、比例、位置、材质、纹理、光学和负面混淆对，而不是堆形容词。",
        f"输入图片名称：{primary_image.get('label') or primary_image['id']}",
        geometry_context,
        f"适用内容类型：{requested_type or '自动判断'}",
        _prompt_block_template_context(requested_type, split_rule),
        _generic_19_type_context(requested_type),
        f"用户补充要求：\n{user_direction}" if user_direction else "",
        "content 可省略，anchors/visual_blueprint 才是事实源；不要返回普通图片分析主提示词。最终只返回严格 JSON。",
    ] if part).strip()
    started = time.time()
    image_urls = [primary_image["image_url"]]
    cache_key = _generic_19_cache_key(
        primary_image["image_url"],
        requested_type,
        user_direction,
        provider_id,
        model,
        reasoning_effort,
        split_rule,
    )
    cached_result = _generic_19_cached_result(cache_key, started)
    if cached_result:
        return cached_result

    def parse_blocks(raw_text: str) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        if not raw_text:
            raise RuntimeError("图片素材块拆分模型没有返回内容")
        parsed = json.loads(_extract_first_json_block(raw_text))
        if not isinstance(parsed, dict):
            raise ValueError("图片素材块拆分模型返回的 JSON 结构不完整")
        has_full_blocks = isinstance(parsed.get("blocks"), list)
        has_repair_blocks = isinstance(parsed.get("repair_modules"), list)
        raw_blueprint = parsed.get("visual_blueprint") or parsed.get("visualBlueprint")
        has_blueprint_anchors = bool(
            isinstance(raw_blueprint, dict)
            and isinstance(raw_blueprint.get("anchors"), list)
            and raw_blueprint.get("anchors")
        )
        if not has_full_blocks and not has_repair_blocks and not has_blueprint_anchors:
            raise ValueError("图片素材块拆分模型返回的 JSON 缺少 blocks、repair_modules 或 visual_blueprint.anchors")
        prepared_items, blueprint = _generic_19_prepare_blueprint_blocks(parsed, requested_type)
        if not prepared_items:
            raise ValueError("图片素材块拆分模型没有返回有效视觉锚点")
        model_type = str(parsed.get("primary_type") or parsed.get("primaryType") or "").strip()
        block_text = " ".join(
            str(item.get("content") or item.get("text") or "")
            for item in prepared_items
            if isinstance(item, dict)
        )
        resolved_type = (
            requested_type
            or (model_type if model_type in PROMPT_BLOCK_PRIMARY_TYPES else "")
            or _infer_prompt_block_primary_type_from_text(block_text)
        )
        normalization_rule = dict(split_rule or generic_19_prompt_block_split_rule())
        normalization_rule["options"] = {
            **(normalization_rule.get("options") if isinstance(normalization_rule.get("options"), dict) else {}),
            "max_blocks": 30,
        }
        candidate_blocks = _normalize_extracted_prompt_blocks(
            {"blocks": prepared_items},
            resolved_type,
            normalization_rule,
        )
        source_pool: dict[str, list[dict[str, Any]]] = {}
        for item in prepared_items:
            source_pool.setdefault(str(item.get("module_type") or "custom"), []).append(item)
        enriched_candidates: list[dict[str, Any]] = []
        for block in candidate_blocks:
            module_type = str(block.get("module_type") or "custom")
            candidates = source_pool.get(module_type) or []
            content_fp = _generic_19_content_fingerprint(block.get("content"))
            source_index = next(
                (
                    index
                    for index, item in enumerate(candidates)
                    if _generic_19_content_fingerprint(item.get("content")) == content_fp
                ),
                0 if candidates else None,
            )
            source_item = candidates.pop(source_index) if source_index is not None else {}
            enriched_candidates.append(_generic_19_enrich_block_from_anchors({
                **block,
                "name": PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type),
                "anchors": source_item.get("anchors") or [],
            }))
        best_by_module: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
        for block in enriched_candidates:
            module_type = str(block.get("module_type") or "custom")
            if module_type not in PROMPT_BLOCK_GENERIC_MODULE_LABELS:
                continue
            detail_rank = _generic_19_block_quality_rank(block)
            current = best_by_module.get(module_type)
            if current is None or detail_rank > current[0]:
                best_by_module[module_type] = (detail_rank, block)
        ordered_blocks = _generic_19_dedupe_blocks([
            best_by_module[module_type][1]
            for module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS
            if module_type in best_by_module
        ])
        if has_full_blocks or has_blueprint_anchors:
            ordered_blocks = _generic_19_apply_source_geometry(ordered_blocks, source_geometry)
        if not ordered_blocks:
            raise ValueError("图片分析完成，但没有得到高保真模块范围内的素材")
        quality = _generic_19_prompt_block_quality(
            ordered_blocks,
            resolved_type,
            candidate_blocks=enriched_candidates,
            raw_blocks=prepared_items,
            type_confidence=str(blueprint.get("type_confidence") or "medium"),
        )
        return ordered_blocks, resolved_type, quality

    def request_same_provider(task_prompt: str) -> tuple[str, str]:
        if provider_id == "chatgpt_pool":
            return _chatgpt_pool_image_json_reply(
                task_prompt,
                PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM,
                image_urls,
            )
        raw_reply = _call_prompt_provider_image_json(
            provider_id,
            task_prompt,
            PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM,
            image_urls,
            model,
            reasoning_effort,
        )
        return raw_reply, model

    if provider_id == "chatgpt_pool":
        raw_text, model = request_same_provider(prompt)
        reasoning_effort = ""
    else:
        try:
            raw_text, _ = request_same_provider(prompt)
        except Exception as exc:
            if not _should_fallback_prompt_chat_to_pool(original_provider_id, exc):
                raise
            raw_text, fallback_model, fallback_warning = _fallback_prompt_image_analysis_to_pool(
                prompt,
                PROMPT_BLOCK_IMAGE_GENERIC_19_SYSTEM,
                image_urls,
                exc,
            )
            provider_id = "chatgpt_pool"
            model = fallback_model
            reasoning_effort = ""
            warning = fallback_warning

    detail_retry_attempted = False
    detail_retry_applied = False
    detail_retry_modules: list[str] = []
    try:
        blocks, resolved_type, quality = parse_blocks(raw_text)
    except Exception as parse_error:
        detail_retry_attempted = True
        format_repair_prompt = "\n".join([
            prompt,
            "上一轮响应无法解析为完整的高保真视觉蓝图。请重新查看同一张图片，返回完整的 primary_type、type_confidence、visual_blueprint 和 blocks JSON。",
            "每个 blocks 项必须引用 visual_blueprint.anchors；不要只补写 content。",
            f"解析问题：{parse_error}",
            f"上一轮响应仅供修正格式参考：\n{str(raw_text or '')[:9000]}",
        ])
        repaired_raw_text, repaired_model = request_same_provider(format_repair_prompt)
        blocks, resolved_type, quality = parse_blocks(repaired_raw_text)
        model = repaired_model
        detail_retry_applied = True
        detail_retry_modules = [str(block.get("module_type") or "") for block in blocks]

    if quality.get("needs_retry"):
        detail_retry_attempted = True
        repair_module_types = [
            module_type
            for module_type in (quality.get("repair_modules") or [])
            if module_type in PROMPT_BLOCK_GENERIC_MODULE_LABELS
        ]
        initial_blocks = [
            {
                "name": block.get("name"),
                "module_type": block.get("module_type"),
                "anchors": block.get("anchors") or [],
                "content": block.get("content"),
                "compact_content": block.get("compact_content"),
            }
            for block in blocks
        ]
        repair_prompt = "\n".join([
            prompt,
            "下面是首轮冻结事实基线。不要重做整图，不要改写未列入 repair_modules 的模块。",
            "只返回 JSON：{\"primary_type\":\"...\",\"type_confidence\":\"...\",\"repair_modules\":[...]}。",
            "每个 repair_modules 项必须带完整 anchors；同 target+attribute 与首轮冲突时，以首轮高置信/critical 锚点为准，只能增加图片可见的新锚点。",
            "禁止为了更长而替换主体数量、年龄感、脸/物体几何、体型体量、服装或产品类别、构图裁切、镜头、光向、主色、材质和背景地标。",
            "需要修复的模块：" + "、".join(
                PROMPT_BLOCK_GENERIC_MODULE_LABELS.get(module_type, module_type)
                for module_type in repair_module_types
            ),
            "需要修复的问题：\n- " + "\n- ".join((quality.get("issues") or ["视觉锚点覆盖不足"])[:14]),
            "首轮冻结事实基线 JSON：\n" + json.dumps(
                {
                    "primary_type": resolved_type,
                    "type_confidence": quality.get("type_confidence"),
                    "protected_modules": quality.get("protected_modules") or [],
                    "repair_modules": repair_module_types,
                    "blocks": initial_blocks,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ])
        try:
            repaired_raw_text, repaired_model = request_same_provider(repair_prompt)
            repaired_blocks, repaired_type, _ = parse_blocks(repaired_raw_text)
            merged_blocks, merged_type, merged_quality, applied_modules = _merge_generic_19_repaired_blocks(
                blocks,
                resolved_type,
                quality,
                repaired_blocks,
                repaired_type,
            )
            if applied_modules:
                blocks = merged_blocks
                resolved_type = merged_type
                quality = merged_quality
                model = repaired_model
                detail_retry_applied = True
                detail_retry_modules = list(dict.fromkeys([*detail_retry_modules, *applied_modules]))
        except Exception as repair_error:
            print(f"⚠️ Generic 19 image block anchor repair kept first result: {repair_error}")

    public_blocks = [
        {key: value for key, value in block.items() if key not in {"anchors", "anchor_ids", "evidence"}}
        for block in blocks
    ]
    result = {
        "ok": True,
        "mode": "image",
        "blocks": public_blocks,
        "primary_type": resolved_type,
        "analysis_id": f"image_blocks_{int(time.time())}_{os.urandom(3).hex()}",
        "provider": provider_id,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "latency_seconds": round(time.time() - started, 2),
        "source_geometry": source_geometry,
        "anchor_coverage": quality.get("anchor_coverage"),
        "fidelity_score": quality.get("anchor_coverage"),
        "fidelity_metrics": {
            "anchor_count": quality.get("anchor_count"),
            "critical_anchor_count": quality.get("critical_anchor_count"),
            "negative_pair_count": quality.get("negative_pair_count"),
            "distinct_anchor_attributes": quality.get("distinct_anchor_attributes") or [],
            "module_count": quality.get("module_count"),
            "type_confidence": quality.get("type_confidence"),
            "remaining_issues": quality.get("issues") or [],
        },
        "detail_retry_attempted": detail_retry_attempted,
        "detail_retry_applied": detail_retry_applied,
        "detail_retry_modules": detail_retry_modules,
    }
    rule_snapshot = _split_rule_snapshot(split_rule)
    if rule_snapshot:
        result["split_rule"] = rule_snapshot
    if warning:
        result["warning"] = warning
        result["fallback"] = "chatgpt_pool_multimodal_chat"
    _store_generic_19_cached_result(cache_key, result)
    return result


def extract_reusable_prompt_blocks_from_image(
    message: str,
    images: list[Any],
    primary_type: str = "",
    options: dict[str, Any] | None = None,
    split_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze an uploaded image and convert the visual evidence into reusable blocks."""
    if str((split_rule or {}).get("id") or "").strip() == "generic_19":
        return _extract_generic_19_prompt_blocks_from_image(message, images, primary_type, options, split_rule)
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
