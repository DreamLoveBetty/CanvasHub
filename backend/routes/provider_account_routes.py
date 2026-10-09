"""Model configuration and managed Codex/account-pool control endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_gpt_config(handler, *, _collect_gpt_runtime_config):
    """Return safe GPT runtime options for the desktop UI."""
    try:
        handler.send_json(_collect_gpt_runtime_config())
    except Exception as e:
        print(f"❌ GPT 配置读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_gpt_config_save(
    handler,
    *,
    _collect_gpt_runtime_config,
    _sanitize_gpt_provider_patch,
    json,
    update_app_settings_section,
):
    """Persist non-secret GPT provider settings into project settings.json."""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')
        patch = _sanitize_gpt_provider_patch(data)
        if not patch:
            handler.send_json({"ok": False, "error": "没有可保存的 GPT 配置"}, 400)
            return
        update_app_settings_section("gpt_provider", patch)
        handler.send_json(_collect_gpt_runtime_config())
    except Exception as e:
        print(f"❌ GPT 配置保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_chatgpt_pool_status(handler, *, _collect_chatgpt_pool_status):
    """Return safe ChatGPT account-pool status for desktop settings."""
    try:
        handler.send_json({"ok": True, "chatgpt_pool": _collect_chatgpt_pool_status()})
    except Exception as e:
        print(f"❌ ChatGPT 账号池状态读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_gpt_models(handler, parsed, *, _coerce_bool, get_gpt_model_catalog, urllib):
    """Return account-scoped generation models for each GPT route."""
    try:
        query = urllib.parse.parse_qs(parsed.query or '')
        refresh = _coerce_bool((query.get('refresh') or [''])[0], False)
        handler.send_json(get_gpt_model_catalog(force=refresh))
    except Exception as e:
        print(f"❌ GPT 模型目录读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_chatgpt_pool_accounts(handler, *, _chatgpt_pool_request):
    """Proxy account list through server.py so the UI never sees sidecar auth."""
    try:
        data = _chatgpt_pool_request("GET", "/accounts")
        handler.send_json(data)
    except Exception as e:
        print(f"❌ ChatGPT 账号池账号读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_managed_codex_oauth_status(handler, *, get_managed_codex_oauth_status):
    """Return safe managed Codex OAuth status for desktop settings."""
    try:
        handler.send_json({"ok": True, "managed_codex_oauth": get_managed_codex_oauth_status()})
    except Exception as e:
        print(f"❌ Managed Codex OAuth 状态读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_managed_codex_oauth_post(
    handler,
    path,
    *,
    _coerce_bool,
    delete_managed_auth,
    finish_managed_codex_oauth_callback,
    import_managed_auth_accounts,
    json,
    refresh_managed_auth,
    start_managed_codex_oauth_login,
    update_managed_auth_account,
):
    """Handle project-managed Codex OAuth mutations."""
    try:
        payload = handler._read_json_body()
    except json.JSONDecodeError:
        handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        return

    try:
        if path == "/api/managed-codex-oauth/start":
            data = start_managed_codex_oauth_login(
                open_browser=_coerce_bool(payload.get("open_browser", payload.get("openBrowser")), True),
                force_reauth=_coerce_bool(payload.get("force_reauth", payload.get("forceReauth")), False),
                email_hint=str(payload.get("email_hint") or payload.get("emailHint") or "").strip(),
            )
            handler.send_json(data)
            return
        if path == "/api/managed-codex-oauth/finish":
            data = finish_managed_codex_oauth_callback(
                callback_url=payload.get("callback_url") or payload.get("callback") or "",
                code=payload.get("code") or "",
                state=payload.get("state") or "",
                session_id=payload.get("session_id") or payload.get("sessionId") or "",
            )
            handler.send_json(data)
            return
        if path == "/api/managed-codex-oauth/refresh":
            handler.send_json(refresh_managed_auth(
                account_id=str(payload.get("account_id") or payload.get("accountId") or "").strip(),
                refresh_all=_coerce_bool(payload.get("all", payload.get("refresh_all", payload.get("refreshAll"))), False),
            ))
            return
        if path == "/api/managed-codex-oauth/import":
            handler.send_json(import_managed_auth_accounts(payload))
            return
        if path == "/api/managed-codex-oauth/update":
            account_id = str(payload.get("account_id") or payload.get("accountId") or "").strip()
            disabled = payload.get("disabled")
            if disabled is None and "status" in payload:
                disabled = str(payload.get("status") or "").strip() in {"禁用", "disabled", "off"}
            handler.send_json(update_managed_auth_account(
                account_id,
                disabled=None if disabled is None else _coerce_bool(disabled, False),
                select=_coerce_bool(payload.get("select"), False),
            ))
            return
        if path == "/api/managed-codex-oauth/select":
            account_id = str(payload.get("account_id") or payload.get("accountId") or "").strip()
            handler.send_json(update_managed_auth_account(account_id, disabled=False, select=True))
            return
        if path == "/api/managed-codex-oauth/delete":
            handler.send_json(delete_managed_auth(
                account_id=str(payload.get("account_id") or payload.get("accountId") or "").strip(),
                delete_all=_coerce_bool(payload.get("all", payload.get("delete_all", payload.get("deleteAll"))), False),
            ))
            return
        if path == "/api/managed-codex-oauth/logout":
            handler.send_json(delete_managed_auth(delete_all=True))
            return
        handler.send_json({"ok": False, "error": "未知 managed_codex_oauth 操作"}, 404)
    except Exception as e:
        print(f"❌ Managed Codex OAuth 操作失败：{path} {e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_chatgpt_pool_post(
    handler,
    path,
    *,
    _chatgpt_pool_build_local_auth_account,
    _chatgpt_pool_complete_account_verification,
    _chatgpt_pool_open_account_verification,
    _chatgpt_pool_open_authorize_url_clean,
    _chatgpt_pool_request,
    json,
    search_chatgpt_pool,
):
    """Proxy account-pool management mutations to the local sidecar."""
    if path == "/api/gpt-pool/oauth/open-clean":
        try:
            payload = handler._read_json_body()
            data = _chatgpt_pool_open_authorize_url_clean(payload.get("authorize_url") or "")
            handler.send_json(data)
        except json.JSONDecodeError:
            handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池干净窗口打开失败：{e}")
            handler.send_json({"ok": False, "error": str(e)}, 400)
        return

    if path == "/api/gpt-pool/accounts/import-local-auth":
        try:
            payload = handler._read_json_body()
            account, source_path = _chatgpt_pool_build_local_auth_account(payload.get("path") or "")
            data = _chatgpt_pool_request("POST", "/accounts/import", {"accounts": [account]})
            if isinstance(data, dict):
                data["imported_from"] = source_path
            handler.send_json(data)
        except json.JSONDecodeError:
            handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池本机 Auth 导入失败：{e}")
            handler.send_json({"ok": False, "error": str(e)}, 502)
        return

    if path == "/api/gpt-pool/accounts/verify/start":
        try:
            payload = handler._read_json_body()
            data = _chatgpt_pool_open_account_verification(
                payload.get("account_id") or payload.get("accountId") or ""
            )
            handler.send_json(data)
        except json.JSONDecodeError:
            handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池验证窗口打开失败：{e}")
            handler.send_json({"ok": False, "error": str(e)}, 502)
        return

    if path == "/api/gpt-pool/accounts/verify/complete":
        try:
            payload = handler._read_json_body()
            data = _chatgpt_pool_complete_account_verification(
                payload.get("account_id") or payload.get("accountId") or "",
                payload.get("debug_port") or payload.get("debugPort"),
            )
            handler.send_json(data)
        except json.JSONDecodeError:
            handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池验证会话同步失败：{e}")
            handler.send_json({"ok": False, "error": str(e)}, 502)
        return

    if path == "/api/gpt-pool/search":
        try:
            payload = handler._read_json_body()
            data = search_chatgpt_pool(
                str(payload.get("prompt") or payload.get("query") or ""),
                model=str(payload.get("model") or ""),
                timeout_seconds=payload.get("timeout_seconds") or payload.get("timeout"),
            )
            handler.send_json(data)
        except json.JSONDecodeError:
            handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        except Exception as e:
            print(f"❌ ChatGPT 账号池检索失败：{e}")
            handler.send_json({"ok": False, "error": str(e)}, 502)
        return

    routes = {
        "/api/gpt-pool/oauth/start": "/accounts/oauth/start",
        "/api/gpt-pool/oauth/finish": "/accounts/oauth/finish",
        "/api/gpt-pool/accounts/import": "/accounts/import",
        "/api/gpt-pool/accounts/refresh": "/accounts/refresh",
        "/api/gpt-pool/accounts/update": "/accounts/update",
        "/api/gpt-pool/accounts/delete": "/accounts/delete",
    }
    sidecar_path = routes.get(path)
    if not sidecar_path:
        handler.send_json({"ok": False, "error": "未知账号池操作"}, 404)
        return
    try:
        payload = handler._read_json_body()
        if path == "/api/gpt-pool/oauth/finish" and payload.get("callback_url") and not payload.get("callback"):
            payload["callback"] = payload.get("callback_url")
        request_timeout = 130 if path == "/api/gpt-pool/oauth/finish" else None
        data = _chatgpt_pool_request("POST", sidecar_path, payload, timeout=request_timeout)
        handler.send_json(data)
    except json.JSONDecodeError:
        handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
    except Exception as e:
        print(f"❌ ChatGPT 账号池代理失败：{path} {e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)
