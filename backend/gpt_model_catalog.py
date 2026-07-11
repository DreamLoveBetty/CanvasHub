#!/usr/bin/env python3
"""Account-scoped GPT model discovery for the desktop generation routes."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .app_config import (
    DEFAULT_GPT_IMAGE_MAIN_MODEL,
    DEFAULT_MANAGED_CODEX_OAUTH_API_BASE,
    get_chatgpt_pool_config,
    get_gpt_provider_config,
    get_third_party_image_config,
)
from .managed_codex_oauth import (
    get_auth_status as get_managed_codex_oauth_status,
    get_provider_env as get_managed_codex_provider_env,
    refresh_managed_auth,
)


MODEL_CATALOG_TTL_SECONDS = 300
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DEFAULT_CODEX_CLIENT_VERSION = "0.144.0"
DEFAULT_POOL_MODEL = "gpt-5-5"
CODEX_IMAGE_ENGINE_ID = "gpt-image-2"
CODEX_FREE_IMAGE_PLANS = frozenset({"free", "free_workspace"})
CODEX_FALLBACK_MODELS = (
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
)
CODEX_MODEL_LABELS = {
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
}

_CACHE_LOCK = threading.RLock()
_ROUTE_CACHE: dict[str, dict[str, Any]] = {}
_CLIENT_VERSION_CACHE: tuple[float, str] = (0.0, "")


def normalize_model_id(value: Any, fallback: str = DEFAULT_GPT_IMAGE_MAIN_MODEL) -> str:
    model = str(value or "").strip()
    return model if MODEL_ID_RE.fullmatch(model) else fallback


def _resolve_model_reasoning(model: dict[str, Any] | None, requested_effort: Any) -> dict[str, Any]:
    requested = str(requested_effort or "medium").strip().lower() or "medium"
    efforts = []
    for value in ((model or {}).get("reasoning_efforts") or []):
        effort = str(value or "").strip().lower()
        if effort and effort not in efforts:
            efforts.append(effort)
    if not efforts:
        actual = "none"
    elif requested in efforts:
        actual = requested
    else:
        default = str((model or {}).get("default_reasoning_effort") or "medium").strip().lower()
        actual = default if default in efforts else ("medium" if "medium" in efforts else efforts[0])
    return {
        "requested_reasoning_effort": requested,
        "reasoning_effort": actual,
        "reasoning_adapted": actual != requested,
        "reasoning_efforts": efforts,
    }


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jwt_claims(token: str) -> dict[str, Any]:
    if str(token or "").count(".") < 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_auth_context(path: Path, api_base: str, source: str, plan_type: str = "") -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data = data if isinstance(data, dict) else {}
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    access_token = str(tokens.get("access_token") or data.get("access_token") or "").strip()
    account_id = str(tokens.get("account_id") or data.get("account_id") or "").strip()
    id_token = str(tokens.get("id_token") or data.get("id_token") or "").strip()
    claims = _jwt_claims(id_token)
    auth_claim = claims.get("https://api.openai.com/auth")
    auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
    account_id = account_id or str(auth_claim.get("chatgpt_account_id") or claims.get("account_id") or "").strip()
    plan_type = str(plan_type or auth_claim.get("chatgpt_plan_type") or "").strip().lower()
    if not access_token:
        raise RuntimeError("Codex auth file does not contain an access token")
    return {
        "access_token": access_token,
        "account_id": account_id,
        "plan_type": plan_type,
        "api_base": str(api_base or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE).rstrip("/"),
        "source": source,
        "auth_file": str(path),
    }


def _codex_auth_context() -> dict[str, str]:
    try:
        status = get_managed_codex_oauth_status()
    except Exception:
        status = {}
    if status.get("enabled") and status.get("configured"):
        provider_env = get_managed_codex_provider_env()
        path = Path(str(provider_env.get("CODEX_API_AUTH_FILE") or "")).expanduser()
        plan_type = str((status.get("account") or {}).get("chatgpt_plan_type") or "")
        return _read_auth_context(
            path,
            provider_env.get("CODEX_API_BASE") or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE,
            "managed_codex_oauth",
            plan_type,
        )

    provider = get_gpt_provider_config()
    candidates = [
        Path(str(provider.get("auth_file") or "")).expanduser() if provider.get("auth_file") else None,
        Path(str(os.environ.get("CODEX_API_AUTH_FILE") or "")).expanduser() if os.environ.get("CODEX_API_AUTH_FILE") else None,
        Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser() / "auth.json",
    ]
    for path in candidates:
        if path and path.is_file():
            return _read_auth_context(
                path,
                str(provider.get("api_base") or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE),
                "local_codex_auth",
            )
    raise RuntimeError("Codex auth account not found")


def _codex_client_version() -> str:
    global _CLIENT_VERSION_CACHE
    now = time.monotonic()
    with _CACHE_LOCK:
        if _CLIENT_VERSION_CACHE[1] and _CLIENT_VERSION_CACHE[0] > now:
            return _CLIENT_VERSION_CACHE[1]
    executable = shutil.which("codex") or "/Applications/ChatGPT.app/Contents/Resources/codex"
    version = DEFAULT_CODEX_CLIENT_VERSION
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        match = re.search(r"(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?)", completed.stdout or completed.stderr or "")
        if match:
            version = match.group(1).split("-", 1)[0]
    except Exception:
        pass
    with _CACHE_LOCK:
        _CLIENT_VERSION_CACHE = (now + 3600, version)
    return version


def _codex_headers(context: dict[str, str], client_version: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {context['access_token']}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "Originator": "codex-tui",
        "User-Agent": f"codex-tui/{client_version} (CanvasHub model discovery)",
    }
    if context.get("account_id"):
        headers["Chatgpt-Account-Id"] = context["account_id"]
    return headers


def _fetch_codex_models(context: dict[str, str]) -> list[dict[str, Any]]:
    client_version = _codex_client_version()
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        f"{context['api_base']}/models",
        params={"client_version": client_version},
        headers=_codex_headers(context, client_version),
        timeout=30,
    )
    if response.status_code == 401 and context.get("source") == "managed_codex_oauth":
        refresh_managed_auth()
        context = _codex_auth_context()
        response = session.get(
            f"{context['api_base']}/models",
            params={"client_version": client_version},
            headers=_codex_headers(context, client_version),
            timeout=30,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Codex model discovery HTTP {response.status_code}")
    data = response.json() if response.text else {}
    items = data.get("models") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("Codex model discovery response is missing models")
    return items


def _codex_image_entitlement(plan_type: str) -> dict[str, Any]:
    normalized = str(plan_type or "").strip().lower()
    blocked = normalized in CODEX_FREE_IMAGE_PLANS
    return {
        "available": not blocked,
        "status": "unavailable" if blocked else "available",
        "source": "account_plan" if normalized else "runtime_fallback",
        "plan_type": normalized or "unknown",
    }


def _normalize_codex_model(
    item: Any,
    plan_type: str,
    *,
    image_generation_available: bool,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    model_id = normalize_model_id(item.get("slug"), "")
    if not model_id:
        return None
    if str(item.get("visibility") or "list").lower() not in {"list", "visible"}:
        return None
    if item.get("supported_in_api") is False:
        return None
    modalities = [str(value) for value in (item.get("input_modalities") or [])]
    plans = [str(value).strip().lower() for value in (item.get("available_in_plans") or [])]
    if plan_type and plan_type not in {"unknown", "none"} and plans and plan_type not in plans:
        return None
    efforts = []
    for value in item.get("supported_reasoning_levels") or []:
        effort = str(value.get("effort") if isinstance(value, dict) else value or "").strip().lower()
        if effort and effort not in efforts:
            efforts.append(effort)
    return {
        "id": model_id,
        "label": CODEX_MODEL_LABELS.get(model_id) or str(item.get("display_name") or model_id).strip() or model_id,
        "description": str(item.get("description") or "").strip(),
        "reasoning_efforts": efforts,
        "default_reasoning_effort": str(item.get("default_reasoning_level") or "medium").strip().lower(),
        "input_modalities": modalities or ["text"],
        "supports_image_input": "image" in modalities,
        "priority": int(item.get("priority") or 999),
        "model_role": "responses_main_model",
        "image_generation": bool(image_generation_available),
        "image_generation_source": "account_plan",
        "minimal_client_version": str(item.get("minimal_client_version") or "").strip(),
        "verified": True,
    }


def _legacy_codex_route(error: str = "") -> dict[str, Any]:
    models = [
        {
            "id": model_id,
            "label": CODEX_MODEL_LABELS.get(model_id, model_id),
            "description": "",
            "reasoning_efforts": ["low", "medium", "high", "xhigh"],
            "default_reasoning_effort": "medium",
            "input_modalities": ["text", "image"],
            "supports_image_input": True,
            "model_role": "responses_main_model",
            "image_generation": False,
            "image_generation_source": "unverified_fallback",
            "verified": False,
        }
        for model_id in CODEX_FALLBACK_MODELS
    ]
    configured = normalize_model_id(get_gpt_provider_config().get("image_main_model"))
    ids = {item["id"] for item in models}
    default_model = configured if configured in ids else DEFAULT_GPT_IMAGE_MAIN_MODEL
    return {
        "id": "codex",
        "label": "本地 Codex",
        "available": False,
        "models": models,
        "default_model": default_model,
        "model_role": "responses_main_model",
        "model_field_label": "主模型",
        "image_engine": {
            "id": CODEX_IMAGE_ENGINE_ID,
            "label": "GPT Image 2",
            "available": False,
            "direct_endpoint": "/images/generations",
            "fallback": "responses_image_generation",
        },
        "source": "legacy_fallback",
        "warning": str(error or "Codex model discovery unavailable")[:300],
    }


def _codex_cache_key(context: dict[str, str]) -> str:
    return "codex:" + hashlib.sha256(
        f"{context.get('auth_file')}:{context.get('access_token')}".encode("utf-8")
    ).hexdigest()


def _discover_codex_route(context: dict[str, str] | None = None) -> tuple[str, dict[str, Any]]:
    try:
        context = context or _codex_auth_context()
        cache_key = _codex_cache_key(context)
        raw_models = _fetch_codex_models(context)
        entitlement = _codex_image_entitlement(context.get("plan_type", ""))
        models = [
            model
            for model in (
                _normalize_codex_model(
                    item,
                    context.get("plan_type", ""),
                    image_generation_available=bool(entitlement["available"]),
                )
                for item in raw_models
            )
            if model
        ]
        models.sort(key=lambda item: (int(item.get("priority") or 999), item["label"].lower()))
        if not models:
            raise RuntimeError("Codex account returned no selectable API models")
        model_ids = {item["id"] for item in models}
        configured = normalize_model_id(get_gpt_provider_config().get("image_main_model"))
        default_model = configured if configured in model_ids else models[0]["id"]
        return cache_key, {
            "id": "codex",
            "label": "本地 Codex",
            "available": bool(entitlement["available"]),
            "models": models,
            "default_model": default_model,
            "model_role": "responses_main_model",
            "model_field_label": "主模型",
            "image_engine": {
                "id": CODEX_IMAGE_ENGINE_ID,
                "label": "GPT Image 2",
                "available": bool(entitlement["available"]),
                "availability_source": entitlement["source"],
                "direct_endpoint": "/images/generations",
                "fallback": "responses_image_generation",
            },
            "source": "codex_account_models",
            "account_plan": context.get("plan_type") or "unknown",
            "client_version": _codex_client_version(),
            "warning": "当前 Codex 免费计划不提供图片生成权限" if not entitlement["available"] else "",
        }
    except Exception as exc:
        return "codex:fallback", _legacy_codex_route(str(exc))


def _discover_pool_route(force: bool = False) -> tuple[str, dict[str, Any]]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    cache_key = f"chatgpt_pool:{cfg.get('base_url')}"
    if not cfg.get("enabled"):
        return cache_key, {
            "id": "chatgpt_pool",
            "label": "账号池 API",
            "available": False,
            "models": [],
            "default_model": DEFAULT_POOL_MODEL,
            "model_role": "web_main_model",
            "model_field_label": "主模型",
            "image_engine": {
                "id": "chatgpt-image",
                "label": "ChatGPT Image",
                "available": False,
            },
            "source": "disabled",
            "warning": "ChatGPT account pool is disabled",
        }
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(
            f"{str(cfg.get('base_url') or '').rstrip('/')}/models",
            params={"refresh": "true" if force else "false"},
            headers={"Authorization": f"Bearer {cfg.get('auth_key') or ''}", "Accept": "application/json"},
            timeout=35,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"account-pool model discovery HTTP {response.status_code}")
        data = response.json() if response.text else {}
        models = []
        for item in ((data.get("models") or []) if isinstance(data, dict) else []):
            if not isinstance(item, dict):
                continue
            model_id = normalize_model_id(item.get("id"), "")
            if not model_id:
                continue
            models.append({
                "id": model_id,
                "label": str(item.get("label") or model_id),
                "description": str(item.get("description") or ""),
                "reasoning_efforts": list(item.get("reasoning_efforts") or []),
                "reasoning_type": str(item.get("reasoning_type") or "none"),
                "model_role": "web_main_model",
                "image_generation": True,
                "verified": True,
                "available_accounts": int(item.get("available_accounts") or 0),
                "account_count": int(item.get("account_count") or 0),
            })
        default_model = normalize_model_id(data.get("default_model"), DEFAULT_POOL_MODEL)
        return cache_key, {
            "id": "chatgpt_pool",
            "label": "账号池 API",
            "available": bool(models),
            "models": models,
            "default_model": default_model,
            "model_role": "web_main_model",
            "model_field_label": "主模型",
            "image_engine": {
                "id": "chatgpt-image",
                "label": "ChatGPT Image",
                "available": bool(models),
            },
            "source": str(data.get("source") or "chatgpt_web_models"),
            "account_count": int(data.get("account_count") or 0),
            "probed_accounts": int(data.get("probed_accounts") or 0),
            "failed_accounts": int(data.get("failed_accounts") or 0),
            "warning": "" if models else "No account-pool Web models were returned",
        }
    except Exception as exc:
        configured = normalize_model_id(cfg.get("generation_model"), DEFAULT_POOL_MODEL)
        if configured in {"gpt-image-2", "gpt-5-3", "auto"}:
            configured = DEFAULT_POOL_MODEL
        return cache_key, {
            "id": "chatgpt_pool",
            "label": "账号池 API",
            "available": False,
            "models": [{
                "id": configured,
                "label": configured,
                "description": "",
                "reasoning_efforts": [],
                "model_role": "web_main_model",
                "image_generation": False,
                "verified": False,
            }],
            "default_model": configured,
            "model_role": "web_main_model",
            "model_field_label": "主模型",
            "image_engine": {
                "id": "chatgpt-image",
                "label": "ChatGPT Image",
                "available": False,
            },
            "source": "configured_fallback",
            "warning": str(exc)[:300],
        }


def _third_party_route() -> dict[str, Any]:
    cfg = get_third_party_image_config()
    model = normalize_model_id(cfg.get("model"), "gpt-image-2")
    return {
        "id": "third_party_image_api",
        "label": "第三方 API",
        "available": bool(cfg.get("enabled") or cfg.get("api_key")),
        "models": [{
            "id": model,
            "label": model,
            "description": "",
            "reasoning_efforts": [],
            "model_role": "image_model",
            "image_generation": True,
            "verified": bool(cfg.get("api_key")),
        }],
        "default_model": model,
        "model_role": "image_model",
        "model_field_label": "生图模型",
        "image_engine": {
            "id": model,
            "label": model,
            "available": bool(cfg.get("enabled") or cfg.get("api_key")),
        },
        "source": "third_party_config",
        "warning": "",
    }


def _cached_route(cache_key: str) -> dict[str, Any] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _ROUTE_CACHE.get(cache_key)
        if cached and float(cached.get("expires_at") or 0) > now:
            return dict(cached["payload"])
    return None


def _store_route(cache_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _CACHE_LOCK:
        _ROUTE_CACHE[cache_key] = {
            "expires_at": time.monotonic() + MODEL_CATALOG_TTL_SECONDS,
            "payload": dict(payload),
        }
    return payload


def discover_codex_route(force: bool = False) -> dict[str, Any]:
    try:
        context = _codex_auth_context()
        cache_key = _codex_cache_key(context)
        if not force:
            cached = _cached_route(cache_key)
            if cached:
                return cached
        cache_key, payload = _discover_codex_route(context)
    except Exception as exc:
        cache_key, payload = "codex:fallback", _legacy_codex_route(str(exc))
        if not force:
            cached = _cached_route(cache_key)
            if cached:
                return cached
    return _store_route(cache_key, payload)


def discover_pool_route(force: bool = False) -> dict[str, Any]:
    cache_key = f"chatgpt_pool:{get_chatgpt_pool_config().get('base_url')}"
    if not force:
        cached = _cached_route(cache_key)
        if cached:
            return cached
    discovered_key, payload = _discover_pool_route(force=force)
    return _store_route(discovered_key, payload)


def get_gpt_model_catalog(force: bool = False) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="gpt-model-catalog") as executor:
        codex_future = executor.submit(discover_codex_route, force)
        pool_future = executor.submit(discover_pool_route, force)
        codex = codex_future.result()
        pool = pool_future.result()
    third_party = _third_party_route()
    return {
        "ok": True,
        "generated_at": _utc_iso(),
        "cache_ttl_seconds": MODEL_CATALOG_TTL_SECONDS,
        "routes": {
            "codex": codex,
            "chatgpt_pool": pool,
            "third_party_image_api": third_party,
        },
    }


def resolve_route_model(
    route: str,
    requested_model: Any,
    force: bool = False,
    *,
    reasoning_effort: Any = None,
) -> dict[str, Any]:
    route_id = str(route or "codex").strip().lower()
    if route_id not in {"codex", "chatgpt_pool", "third_party_image_api"}:
        route_id = "codex"
    if route_id == "codex":
        route_catalog = discover_codex_route(force=force)
    elif route_id == "chatgpt_pool":
        route_catalog = discover_pool_route(force=force)
    else:
        route_catalog = _third_party_route()
    requested = normalize_model_id(requested_model)
    if route_id == "chatgpt_pool" and requested == "gpt-image-2":
        requested = DEFAULT_POOL_MODEL
    model_ids = [str(item.get("id") or "") for item in (route_catalog.get("models") or [])]
    actual = requested if requested in model_ids else str(route_catalog.get("default_model") or "")
    if actual not in model_ids and model_ids:
        actual = model_ids[0]
    actual = normalize_model_id(actual, requested)
    model = next(
        (item for item in (route_catalog.get("models") or []) if str(item.get("id") or "") == actual),
        None,
    )
    result = {
        "route": route_id,
        "requested_model": normalize_model_id(requested_model),
        "model": actual,
        "adapted": actual != normalize_model_id(requested_model),
        "source": route_catalog.get("source") or "",
        "available": bool(route_catalog.get("available")),
        "warning": str(route_catalog.get("warning") or ""),
        "model_role": str(route_catalog.get("model_role") or ""),
        "image_engine": dict(route_catalog.get("image_engine") or {}),
    }
    result.update(_resolve_model_reasoning(model, reasoning_effort))
    return result


def codex_fallback_models(requested_model: Any) -> list[str]:
    requested = normalize_model_id(requested_model)
    try:
        route = discover_codex_route(force=False)
        if not route.get("available"):
            return []
        model_ids = [
            str(item.get("id") or "")
            for item in (route.get("models") or [])
            if item.get("image_generation") is not False
        ]
        default_model = str(route.get("default_model") or DEFAULT_GPT_IMAGE_MAIN_MODEL)
    except Exception:
        model_ids = []
        default_model = DEFAULT_GPT_IMAGE_MAIN_MODEL
    ordered = [
        model
        for model in (default_model, DEFAULT_GPT_IMAGE_MAIN_MODEL, *model_ids)
        if model in model_ids
    ]
    result = []
    for model in ordered:
        model = normalize_model_id(model, "")
        if model and model != requested and model not in result:
            result.append(model)
    return result
