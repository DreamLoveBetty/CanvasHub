"""System settings, diagnostics, update and optional component endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_system_diagnostics(handler, *, _collect_system_diagnostics):
    """Return safe runtime configuration status without secret values."""
    try:
        handler.send_json(_collect_system_diagnostics())
    except Exception as e:
        print(f"❌ 系统诊断失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_app_update_status(handler, *, get_app_update_status):
    """Return the latest public CanvasHub release without exposing configuration."""
    handler.send_json({"ok": True, **get_app_update_status()})


def handle_system_settings(handler, *, _collect_system_settings):
    """Return editable project settings without secret values."""
    try:
        handler.send_json(_collect_system_settings())
    except Exception as e:
        print(f"❌ 系统设置读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_system_settings_save(
    handler,
    *,
    _coerce_bool,
    _collect_system_settings,
    _normalize_pinterest_cookie_header,
    _reload_auth_state,
    _sanitize_system_settings_patch,
    _settings_dict,
    copy,
    delete_pinterest_auth,
    ensure_pinterest_auth_storage,
    get_pinterest_config,
    import_pinterest_cookie_header,
    save_app_settings,
):
    """Persist whitelisted project settings into settings.json."""
    try:
        ensure_pinterest_auth_storage()
        data = handler.read_json_body(max_bytes=128 * 1024)
        data = copy.deepcopy(data)
        data_root = _settings_dict(data.get("settings")) or data
        pinterest_data = _settings_dict(data_root.get("pinterest"))
        cookie_to_import = _normalize_pinterest_cookie_header(pinterest_data.get("auth_cookie"))
        clear_pinterest_auth = _coerce_bool(pinterest_data.get("clear_auth_cookie"), False)
        if cookie_to_import:
            pinterest_data.pop("auth_cookie", None)
            pinterest_data["clear_legacy_auth_cookie"] = True
        settings = _sanitize_system_settings_patch(data)
        if settings is None:
            handler.send_json({"ok": False, "error": "设置格式错误"}, 400)
            return
        save_app_settings(settings)
        if clear_pinterest_auth:
            delete_pinterest_auth()
        elif cookie_to_import:
            pinterest_cfg = get_pinterest_config()
            import_pinterest_cookie_header(
                cookie_to_import,
                pinterest_cfg.get("profile_url", ""),
            )
        _reload_auth_state()
        handler.send_json(_collect_system_settings())
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ 系统设置保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_upscale_models(handler, *, UPSCALE_MODEL_DIR, available_upscale_models, get_upscale_component_status):
    """返回本地高清放大模型状态。"""
    try:
        handler.send_json({
            "ok": True,
            "model_dir": str(UPSCALE_MODEL_DIR),
            "models": available_upscale_models(UPSCALE_MODEL_DIR),
            "component": get_upscale_component_status(),
        })
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_upscale_component_status(handler, *, get_upscale_component_status):
    try:
        handler.send_json({"ok": True, **get_upscale_component_status()})
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_upscale_component_install(handler, *, json, start_upscale_component_install):
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length) if content_length else b'{}'
        data = json.loads(body or b'{}')
        handler.send_json({"ok": True, **start_upscale_component_install(bool(data.get('force')))}, 202)
    except Exception as e:
        handler.send_json({"error": str(e)}, 500)


def handle_upscale_component_remove(handler, *, remove_upscale_component):
    try:
        handler.send_json({"ok": True, **remove_upscale_component()})
    except Exception as e:
        handler.send_json({"error": str(e)}, 409)


def handle_pose_assets_status(handler, *, pose_assets_status):
    try:
        handler.send_json(pose_assets_status())
    except Exception as e:
        print(f"❌ pose assets status failed: {e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)
