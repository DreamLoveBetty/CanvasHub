from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import re
import threading
import time
from typing import Any

from .account_store import DISABLED_STATUS, ERROR_STATUS, AccountStore
from .openai_backend import OpenAIBackend


MODEL_CACHE_TTL_SECONDS = 300
WEB_IMAGE_MODEL_ALIAS = "gpt-image-2"
DEFAULT_WEB_IMAGE_MODEL = "gpt-5-5"
MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
NON_MODEL_PICKER_SLUGS = frozenset({
    "auto",
    "research",
    "deep-research",
    "deep_research",
})
UNAVAILABLE_PRESET_TYPES = frozenset({"disabled", "hidden", "unavailable"})

_CACHE_LOCK = threading.RLock()
_ACCOUNT_MODEL_CACHE: dict[str, dict[str, Any]] = {}


def normalize_web_model_id(value: Any, fallback: str = WEB_IMAGE_MODEL_ALIAS) -> str:
    model = str(value or "").strip()
    if model == WEB_IMAGE_MODEL_ALIAS:
        return model
    return model if MODEL_ID_RE.fullmatch(model) else fallback


def web_model_slug(value: Any) -> str:
    model = normalize_web_model_id(value)
    return DEFAULT_WEB_IMAGE_MODEL if model == WEB_IMAGE_MODEL_ALIAS else model


def _cache_key(access_token: str) -> str:
    return hashlib.sha256(str(access_token or "").encode("utf-8")).hexdigest()


def _catalog_model_slug(value: Any) -> str:
    model_id = str(value or "").strip()
    return model_id if MODEL_ID_RE.fullmatch(model_id) else ""


def _picker_model_ids(data: Any) -> tuple[list[str], bool]:
    """Read account-selectable model slugs from the Web model picker's routing metadata."""
    if not isinstance(data, dict):
        return [], False

    ordered: list[str] = []
    declared = False

    def add(value: Any) -> None:
        nonlocal declared
        model_id = _catalog_model_slug(value)
        if not model_id:
            return
        declared = True
        if model_id in NON_MODEL_PICKER_SLUGS or model_id in ordered:
            return
        ordered.append(model_id)

    for version in data.get("versions") or []:
        if not isinstance(version, dict) or version.get("enabled") is False:
            continue
        for preset in version.get("intelligence_presets") or []:
            if not isinstance(preset, dict):
                continue
            preset_type = str(preset.get("preset_type") or "available").strip().lower()
            if preset_type in UNAVAILABLE_PRESET_TYPES:
                continue
            add(preset.get("model_slug"))
        for model_id in version.get("slugs") or []:
            add(model_id)

    for category in data.get("categories") or []:
        if not isinstance(category, dict):
            continue
        for model_id in category.get("supported_models") or []:
            add(model_id)
        add(category.get("default_model"))

    return ordered, declared


def _normalized_model(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    model_id = _catalog_model_slug(item.get("slug") or item.get("id") or item.get("model_slug"))
    if not model_id or model_id in NON_MODEL_PICKER_SLUGS:
        return None
    enabled_tools = [str(value) for value in (item.get("enabled_tools") or [])]
    if enabled_tools and "image_gen_tool_enabled" not in enabled_tools:
        return None
    reasoning_type = str(item.get("reasoning_type") or "none").strip() or "none"
    return {
        "id": model_id,
        "label": str(item.get("title") or item.get("name") or model_id).strip() or model_id,
        "description": str(item.get("description") or "").strip(),
        "reasoning_type": reasoning_type,
        "reasoning_efforts": [
            str(value).strip()
            for value in (item.get("thinking_efforts") or [])
            if str(value).strip()
        ],
        "image_generation": True,
    }


def account_model_catalog(backend: Any, force: bool = False) -> dict[str, Any]:
    token = str(getattr(backend, "access_token", "") or "")
    key = _cache_key(token) if token else ""
    now = time.monotonic()
    if key and not force:
        with _CACHE_LOCK:
            cached = _ACCOUNT_MODEL_CACHE.get(key)
            if cached and float(cached.get("expires_at") or 0) > now:
                return dict(cached["payload"])

    if not hasattr(backend, "fetch_model_catalog"):
        return {
            "models": [],
            "default_model": DEFAULT_WEB_IMAGE_MODEL,
            "source": "unavailable",
        }

    data = backend.fetch_model_catalog()
    picker_model_ids, picker_is_authoritative = _picker_model_ids(data)
    picker_model_id_set = set(picker_model_ids)
    models = []
    seen = set()
    for raw in ((data.get("models") or []) if isinstance(data, dict) else []):
        model = _normalized_model(raw)
        if (
            not model
            or model["id"] in seen
            or (picker_is_authoritative and model["id"] not in picker_model_id_set)
        ):
            continue
        seen.add(model["id"])
        models.append(model)

    advertised_default = str(data.get("default_model_slug") or "").strip() if isinstance(data, dict) else ""
    model_ids = {item["id"] for item in models}
    default_model = next(
        (
            candidate
            for candidate in (advertised_default, *picker_model_ids, DEFAULT_WEB_IMAGE_MODEL, "gpt-5-5")
            if candidate in model_ids
        ),
        models[0]["id"] if models else DEFAULT_WEB_IMAGE_MODEL,
    )
    payload = {
        "models": models,
        "default_model": default_model,
        "source": "chatgpt_web_models",
        "model_picker_version": data.get("model_picker_version") if isinstance(data, dict) else None,
    }
    if key:
        with _CACHE_LOCK:
            _ACCOUNT_MODEL_CACHE[key] = {
                "expires_at": now + MODEL_CACHE_TTL_SECONDS,
                "payload": dict(payload),
            }
    return payload


def _fallback_model(catalog: dict[str, Any], excluded: set[str] | None = None) -> str:
    excluded = {str(value or "") for value in (excluded or set())}
    model_ids = [str(item.get("id") or "") for item in (catalog.get("models") or [])]
    for candidate in (
        str(catalog.get("default_model") or ""),
        DEFAULT_WEB_IMAGE_MODEL,
        "gpt-5-5",
        *model_ids,
    ):
        if candidate and candidate not in excluded and candidate in model_ids:
            return candidate
    return DEFAULT_WEB_IMAGE_MODEL


def resolve_account_image_model(
    backend: Any,
    requested_model: Any,
    *,
    force: bool = False,
    excluded: set[str] | None = None,
) -> tuple[str, str, bool]:
    if not hasattr(backend, "fetch_model_catalog"):
        requested = normalize_web_model_id(requested_model)
        return requested, requested, False
    requested = web_model_slug(requested_model)
    try:
        catalog = account_model_catalog(backend, force=force)
    except Exception:
        if force and requested != DEFAULT_WEB_IMAGE_MODEL and DEFAULT_WEB_IMAGE_MODEL not in (excluded or set()):
            return DEFAULT_WEB_IMAGE_MODEL, requested, True
        return requested, requested, False
    model_ids = {str(item.get("id") or "") for item in (catalog.get("models") or [])}
    excluded = {str(value or "") for value in (excluded or set())}
    if requested in model_ids and requested not in excluded:
        return requested, requested, False
    actual = _fallback_model(catalog, excluded=excluded)
    return actual, requested, actual != requested


def is_model_unavailable_error(error: Exception | str) -> bool:
    text = str(error or "").strip().lower()
    markers = (
        "model is not available",
        "model is unavailable",
        "model is not supported",
        "unsupported model",
        "invalid model",
        "model_not_found",
        "model_access_denied",
        "does not have access to model",
        "does not exist or you do not have access",
    )
    return bool(text and any(marker in text for marker in markers))


def discover_pool_models(store: AccountStore, force: bool = False) -> dict[str, Any]:
    accounts = [
        row
        for row in store.list_private_accounts()
        if str(row.get("access_token") or "")
        and str(row.get("status") or "") not in {DISABLED_STATUS, ERROR_STATUS}
    ]
    if not accounts:
        return {
            "ok": True,
            "models": [],
            "default_model": DEFAULT_WEB_IMAGE_MODEL,
            "source": "chatgpt_web_models",
            "account_count": 0,
            "probed_accounts": 0,
            "failed_accounts": 0,
        }

    catalogs: list[dict[str, Any]] = []
    failed = 0
    workers = max(1, min(4, len(accounts)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="chatgpt-pool-models") as executor:
        futures = {
            executor.submit(
                account_model_catalog,
                OpenAIBackend(str(row.get("access_token") or ""), timeout_seconds=60),
                force,
            ): row
            for row in accounts
        }
        for future in as_completed(futures):
            try:
                catalog = future.result()
                if catalog.get("models"):
                    catalogs.append(catalog)
                else:
                    failed += 1
            except Exception:
                failed += 1

    counts: dict[str, int] = {}
    model_by_id: dict[str, dict[str, Any]] = {}
    for catalog in catalogs:
        account_ids = set()
        for model in catalog.get("models") or []:
            model_id = str(model.get("id") or "")
            if not model_id or model_id in account_ids:
                continue
            account_ids.add(model_id)
            counts[model_id] = counts.get(model_id, 0) + 1
            model_by_id.setdefault(model_id, dict(model))

    successful = len(catalogs)
    intersection = {model_id for model_id, count in counts.items() if successful and count == successful}
    selected_ids = intersection or set(model_by_id)
    models = []
    for model_id, model in model_by_id.items():
        if model_id not in selected_ids:
            continue
        model["available_accounts"] = counts.get(model_id, 0)
        model["account_count"] = successful
        models.append(model)
    models.sort(key=lambda item: (0 if item["id"] == DEFAULT_WEB_IMAGE_MODEL else 1, item["label"].lower()))
    model_ids = {item["id"] for item in models}
    default_model = next(
        (candidate for candidate in (DEFAULT_WEB_IMAGE_MODEL, "gpt-5-5") if candidate in model_ids),
        models[0]["id"] if models else DEFAULT_WEB_IMAGE_MODEL,
    )
    return {
        "ok": True,
        "models": models,
        "default_model": default_model,
        "source": "chatgpt_web_models",
        "account_count": len(accounts),
        "probed_accounts": successful,
        "failed_accounts": failed,
        "intersection": bool(intersection),
        "cache_ttl_seconds": MODEL_CACHE_TTL_SECONDS,
    }
