"""Public system diagnostics and validated settings updates.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _collect_system_diagnostics(
    *,
    PORT,
    SERVER_HOST,
    TELEGRAM_AUTH_ALLOWED_IDS,
    TELEGRAM_AUTH_BOT_TOKEN,
    _auth_enabled,
    _collect_chatgpt_pool_status,
    _collect_comfy_workflows,
    _path_diagnostics,
    archive_scan_roots,
    collect_video_runtime_component_status,
    get_comfy_config,
    get_cyimg_config,
    get_database_path,
    get_gpt_provider_auth_status,
    get_managed_codex_oauth_status,
    get_miniapp_access_password,
    get_nano_banana_api_base_url,
    get_nano_banana_api_key,
    get_prompt_skill_config,
    get_server_config,
    get_storage_config,
    get_telegram_config,
    get_third_party_image_config,
    get_video_inference_public_config,
    get_yunwu_api_base_url,
    get_yunwu_api_key,
    source_image_roots,
):
    telegram_cfg = get_telegram_config()
    storage_cfg = get_storage_config()
    server_cfg = get_server_config()
    database_path = get_database_path()
    prompt_skill_cfg = get_prompt_skill_config()
    third_party_cfg = get_third_party_image_config()
    cyimg_cfg = get_cyimg_config()
    managed_codex_cfg = get_managed_codex_oauth_status()
    comfy_cfg = get_comfy_config()
    video_inference_cfg = get_video_inference_public_config()

    return {
        "ok": True,
        "auth": {
            "password_enabled": _auth_enabled(),
            "telegram_init_data_enabled": bool(TELEGRAM_AUTH_BOT_TOKEN),
            "allowed_user_count": len(TELEGRAM_AUTH_ALLOWED_IDS),
        },
        "server": {
            "host": SERVER_HOST,
            "port": PORT,
            "url": f"http://{SERVER_HOST}:{PORT}",
            "public_mode": bool(server_cfg.get("public_mode")),
            "configured_host": server_cfg.get("host", SERVER_HOST),
            "configured_port": server_cfg.get("port", PORT),
            "password_required": bool(server_cfg.get("public_mode")),
            "password_configured": bool(get_miniapp_access_password()),
            "restart_required": (
                str(server_cfg.get("host", SERVER_HOST)) != str(SERVER_HOST)
                or int(server_cfg.get("port", PORT)) != int(PORT)
            ),
        },
        "telegram": {
            "bot_token_configured": bool(telegram_cfg.get("bot_token")),
            "chat_id_configured": bool(telegram_cfg.get("chat_id")),
            "proxy_url": telegram_cfg.get("proxy_url", ""),
            "delivery_method": "sendDocument",
        },
        "yunwu": {
            "api_key_configured": bool(get_yunwu_api_key()),
            "base_url": get_yunwu_api_base_url(),
        },
        "nano_banana_api": {
            "api_key_configured": bool(get_nano_banana_api_key()),
            "base_url": get_nano_banana_api_base_url(),
        },
        "third_party_image_api": {
            "api_key_configured": bool(third_party_cfg.get("api_key_configured")),
            "base_url": third_party_cfg.get("base_url", ""),
            "model": third_party_cfg.get("model", ""),
            "generate_path": third_party_cfg.get("generate_path", ""),
            "edit_path": third_party_cfg.get("edit_path", ""),
            "format": third_party_cfg.get("format", "png"),
            "timeout_seconds": third_party_cfg.get("timeout_seconds", 900),
        },
        "cyimg": {
            "api_key_configured": bool(cyimg_cfg.get("api_key_configured")),
            "task_timeout_seconds": cyimg_cfg.get("task_timeout_seconds", 3600),
        },
        "comfy": {
            "base_url": comfy_cfg.get("base_url", ""),
            "configured": bool(comfy_cfg.get("base_url")),
            "environment_managed": bool(comfy_cfg.get("environment_managed")),
            "workflow_count": len(_collect_comfy_workflows().get("items") or []),
        },
        "video_inference": {
            "runtime_mode": video_inference_cfg.get("runtime_mode", "auto"),
            "local_base_url": (video_inference_cfg.get("local") or {}).get("base_url", ""),
            "lan_base_url": (video_inference_cfg.get("lan") or {}).get("base_url", ""),
            "manager_base_url": video_inference_cfg.get("manager_base_url", ""),
            "lan_api_key_configured": bool((video_inference_cfg.get("lan") or {}).get("api_key_configured")),
            "environment_managed": bool(video_inference_cfg.get("environment_managed")),
            "component": collect_video_runtime_component_status(),
        },
        "storage": {
            "image_archive_dir": _path_diagnostics(storage_cfg["image_archive_dir"], expect_dir=True),
            "source_image_dir": _path_diagnostics(storage_cfg["source_image_dir"], expect_dir=True),
            "archive_read_roots": [{"key": key, "path": str(path)} for key, path in archive_scan_roots()],
            "source_image_read_roots": [{"key": key, "path": str(path)} for key, path in source_image_roots()],
        },
        "database": {
            "tasks_db": _path_diagnostics(database_path),
        },
        "gpt_provider": get_gpt_provider_auth_status(),
        "managed_codex_oauth": managed_codex_cfg,
        "chatgpt_pool": _collect_chatgpt_pool_status(),
        "prompt_skill": {
            "provider": prompt_skill_cfg.get("provider", ""),
            "skill": prompt_skill_cfg.get("skill", ""),
            "model": prompt_skill_cfg.get("model", ""),
            "reasoning_effort": prompt_skill_cfg.get("reasoning_effort", ""),
            "default_output": prompt_skill_cfg.get("default_output", ""),
        },
    }


def _collect_gpt_runtime_config(
    *,
    DEFAULT_GPT_IMAGE_MAIN_MODEL,
    DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_GPT_REASONING_EFFORT,
    DEFAULT_GPT_TRANSPORT_MODE,
    VALID_GPT_MAIN_MODELS,
    VALID_GPT_REASONING_EFFORTS,
    VALID_GPT_TRANSPORT_MODES,
    get_gpt_provider_config,
):
    provider_cfg = get_gpt_provider_config()
    return {
        "ok": True,
        "gpt_provider": {
            "image_main_model": provider_cfg.get("image_main_model") or DEFAULT_GPT_IMAGE_MAIN_MODEL,
            "reasoning_effort": provider_cfg.get("reasoning_effort") or DEFAULT_GPT_REASONING_EFFORT,
            "transport_mode": provider_cfg.get("transport_mode") or DEFAULT_GPT_TRANSPORT_MODE,
            "total_timeout_seconds": provider_cfg.get("total_timeout_seconds") or DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
            "allowed_image_main_models": provider_cfg.get("allowed_image_main_models") or sorted(VALID_GPT_MAIN_MODELS),
            "allowed_reasoning_efforts": provider_cfg.get("allowed_reasoning_efforts") or sorted(VALID_GPT_REASONING_EFFORTS),
            "allowed_transport_modes": provider_cfg.get("allowed_transport_modes") or sorted(VALID_GPT_TRANSPORT_MODES),
        },
    }


def _collect_system_settings(
    *,
    PORT,
    SERVER_HOST,
    TELEGRAM_AUTH_ALLOWED_IDS,
    archive_scan_roots,
    ensure_pinterest_auth_storage,
    get_chatgpt_pool_public_config,
    get_comfy_config,
    get_cyimg_config,
    get_database_path,
    get_gpt_provider_config,
    get_managed_codex_oauth_public_config,
    get_miniapp_access_password,
    get_nano_banana_api_base_url,
    get_nano_banana_api_key,
    get_pinterest_browser_login_capability,
    get_pinterest_config,
    get_prompt_skill_config,
    get_proxy_config,
    get_server_config,
    get_storage_config,
    get_telegram_config,
    get_third_party_image_config,
    get_video_inference_public_config,
    get_yunwu_api_base_url,
    get_yunwu_api_key,
    source_image_roots,
):
    """Return editable settings without exposing secret values."""
    ensure_pinterest_auth_storage()
    telegram_cfg = get_telegram_config()
    storage_cfg = get_storage_config()
    server_cfg = get_server_config()
    provider_cfg = get_gpt_provider_config()
    managed_codex_cfg = get_managed_codex_oauth_public_config()
    pool_cfg = get_chatgpt_pool_public_config()
    prompt_cfg = get_prompt_skill_config()
    third_party_cfg = get_third_party_image_config()
    cyimg_cfg = get_cyimg_config()
    proxy_cfg = get_proxy_config()
    prompt_source_proxy_cfg = get_proxy_config("prompt_source")
    comfy_cfg = get_comfy_config()
    video_inference_cfg = get_video_inference_public_config()
    pinterest_cfg = get_pinterest_config()
    pinterest_browser = get_pinterest_browser_login_capability()
    return {
        "ok": True,
        "settings": {
            "auth": {
                "miniapp_access_password_configured": bool(get_miniapp_access_password()),
            },
            "server": {
                "host": server_cfg.get("host", SERVER_HOST),
                "port": server_cfg.get("port", PORT),
                "public_mode": bool(server_cfg.get("public_mode")),
                "runtime_host": SERVER_HOST,
                "runtime_port": PORT,
                "restart_required": (
                    str(server_cfg.get("host", SERVER_HOST)) != str(SERVER_HOST)
                    or int(server_cfg.get("port", PORT)) != int(PORT)
                ),
            },
            "telegram": {
                "bot_token_configured": bool(telegram_cfg.get("bot_token")),
                "chat_id": telegram_cfg.get("chat_id", ""),
                "allowed_user_ids": sorted(TELEGRAM_AUTH_ALLOWED_IDS),
                "proxy_url": telegram_cfg.get("proxy_url", ""),
            },
            "yunwu": {
                "api_key_configured": bool(get_yunwu_api_key()),
                "base_url": get_yunwu_api_base_url(),
            },
            "nano_banana_api": {
                "api_key_configured": bool(get_nano_banana_api_key()),
                "base_url": get_nano_banana_api_base_url(),
            },
            "third_party_image_api": {
                "api_key_configured": bool(third_party_cfg.get("api_key_configured")),
                "base_url": third_party_cfg.get("base_url", ""),
                "model": third_party_cfg.get("model", ""),
                "generate_path": third_party_cfg.get("generate_path", ""),
                "edit_path": third_party_cfg.get("edit_path", ""),
                "format": third_party_cfg.get("format", "png"),
                "timeout_seconds": third_party_cfg.get("timeout_seconds", 900),
            },
            "cyimg": {
                "api_key_configured": bool(cyimg_cfg.get("api_key_configured")),
                "task_timeout_seconds": cyimg_cfg.get("task_timeout_seconds", 3600),
            },
            "comfy": {
                "base_url": comfy_cfg.get("base_url", ""),
                "timeout_seconds": comfy_cfg.get("timeout_seconds", 120),
                "task_timeout_seconds": comfy_cfg.get("task_timeout_seconds", 1800),
                "poll_interval_seconds": comfy_cfg.get("poll_interval_seconds", 2),
                "environment_managed": bool(comfy_cfg.get("environment_managed")),
                "environment_fields": comfy_cfg.get("environment_fields") or [],
            },
            "video_inference": video_inference_cfg,
            "pinterest": {
                "enabled": bool(pinterest_cfg.get("enabled")),
                "profile_url": pinterest_cfg.get("profile_url", ""),
                "sync_profile_url": pinterest_cfg.get("sync_profile_url", ""),
                "auth_configured": bool(pinterest_cfg.get("auth_configured")),
                "auth_status": pinterest_cfg.get("auth_status", "not_configured"),
                "auth_updated_at": pinterest_cfg.get("auth_updated_at", ""),
                "last_verified_at": pinterest_cfg.get("last_verified_at", ""),
                "auth_source": pinterest_cfg.get("auth_source", "none"),
                "auth_username": pinterest_cfg.get("auth_username", ""),
                "auth_display_name": pinterest_cfg.get("auth_display_name", ""),
                "auth_profile_url": pinterest_cfg.get("auth_profile_url", ""),
                "browser_login_available": bool(pinterest_browser.get("available")),
                "browser_name": pinterest_browser.get("browser", ""),
                "sync_mode": pinterest_cfg.get("sync_mode", "auto"),
                "download_originals": bool(pinterest_cfg.get("download_originals", True)),
                "max_pins_per_board": pinterest_cfg.get("max_pins_per_board", 500),
                "request_timeout_seconds": pinterest_cfg.get("request_timeout_seconds", 20),
            },
            "paths": {
                "image_archive_dir": str(storage_cfg["image_archive_dir"]),
                "source_image_dir": str(storage_cfg["source_image_dir"]),
                "tasks_db": str(get_database_path()),
                "archive_read_roots": [{"key": key, "path": str(path)} for key, path in archive_scan_roots()],
                "source_image_read_roots": [{"key": key, "path": str(path)} for key, path in source_image_roots()],
            },
            "managed_codex_oauth": managed_codex_cfg,
            "chatgpt_pool": pool_cfg,
            "prompt_skill": prompt_cfg,
            "proxy": proxy_cfg,
            "prompt_source_proxy": prompt_source_proxy_cfg,
        },
    }


def _settings_dict(value):
    return value if isinstance(value, dict) else {}


def _clean_text(value, max_len=4096):
    return str(value or "").strip()[:max_len]


def _clean_text_list(value, *, _clean_text, re):
    if isinstance(value, (list, tuple, set)):
        return [_clean_text(item, 128) for item in value if _clean_text(item, 128)]
    text = _clean_text(value, 4096)
    if not text:
        return []
    return [_clean_text(item, 128) for item in re.split(r"[\n,，\s]+", text) if _clean_text(item, 128)]


def _patch_text(target, source, key, max_len=4096, allow_empty=True, *, _clean_text):
    if key not in source:
        return
    value = _clean_text(source.get(key), max_len=max_len)
    if value or allow_empty:
        target[key] = value


def _patch_secret(target, source, key, clear_key=None, max_len=8192, *, _clean_text, _coerce_bool):
    clear_key = clear_key or f"clear_{key}"
    if _coerce_bool(source.get(clear_key), False):
        target.pop(key, None)
        return
    if key not in source:
        return
    value = _clean_text(source.get(key), max_len=max_len)
    if value:
        target[key] = value


def _normalize_pinterest_profile_url(value, *, _clean_text, re, urllib):
    text = _clean_text(value, max_len=2048)
    if not text:
        return ""
    parsed = urllib.parse.urlparse(text if "://" in text else f"https://{text}")
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not (host == "pinterest.com" or host.endswith(".pinterest.com")):
        raise ValueError("Pinterest 主页地址必须使用 pinterest.com 域名")
    path = re.sub(r"/+", "/", parsed.path or "/")
    return urllib.parse.urlunparse(("https", host, path, "", "", ""))


def _normalize_pinterest_cookie_header(value, *, re):
    text = str(value or "").strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    text = re.sub(r"[\r\n]+", " ", text).strip()
    return text[:65536]


def _sanitize_system_settings_patch(
    payload,
    *,
    _clean_text,
    _clean_text_list,
    _coerce_bool,
    _coerce_gpt_main_model,
    _coerce_gpt_provider_total_timeout,
    _coerce_gpt_reasoning_effort,
    _coerce_gpt_transport_mode,
    _normalize_comfy_base_url,
    _normalize_pinterest_profile_url,
    _patch_secret,
    _patch_text,
    _server_config_from_settings_snapshot,
    _settings_dict,
    _validate_public_mode_password,
    load_app_settings,
    normalize_runtime_base_url,
    normalize_supervisor_base_url,
):
    if not isinstance(payload, dict):
        return None
    data = _settings_dict(payload.get("settings")) or payload
    settings = load_app_settings()
    if not isinstance(settings, dict):
        settings = {}

    _patch_secret(settings, data, "miniapp_access_password")
    _patch_secret(settings, data, "yunwu_api_key")
    _patch_text(settings, data, "yunwu_api_base_url", max_len=2048)

    nano_banana = _settings_dict(settings.get("nano_banana_api")).copy()
    nano_banana_data = _settings_dict(data.get("nano_banana_api"))
    _patch_secret(nano_banana, nano_banana_data, "api_key")
    _patch_text(nano_banana, nano_banana_data, "base_url", max_len=2048)
    if _coerce_bool(nano_banana_data.get("clear_api_key"), False):
        settings.pop("nano_banana_api_key", None)
        settings.pop("yunwu_api_key", None)
    if "base_url" in nano_banana_data and not _clean_text(nano_banana_data.get("base_url"), max_len=2048):
        settings.pop("nano_banana_api_base_url", None)
        settings.pop("yunwu_api_base_url", None)
    if nano_banana_data:
        settings["nano_banana_api"] = nano_banana

    server = _settings_dict(settings.get("server")).copy()
    server_data = _settings_dict(data.get("server"))
    if "public_mode" in server_data:
        server["public_mode"] = _coerce_bool(server_data.get("public_mode"), False)
    _patch_text(server, server_data, "host", max_len=255)
    if "port" in server_data:
        try:
            server["port"] = max(1, min(65535, int(server_data.get("port"))))
        except (TypeError, ValueError):
            pass
    if server_data:
        settings["server"] = server

    telegram = _settings_dict(settings.get("telegram")).copy()
    telegram_data = _settings_dict(data.get("telegram"))
    _patch_secret(telegram, telegram_data, "bot_token")
    _patch_text(telegram, telegram_data, "chat_id", max_len=128)
    _patch_text(telegram, telegram_data, "proxy_url", max_len=512)
    if "allowed_user_ids" in telegram_data:
        telegram["allowed_user_ids"] = _clean_text_list(telegram_data.get("allowed_user_ids"))
    if telegram_data:
        settings["telegram"] = telegram

    paths = _settings_dict(settings.get("paths")).copy()
    paths_data = _settings_dict(data.get("paths"))
    for key in ("image_archive_dir", "source_image_dir", "tasks_db"):
        _patch_text(paths, paths_data, key, max_len=2048)
    if paths_data:
        settings["paths"] = paths

    provider = _settings_dict(settings.get("gpt_provider")).copy()
    provider_data = _settings_dict(data.get("gpt_provider"))
    for key in ("auth_file", "auth_dir", "api_base"):
        _patch_text(provider, provider_data, key, max_len=2048)
    if "image_main_model" in provider_data:
        provider["image_main_model"] = _coerce_gpt_main_model(provider_data.get("image_main_model"))
    if "reasoning_effort" in provider_data:
        provider["reasoning_effort"] = _coerce_gpt_reasoning_effort(provider_data.get("reasoning_effort"))
    if "transport_mode" in provider_data:
        provider["transport_mode"] = _coerce_gpt_transport_mode(provider_data.get("transport_mode"))
    if "total_timeout_seconds" in provider_data:
        provider["total_timeout_seconds"] = _coerce_gpt_provider_total_timeout(provider_data.get("total_timeout_seconds"))
    if provider_data:
        settings["gpt_provider"] = provider

    third_party = _settings_dict(settings.get("third_party_image_api")).copy()
    third_party_data = _settings_dict(data.get("third_party_image_api"))
    _patch_secret(third_party, third_party_data, "api_key")
    for key in ("base_url", "model", "generate_path", "edit_path", "format"):
        _patch_text(third_party, third_party_data, key, max_len=2048 if key in ("base_url", "generate_path", "edit_path") else 128)
    if "timeout_seconds" in third_party_data:
        try:
            third_party["timeout_seconds"] = max(30, min(1800, int(third_party_data.get("timeout_seconds"))))
        except (TypeError, ValueError):
            pass
    if third_party_data:
        settings["third_party_image_api"] = third_party

    cyimg = _settings_dict(settings.get("cyimg")).copy()
    cyimg_data = _settings_dict(data.get("cyimg"))
    _patch_secret(cyimg, cyimg_data, "api_key")
    if "task_timeout_seconds" in cyimg_data:
        try:
            cyimg["task_timeout_seconds"] = max(60, min(7200, int(cyimg_data["task_timeout_seconds"])))
        except (TypeError, ValueError):
            pass
    if cyimg_data:
        settings["cyimg"] = cyimg

    comfy = _settings_dict(settings.get("comfy")).copy()
    comfy_data = _settings_dict(data.get("comfy"))
    _patch_text(comfy, comfy_data, "base_url", max_len=2048)
    if "base_url" in comfy_data:
        comfy["base_url"] = _normalize_comfy_base_url(comfy.get("base_url"))
    for key, minimum, maximum in (
        ("timeout_seconds", 5, 1800),
        ("task_timeout_seconds", 60, 86400),
    ):
        if key in comfy_data:
            try:
                comfy[key] = max(minimum, min(maximum, int(comfy_data.get(key))))
            except (TypeError, ValueError):
                pass
    if "poll_interval_seconds" in comfy_data:
        try:
            comfy["poll_interval_seconds"] = max(0.25, min(30.0, float(comfy_data.get("poll_interval_seconds"))))
        except (TypeError, ValueError):
            pass
    if comfy_data:
        settings["comfy"] = comfy

    video_inference = _settings_dict(settings.get("video_inference")).copy()
    video_inference_data = _settings_dict(data.get("video_inference"))
    runtime_mode = _clean_text(video_inference_data.get("runtime_mode"), max_len=16).lower()
    if runtime_mode in {"auto", "local", "lan"}:
        video_inference["runtime_mode"] = runtime_mode
    if "manager_base_url" in video_inference_data:
        raw_manager_url = _clean_text(video_inference_data.get("manager_base_url"), max_len=2048)
        video_inference["manager_base_url"] = normalize_supervisor_base_url(raw_manager_url, allow_empty=True)

    video_local = _settings_dict(video_inference.get("local")).copy()
    video_local_data = _settings_dict(video_inference_data.get("local"))
    if "base_url" in video_local_data:
        raw_url = _clean_text(video_local_data.get("base_url"), max_len=2048)
        video_local["base_url"] = normalize_runtime_base_url(raw_url) if raw_url else ""
    _patch_text(video_local, video_local_data, "component_dir", max_len=2048)
    start_mode = _clean_text(video_local_data.get("start_mode"), max_len=24).lower()
    if start_mode in {"manual", "on_demand", "always"}:
        video_local["start_mode"] = start_mode
    if video_local_data:
        video_inference["local"] = video_local

    video_lan = _settings_dict(video_inference.get("lan")).copy()
    video_lan_data = _settings_dict(video_inference_data.get("lan"))
    if "base_url" in video_lan_data:
        raw_url = _clean_text(video_lan_data.get("base_url"), max_len=2048)
        video_lan["base_url"] = normalize_runtime_base_url(raw_url, allow_empty=True)
    _patch_secret(video_lan, video_lan_data, "api_key")
    if "connect_timeout_seconds" in video_lan_data:
        try:
            video_lan["connect_timeout_seconds"] = max(0.5, min(30.0, float(video_lan_data.get("connect_timeout_seconds"))))
        except (TypeError, ValueError):
            pass
    if video_lan_data:
        video_inference["lan"] = video_lan

    video_defaults = _settings_dict(video_inference.get("defaults")).copy()
    video_defaults_data = _settings_dict(video_inference_data.get("defaults"))
    aspect_ratio = _clean_text(video_defaults_data.get("aspect_ratio"), max_len=16)
    if aspect_ratio in {"16:9", "9:16", "3:4", "4:3", "2:3", "3:2", "1:1", "21:9", "9:21"}:
        video_defaults["aspect_ratio"] = aspect_ratio
    acceleration_mode = _clean_text(video_defaults_data.get("acceleration_mode"), max_len=32).lower()
    if acceleration_mode in {"off", "first_block_cache", "sol_attn", "combined"}:
        video_defaults["acceleration_mode"] = acceleration_mode
    for key, minimum, maximum in (
        ("pixel_budget_mp", 0.1, 8.0),
        ("first_block_cache_threshold", 0.001, 1.0),
    ):
        if key in video_defaults_data:
            try:
                video_defaults[key] = max(minimum, min(maximum, float(video_defaults_data.get(key))))
            except (TypeError, ValueError):
                pass
    if "duration_seconds" in video_defaults_data:
        try:
            video_defaults["duration_seconds"] = max(1, min(120, int(video_defaults_data.get("duration_seconds"))))
        except (TypeError, ValueError):
            pass
    if video_defaults_data:
        video_inference["defaults"] = video_defaults
    if video_inference_data:
        settings["video_inference"] = video_inference

    pinterest = _settings_dict(settings.get("pinterest")).copy()
    pinterest_data = _settings_dict(data.get("pinterest"))
    had_legacy_auth_file = "auth_file" in pinterest
    pinterest.pop("auth_file", None)
    if "enabled" in pinterest_data:
        pinterest["enabled"] = _coerce_bool(pinterest_data.get("enabled"), False)
    if "profile_url" in pinterest_data:
        pinterest["profile_url"] = _normalize_pinterest_profile_url(pinterest_data.get("profile_url"))
    if "sync_profile_url" in pinterest_data:
        sync_profile_url = _normalize_pinterest_profile_url(pinterest_data.get("sync_profile_url"))
        if sync_profile_url:
            pinterest["sync_profile_url"] = sync_profile_url
        else:
            pinterest.pop("sync_profile_url", None)
    if "sync_mode" in pinterest_data:
        sync_mode = _clean_text(pinterest_data.get("sync_mode"), max_len=32).lower()
        if sync_mode in {"auto", "rss", "authenticated_browser"}:
            pinterest["sync_mode"] = sync_mode
    if "download_originals" in pinterest_data:
        pinterest["download_originals"] = _coerce_bool(pinterest_data.get("download_originals"), True)
    for key, minimum, maximum in (
        ("max_pins_per_board", 20, 5000),
        ("request_timeout_seconds", 5, 60),
    ):
        if key in pinterest_data:
            try:
                pinterest[key] = max(minimum, min(maximum, int(pinterest_data.get(key))))
            except (TypeError, ValueError):
                pass
    clear_pinterest_auth = _coerce_bool(pinterest_data.get("clear_auth_cookie"), False)
    if clear_pinterest_auth:
        for key in ("auth_cookie", "auth_updated_at", "last_verified_at"):
            pinterest.pop(key, None)
        pinterest["auth_status"] = "not_configured"
    elif _coerce_bool(pinterest_data.get("clear_legacy_auth_cookie"), False):
        pinterest.pop("auth_cookie", None)
    if pinterest_data or had_legacy_auth_file:
        settings["pinterest"] = pinterest

    pool = _settings_dict(settings.get("chatgpt_pool")).copy()
    pool_data = _settings_dict(data.get("chatgpt_pool"))
    if "enabled" in pool_data:
        pool["enabled"] = _coerce_bool(pool_data.get("enabled"), True)
    for key in ("base_url", "generation_model", "db_path"):
        _patch_text(pool, pool_data, key, max_len=2048)
    if "timeout_seconds" in pool_data:
        try:
            pool["timeout_seconds"] = max(60, min(900, int(pool_data.get("timeout_seconds"))))
        except (TypeError, ValueError):
            pass
    _patch_secret(pool, pool_data, "auth_key")
    if pool_data:
        settings["chatgpt_pool"] = pool

    managed_codex = _settings_dict(settings.get("managed_codex_oauth")).copy()
    managed_codex_data = _settings_dict(data.get("managed_codex_oauth"))
    if "enabled" in managed_codex_data:
        managed_codex["enabled"] = _coerce_bool(managed_codex_data.get("enabled"), True)
    for key in ("auth_file", "accounts_dir", "api_base", "redirect_uri"):
        _patch_text(managed_codex, managed_codex_data, key, max_len=2048)
    if managed_codex_data:
        settings["managed_codex_oauth"] = managed_codex

    for bool_key, url_key, section_key in (
        ("proxy_enabled", "proxy_url", "proxy"),
        ("prompt_source_proxy_enabled", "prompt_source_proxy_url", "prompt_source_proxy"),
    ):
        proxy_data = _settings_dict(data.get(section_key))
        if "enabled" in proxy_data:
            settings[bool_key] = _coerce_bool(proxy_data.get("enabled"), False)
        if "proxy_url" in proxy_data:
            settings[url_key] = _clean_text(proxy_data.get("proxy_url"), max_len=512)

    _validate_public_mode_password(settings, server_config=_server_config_from_settings_snapshot(settings))
    return settings


def _sanitize_gpt_provider_patch(data, *, GPT_TRANSPORT_MODES, _coerce_gpt_provider_total_timeout):
    allowed = {}
    transport_mode = str(data.get("transport_mode") or data.get("transportMode") or "").strip().lower()
    if transport_mode in GPT_TRANSPORT_MODES:
        allowed["transport_mode"] = transport_mode
    timeout_value = data.get("total_timeout_seconds", data.get("totalTimeoutSeconds"))
    if timeout_value not in (None, ""):
        allowed["total_timeout_seconds"] = _coerce_gpt_provider_total_timeout(timeout_value)
    return allowed


def _collect_prompt_skill_runtime_config(
    provider_id=None,
    *,
    discover_prompt_models,
    get_prompt_skill_config,
    list_prompt_providers,
):
    config = get_prompt_skill_config()
    models_payload = discover_prompt_models(provider_id or config.get("provider"))
    return {
        "ok": True,
        "prompt_skill": config,
        "providers": list_prompt_providers(),
        "models": models_payload.get("models") or [],
        "default_model": models_payload.get("default_model") or "",
        "warning": models_payload.get("warning") or "",
    }


def _sanitize_prompt_skill_patch(data, *, GPT_REASONING_EFFORTS):
    allowed = {}
    provider = str(data.get("provider") or "").strip()
    skill = str(data.get("skill") or "").strip()
    model = str(data.get("model") or "").strip()
    reasoning_effort = str(data.get("reasoning_effort") or data.get("reasoningEffort") or "").strip().lower()
    default_output = str(data.get("default_output") or data.get("defaultOutput") or "").strip().lower()
    if provider:
        allowed["provider"] = provider[:80]
    if skill:
        allowed["skill"] = skill[:120]
    allowed["model"] = model[:160]
    if reasoning_effort in GPT_REASONING_EFFORTS:
        allowed["reasoning_effort"] = reasoning_effort
    if default_output in {"full_prompt", "compact_prompt"}:
        allowed["default_output"] = default_output
    return allowed


def _path_diagnostics(path_value, expect_dir=False, *, Path, os):
    path = Path(path_value).expanduser()
    exists = path.exists()
    is_dir = path.is_dir()
    parent = path if is_dir else path.parent
    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "is_file": path.is_file(),
        "parent_exists": parent.exists(),
        "writable": os.access(str(path if exists else parent), os.W_OK) if (exists or parent.exists()) else False,
        "expected_type": "directory" if expect_dir else "file",
    }
