#!/usr/bin/env python3
"""Project-local configuration helpers."""

from __future__ import annotations

import json
import os
import re
import secrets
import socket
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
SOURCE_BASE_DIR = BACKEND_DIR.parent
BASE_DIR = Path(os.environ.get("CANVASHUB_RESOURCE_DIR") or SOURCE_BASE_DIR).expanduser().resolve()
_APP_DATA_OVERRIDE = str(os.environ.get("CANVASHUB_DATA_DIR") or "").strip()
APP_DATA_DIR = Path(_APP_DATA_OVERRIDE).expanduser().resolve() if _APP_DATA_OVERRIDE else BASE_DIR
DESKTOP_DATA_MODE = bool(_APP_DATA_OVERRIDE)
DEFAULT_SETTINGS_PATH = APP_DATA_DIR / "settings.json"
DEFAULT_IMAGE_ARCHIVE_DIR = APP_DATA_DIR / ("archive" if DESKTOP_DATA_MODE else "data/archive")
DEFAULT_SOURCE_IMAGE_DIR = APP_DATA_DIR / ("source_images" if DESKTOP_DATA_MODE else "data/source_images")
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_PUBLIC_SERVER_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 18463
DEFAULT_GPT_IMAGE_MAIN_MODEL = "gpt-5.5"
DEFAULT_GPT_REASONING_EFFORT = "medium"
DEFAULT_GPT_TRANSPORT_MODE = "stream_then_nonstream"
DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS = 600
DEFAULT_PROMPT_SKILL_PROVIDER = "gpt_oauth"
DEFAULT_PROMPT_SKILL_ID = "image_prompt_v7"
DEFAULT_PROMPT_SKILL_REASONING_EFFORT = "medium"
DEFAULT_PROMPT_SKILL_OUTPUT = "full_prompt"
DEFAULT_CHATGPT_POOL_ENABLED = True
DEFAULT_CHATGPT_POOL_BASE_URL = "http://127.0.0.1:18080"
DEFAULT_CHATGPT_POOL_MODEL = "gpt-5-5"
DEFAULT_CHATGPT_POOL_TIMEOUT_SECONDS = 900
DEFAULT_MANAGED_CODEX_OAUTH_ENABLED = True
DEFAULT_MANAGED_CODEX_OAUTH_API_BASE = "https://chatgpt.com/backend-api/codex"
DEFAULT_MANAGED_CODEX_OAUTH_AUTH_FILE = APP_DATA_DIR / ("auth/managed_codex/auth.json" if DESKTOP_DATA_MODE else "data/managed_codex_oauth/auth.json")
DEFAULT_MANAGED_CODEX_OAUTH_ACCOUNTS_DIR = APP_DATA_DIR / ("auth/managed_codex/accounts" if DESKTOP_DATA_MODE else "data/managed_codex_oauth/accounts")
DEFAULT_MANAGED_CODEX_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_NANO_BANANA_API_BASE_URL = ""
DEFAULT_YUNWU_API_BASE_URL = DEFAULT_NANO_BANANA_API_BASE_URL
DEFAULT_THIRD_PARTY_IMAGE_API_BASE_URL = ""
DEFAULT_THIRD_PARTY_IMAGE_MODEL = "gpt-image-2"
DEFAULT_THIRD_PARTY_IMAGE_GENERATE_PATH = "/v1/images/generations"
DEFAULT_THIRD_PARTY_IMAGE_EDIT_PATH = "/v1/images/edits"
DEFAULT_THIRD_PARTY_IMAGE_FORMAT = "png"
DEFAULT_THIRD_PARTY_IMAGE_TIMEOUT_SECONDS = 900
GPT_IMAGE_MAIN_MODELS = {
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
}
GPT_REASONING_EFFORTS = {
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}
GPT_TRANSPORT_MODES = {
    "stream",
    "nonstream",
    "stream_then_nonstream",
}


def _path_from_env(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if raw:
        return Path(raw).expanduser()
    return default


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [_as_str(item) for item in value if _as_str(item)]
    text = _as_str(value)
    return [text] if text else []


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _as_str(value).lower()
    if text in ("1", "true", "yes", "on", "enabled"):
        return True
    if text in ("0", "false", "no", "off", "disabled"):
        return False
    return default


def _as_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _detect_local_telegram_proxy() -> str:
    for port in (7897, 7890):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        try:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return f"http://127.0.0.1:{port}"
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
    return ""


def load_app_settings() -> dict[str, Any]:
    """Load project settings without exposing secrets or raising on bad JSON."""
    return _load_json(_path_from_env("APP_SETTINGS_PATH", DEFAULT_SETTINGS_PATH))


def save_app_settings(settings: dict[str, Any]) -> None:
    """Atomically save project settings.json while preserving unknown keys."""
    path = _path_from_env("APP_SETTINGS_PATH", DEFAULT_SETTINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(temp_name, path)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except Exception:
            pass


def update_app_settings_section(section: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Update one top-level settings section and return the sanitized section."""
    settings = load_app_settings()
    current = settings.get(section) if isinstance(settings.get(section), dict) else {}
    updated = {**current, **patch}
    settings[section] = updated
    save_app_settings(settings)
    return updated


def _telegram_settings() -> dict[str, Any]:
    settings = load_app_settings().get("telegram") or {}
    return settings if isinstance(settings, dict) else {}


def get_miniapp_access_password() -> str:
    env_password = (
        os.environ.get("MINIAPP_ACCESS_PASSWORD")
        or os.environ.get("MINIAPP_AUTH_PASSWORD")
        or ""
    ).strip()
    if env_password:
        return env_password
    return _as_str(load_app_settings().get("miniapp_access_password"))


def get_telegram_config() -> dict[str, str]:
    """Return Telegram delivery config using env and project settings.json."""
    settings = _telegram_settings()

    bot_token = (
        os.environ.get("TELEGRAM_BOT_TOKEN")
        or os.environ.get("BOT_TOKEN")
        or _as_str(settings.get("bot_token"))
    )

    chat_id = (
        os.environ.get("CHAT_ID")
        or _as_str(settings.get("chat_id"))
    )

    proxy_url = (
        os.environ.get("TELEGRAM_PROXY_URL")
        or os.environ.get("TG_PROXY_URL")
        or _as_str(settings.get("proxy_url"))
    )
    if not proxy_url:
        proxy_url = _detect_local_telegram_proxy()

    return {
        "bot_token": _as_str(bot_token),
        "chat_id": _as_str(chat_id),
        "proxy_url": _as_str(proxy_url),
    }


def get_telegram_auth_config() -> dict[str, Any]:
    """Return Telegram WebApp auth config using project settings only."""
    telegram_cfg = get_telegram_config()
    settings = _telegram_settings()

    allowed_ids = _as_str_list(settings.get("allowed_user_ids"))

    return {
        "bot_token": telegram_cfg.get("bot_token", ""),
        "allowed_user_ids": set(allowed_ids),
    }


def get_nano_banana_api_key() -> str:
    settings = load_app_settings()
    nano_banana = settings.get("nano_banana_api") if isinstance(settings.get("nano_banana_api"), dict) else {}
    return _as_str(
        os.environ.get("NANO_BANANA_API_KEY")
        or os.environ.get("YUNWU_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or settings.get("nano_banana_api_key")
        or nano_banana.get("api_key")
        or settings.get("yunwu_api_key")
    )


def get_nano_banana_api_base_url() -> str:
    settings = load_app_settings()
    nano_banana = settings.get("nano_banana_api") if isinstance(settings.get("nano_banana_api"), dict) else {}
    return _as_str(
        os.environ.get("NANO_BANANA_API_BASE_URL")
        or os.environ.get("YUNWU_API_BASE_URL")
        or os.environ.get("GOOGLE_API_BASE_URL")
        or settings.get("nano_banana_api_base_url")
        or nano_banana.get("base_url")
        or nano_banana.get("api_url")
        or settings.get("yunwu_api_base_url")
        or DEFAULT_YUNWU_API_BASE_URL
    ).rstrip("/") or DEFAULT_YUNWU_API_BASE_URL


def get_yunwu_api_key() -> str:
    """Backward-compatible alias for the nano banana / Google-compatible API key."""
    return get_nano_banana_api_key()


def get_yunwu_api_base_url() -> str:
    """Backward-compatible alias for the nano banana / Google-compatible API URL."""
    return get_nano_banana_api_base_url()


def get_third_party_image_config() -> dict[str, Any]:
    """Return explicit third-party image API config for opt-in GPT 4K requests."""
    settings = load_app_settings()
    section = settings.get("third_party_image_api") or settings.get("third_party_gpt_image") or {}
    if not isinstance(section, dict):
        section = {}

    api_key = _as_str(
        os.environ.get("THIRD_PARTY_IMAGE_API_KEY")
        or os.environ.get("THIRD_PARTY_GPT_IMAGE_API_KEY")
        or section.get("api_key")
    )
    base_url = _as_str(
        os.environ.get("THIRD_PARTY_IMAGE_API_BASE_URL")
        or os.environ.get("THIRD_PARTY_GPT_IMAGE_BASE_URL")
        or section.get("base_url")
        or DEFAULT_THIRD_PARTY_IMAGE_API_BASE_URL
    ).rstrip("/")
    model = _as_str(
        os.environ.get("THIRD_PARTY_IMAGE_MODEL")
        or os.environ.get("THIRD_PARTY_GPT_IMAGE_MODEL")
        or section.get("model")
        or DEFAULT_THIRD_PARTY_IMAGE_MODEL
    ) or DEFAULT_THIRD_PARTY_IMAGE_MODEL
    generate_path = _as_str(section.get("generate_path") or DEFAULT_THIRD_PARTY_IMAGE_GENERATE_PATH)
    edit_path = _as_str(section.get("edit_path") or DEFAULT_THIRD_PARTY_IMAGE_EDIT_PATH)
    output_format = _as_str(section.get("format") or section.get("output_format") or DEFAULT_THIRD_PARTY_IMAGE_FORMAT).lower()
    if output_format not in {"png", "jpeg", "webp"}:
        output_format = DEFAULT_THIRD_PARTY_IMAGE_FORMAT
    timeout_seconds = _as_int(
        os.environ.get("THIRD_PARTY_IMAGE_TIMEOUT")
        or section.get("timeout_seconds")
        or section.get("timeoutSeconds"),
        DEFAULT_THIRD_PARTY_IMAGE_TIMEOUT_SECONDS,
        minimum=30,
    )
    timeout_seconds = min(1800, timeout_seconds)
    return {
        "api_key": api_key,
        "api_key_configured": bool(api_key),
        "base_url": base_url or DEFAULT_THIRD_PARTY_IMAGE_API_BASE_URL,
        "model": model,
        "generate_path": generate_path if generate_path.startswith("/") else f"/{generate_path}",
        "edit_path": edit_path if edit_path.startswith("/") else f"/{edit_path}",
        "format": output_format,
        "timeout_seconds": timeout_seconds,
    }


def _settings_paths() -> dict[str, Any]:
    paths = load_app_settings().get("paths") or {}
    return paths if isinstance(paths, dict) else {}


def _resolve_project_path(raw: Any, default: Path) -> Path:
    text = _as_str(raw)
    if not text:
        return default
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = APP_DATA_DIR / path
    return path


def _resolve_optional_project_path(raw: Any) -> Path | None:
    text = _as_str(raw)
    if not text:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = APP_DATA_DIR / path
    return path


def get_storage_config() -> dict[str, Path]:
    paths = _settings_paths()
    image_archive_dir = _resolve_project_path(
        os.environ.get("IMAGE_ARCHIVE_DIR") or paths.get("image_archive_dir"),
        DEFAULT_IMAGE_ARCHIVE_DIR,
    )
    source_image_dir = _resolve_project_path(
        os.environ.get("SOURCE_IMAGE_DIR") or paths.get("source_image_dir"),
        DEFAULT_SOURCE_IMAGE_DIR,
    )
    return {
        "image_archive_dir": image_archive_dir,
        "source_image_dir": source_image_dir,
    }


def get_server_config() -> dict[str, Any]:
    """Return bind settings. Public mode is the only path to non-loopback bind."""
    settings = load_app_settings()
    section = settings.get("server") or {}
    if not isinstance(section, dict):
        section = {}

    public_mode = _as_bool(
        os.environ.get("MINIAPP_PUBLIC_MODE")
        or os.environ.get("PUBLIC_MODE")
        or section.get("public_mode"),
        False,
    )
    port = _as_int(
        os.environ.get("PORT")
        or os.environ.get("MINIAPP_PORT")
        or section.get("port"),
        DEFAULT_SERVER_PORT,
        minimum=1,
    )
    port = min(65535, port)

    requested_host = _as_str(
        os.environ.get("HOST")
        or os.environ.get("BIND_HOST")
        or os.environ.get("MINIAPP_HOST")
        or section.get("host")
    )
    if public_mode:
        host = requested_host or DEFAULT_PUBLIC_SERVER_HOST
    else:
        host = DEFAULT_SERVER_HOST

    return {
        "host": host,
        "requested_host": requested_host,
        "port": port,
        "public_mode": public_mode,
    }


def get_database_path() -> Path:
    paths = _settings_paths()
    return _resolve_project_path(
        os.environ.get("TASKS_DB_PATH")
        or os.environ.get("TASKS_DB")
        or paths.get("tasks_db"),
        APP_DATA_DIR / "tasks.db",
    )


def _new_chatgpt_pool_auth_key() -> str:
    return "sk-local-" + secrets.token_urlsafe(32)


def get_chatgpt_pool_config(ensure_auth_key: bool = False) -> dict[str, Any]:
    """Return sidecar settings. Secret values are only included in this private helper."""
    settings = load_app_settings()
    section = settings.get("chatgpt_pool") or {}
    if not isinstance(section, dict):
        section = {}

    env_auth_key = _as_str(os.environ.get("CHATGPT_POOL_AUTH_KEY"))
    auth_key = env_auth_key or _as_str(section.get("auth_key"))
    if ensure_auth_key and not auth_key:
        auth_key = _new_chatgpt_pool_auth_key()
        section = {**section, "auth_key": auth_key}
        settings["chatgpt_pool"] = section
        save_app_settings(settings)

    base_url = _as_str(os.environ.get("CHATGPT_POOL_BASE_URL") or section.get("base_url"))
    if not base_url:
        host = _as_str(os.environ.get("CHATGPT_POOL_HOST") or section.get("host") or "127.0.0.1")
        port = _as_int(os.environ.get("CHATGPT_POOL_PORT") or section.get("port"), 18080)
        base_url = f"http://{host}:{port}"

    db_path = _resolve_project_path(
        os.environ.get("CHATGPT_POOL_DB") or section.get("db_path"),
        APP_DATA_DIR / ("chatgpt_pool/accounts.db" if DESKTOP_DATA_MODE else "data/chatgpt_pool/accounts.db"),
    )

    generation_model = _as_str(section.get("generation_model") or DEFAULT_CHATGPT_POOL_MODEL) or DEFAULT_CHATGPT_POOL_MODEL
    if generation_model in {"gpt-image-2", "gpt-5-3", "auto"}:
        generation_model = DEFAULT_CHATGPT_POOL_MODEL

    return {
        "enabled": _as_bool(os.environ.get("CHATGPT_POOL_ENABLED"), _as_bool(section.get("enabled"), DEFAULT_CHATGPT_POOL_ENABLED)),
        "base_url": base_url.rstrip("/"),
        "auth_key": auth_key,
        "auth_key_configured": bool(auth_key),
        "generation_model": generation_model,
        "timeout_seconds": _as_int(section.get("timeout_seconds"), DEFAULT_CHATGPT_POOL_TIMEOUT_SECONDS),
        "db_path": db_path,
    }


def get_chatgpt_pool_public_config() -> dict[str, Any]:
    """Return safe sidecar settings for UI/diagnostics without the Bearer key."""
    cfg = get_chatgpt_pool_config(ensure_auth_key=False)
    return {
        "enabled": bool(cfg.get("enabled")),
        "base_url": cfg.get("base_url", ""),
        "auth_key_configured": bool(cfg.get("auth_key_configured")),
        "generation_model": cfg.get("generation_model", DEFAULT_CHATGPT_POOL_MODEL),
        "timeout_seconds": cfg.get("timeout_seconds", DEFAULT_CHATGPT_POOL_TIMEOUT_SECONDS),
        "db_path": str(cfg.get("db_path") or ""),
    }


def get_managed_codex_oauth_config() -> dict[str, Any]:
    """Return project-managed Codex OAuth settings without token contents."""
    settings = load_app_settings()
    section = settings.get("managed_codex_oauth") or {}
    if not isinstance(section, dict):
        section = {}

    auth_file = _resolve_project_path(
        os.environ.get("MANAGED_CODEX_OAUTH_AUTH_FILE")
        or section.get("auth_file"),
        DEFAULT_MANAGED_CODEX_OAUTH_AUTH_FILE,
    )
    accounts_dir = _resolve_project_path(
        os.environ.get("MANAGED_CODEX_OAUTH_ACCOUNTS_DIR")
        or section.get("accounts_dir"),
        DEFAULT_MANAGED_CODEX_OAUTH_ACCOUNTS_DIR,
    )
    api_base = _as_str(
        os.environ.get("MANAGED_CODEX_OAUTH_API_BASE")
        or section.get("api_base")
        or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE
    ).rstrip("/") or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE
    redirect_uri = _as_str(
        os.environ.get("MANAGED_CODEX_OAUTH_REDIRECT_URI")
        or section.get("redirect_uri")
        or DEFAULT_MANAGED_CODEX_OAUTH_REDIRECT_URI
    ) or DEFAULT_MANAGED_CODEX_OAUTH_REDIRECT_URI

    return {
        "enabled": _as_bool(
            os.environ.get("MANAGED_CODEX_OAUTH_ENABLED"),
            _as_bool(section.get("enabled"), DEFAULT_MANAGED_CODEX_OAUTH_ENABLED),
        ),
        "auth_file": auth_file,
        "accounts_dir": accounts_dir,
        "api_base": api_base,
        "redirect_uri": redirect_uri,
    }


def get_managed_codex_oauth_public_config() -> dict[str, Any]:
    """Return safe managed Codex OAuth settings for UI/diagnostics."""
    cfg = get_managed_codex_oauth_config()
    return {
        "enabled": bool(cfg.get("enabled")),
        "auth_file": str(cfg.get("auth_file") or ""),
        "accounts_dir": str(cfg.get("accounts_dir") or ""),
        "api_base": cfg.get("api_base", DEFAULT_MANAGED_CODEX_OAUTH_API_BASE),
        "redirect_uri": cfg.get("redirect_uri", DEFAULT_MANAGED_CODEX_OAUTH_REDIRECT_URI),
    }


def get_gpt_provider_config() -> dict[str, Any]:
    """Return local gpt-image-2/Codex provider config without token contents."""
    settings = load_app_settings().get("gpt_provider") or {}
    if not isinstance(settings, dict):
        settings = {}

    auth_file = _resolve_optional_project_path(
        os.environ.get("GPT_PROVIDER_AUTH_FILE")
        or os.environ.get("CODEX_API_AUTH_FILE")
        or settings.get("auth_file")
    )
    auth_dir = _resolve_optional_project_path(
        os.environ.get("GPT_PROVIDER_AUTH_DIR")
        or os.environ.get("CODEX_API_AUTH_DIR")
        or settings.get("auth_dir")
    )
    image_main_model = _as_str(
        os.environ.get("GPT_IMAGE_MAIN_MODEL")
        or os.environ.get("GPT_PROVIDER_MAIN_MODEL")
        or settings.get("image_main_model")
        or settings.get("main_model")
        or DEFAULT_GPT_IMAGE_MAIN_MODEL
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", image_main_model):
        image_main_model = DEFAULT_GPT_IMAGE_MAIN_MODEL

    reasoning_effort = _as_str(
        os.environ.get("GPT_REASONING_EFFORT")
        or os.environ.get("GPT_PROVIDER_REASONING_EFFORT")
        or settings.get("reasoning_effort")
        or DEFAULT_GPT_REASONING_EFFORT
    ).lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = DEFAULT_GPT_REASONING_EFFORT

    transport_mode = _as_str(
        os.environ.get("GPT_PROVIDER_TRANSPORT_MODE")
        or os.environ.get("GPT_TRANSPORT_MODE")
        or settings.get("transport_mode")
        or DEFAULT_GPT_TRANSPORT_MODE
    ).lower()
    if transport_mode not in GPT_TRANSPORT_MODES:
        transport_mode = DEFAULT_GPT_TRANSPORT_MODE

    total_timeout_seconds = _as_int(
        os.environ.get("GPT_PROVIDER_TOTAL_TIMEOUT")
        or settings.get("total_timeout_seconds")
        or settings.get("totalTimeoutSeconds"),
        DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
        minimum=30,
    )
    total_timeout_seconds = min(1800, total_timeout_seconds)

    return {
        "auth_file": auth_file,
        "auth_dir": auth_dir,
        "api_base": _as_str(os.environ.get("CODEX_API_BASE") or settings.get("api_base")),
        "image_main_model": image_main_model,
        "reasoning_effort": reasoning_effort,
        "transport_mode": transport_mode,
        "total_timeout_seconds": total_timeout_seconds,
        "allowed_image_main_models": sorted(GPT_IMAGE_MAIN_MODELS),
        "allowed_reasoning_efforts": sorted(GPT_REASONING_EFFORTS),
        "allowed_transport_modes": sorted(GPT_TRANSPORT_MODES),
    }


def get_prompt_skill_config() -> dict[str, Any]:
    """Return text prompt-skill config without provider secrets."""
    settings = load_app_settings().get("prompt_skill") or {}
    if not isinstance(settings, dict):
        settings = {}

    provider = _as_str(
        os.environ.get("PROMPT_SKILL_PROVIDER")
        or settings.get("provider")
        or DEFAULT_PROMPT_SKILL_PROVIDER
    ) or DEFAULT_PROMPT_SKILL_PROVIDER
    skill = _as_str(
        os.environ.get("PROMPT_SKILL_ID")
        or settings.get("skill")
        or DEFAULT_PROMPT_SKILL_ID
    ) or DEFAULT_PROMPT_SKILL_ID
    model = _as_str(os.environ.get("PROMPT_SKILL_MODEL") or settings.get("model"))
    reasoning_effort = _as_str(
        os.environ.get("PROMPT_SKILL_REASONING_EFFORT")
        or settings.get("reasoning_effort")
        or DEFAULT_PROMPT_SKILL_REASONING_EFFORT
    ).lower()
    if reasoning_effort not in GPT_REASONING_EFFORTS:
        reasoning_effort = DEFAULT_PROMPT_SKILL_REASONING_EFFORT
    default_output = _as_str(
        os.environ.get("PROMPT_SKILL_DEFAULT_OUTPUT")
        or settings.get("default_output")
        or DEFAULT_PROMPT_SKILL_OUTPUT
    ).lower()
    if default_output not in {"full_prompt", "compact_prompt"}:
        default_output = DEFAULT_PROMPT_SKILL_OUTPUT

    return {
        "provider": provider,
        "skill": skill,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "default_output": default_output,
    }


def get_proxy_config(scope: str = "") -> dict[str, Any]:
    settings = load_app_settings()
    prefix = f"{scope.upper()}_" if scope else ""
    enabled_key = f"{scope}_proxy_enabled" if scope else "proxy_enabled"
    url_key = f"{scope}_proxy_url" if scope else "proxy_url"
    enabled = settings.get(enabled_key, False)
    env_enabled = os.environ.get(f"{prefix}PROXY_ENABLED")
    if env_enabled is not None:
        enabled = env_enabled.strip().lower() in ("1", "true", "yes", "on")
    proxy_url = _as_str(os.environ.get(f"{prefix}PROXY_URL") or settings.get(url_key))
    return {
        "enabled": bool(enabled),
        "proxy_url": proxy_url,
    }


def get_max_concurrent_tasks() -> int:
    """Max concurrent generation tasks. Default 3, clamp to 1-8."""
    raw = (
        os.environ.get("MAX_CONCURRENT_TASKS")
        or load_app_settings().get("max_concurrent_tasks")
        or 3
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 3
    return max(1, min(8, value))


def _normalize_origin(value: Any) -> str:
    raw = _as_str(value).rstrip("/")
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return raw


def get_allowed_cors_origins() -> list[str]:
    """Allowed CORS origins. Defaults to local loopback; auto-adds telegram webapp_url."""
    settings = load_app_settings()
    env_value = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if env_value:
        origins = [o.strip() for o in env_value.split(",") if o.strip()]
    else:
        origins = _as_str_list(settings.get("cors_allowed_origins"))
    if not origins:
        origins = [
            "http://127.0.0.1:18463",
            "http://localhost:18463",
        ]
    webapp_origin = _normalize_origin(settings.get("webapp_url"))
    if webapp_origin:
        origins.append(webapp_origin)
    normalized: list[str] = []
    seen = set()
    for origin in origins:
        origin = _normalize_origin(origin)
        if origin and origin not in seen:
            normalized.append(origin)
            seen.add(origin)
    return normalized
