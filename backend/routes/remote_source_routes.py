"""Prompt-source synchronization and Pinterest library/auth endpoints.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def handle_prompt_sources(handler, *, list_prompt_sources):
    """返回独立远程提示词源状态。"""
    try:
        handler.send_json(list_prompt_sources())
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_library(handler, parsed, *, ensure_pinterest_auth_storage, get_pinterest_library, urllib):
    """Return local or remote Pinterest Pins without importing them into the asset index."""
    try:
        ensure_pinterest_auth_storage()
        query = urllib.parse.parse_qs(parsed.query)
        board_id = str(query.get("board_id", [""])[0] or "").strip()
        limit = int(query.get("limit", [200])[0])
        refresh = str(query.get("refresh", [""])[0] or "").strip().lower() in {"1", "true", "yes"}
        local_only = str(query.get("local_only", [""])[0] or "").strip().lower() in {"1", "true", "yes"}
        handler.send_json(get_pinterest_library(
            board_id=board_id,
            limit=limit,
            refresh=refresh,
            local_only=local_only,
        ))
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 图库读取失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_pinterest_download_pin(handler, *, download_pinterest_pin):
    """Download one Pinterest Pin into SOURCE_IMAGE_DIR/pinterest."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        board_id = str(data.get("board_id") or "").strip()
        pin_id = str(data.get("pin_id") or "").strip()
        if not pin_id:
            raise ValueError("缺少 Pinterest Pin ID")
        board, pins = handler._pinterest_board_and_pins(board_id)
        pin = next(
            (
                item for item in pins
                if str(item.get("pin_id") or "") == pin_id
                or str(item.get("id") or "") == pin_id
                or str(item.get("id") or "") == f"pinterest_{pin_id}"
            ),
            None,
        )
        if not pin:
            raise ValueError("Pinterest Pin 不存在或未加载")
        result = download_pinterest_pin(board, pin, force=bool(data.get("force")))
        handler.send_json({"ok": True, "pin_id": pin_id, "cache": result})
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 单图下载失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_pinterest_prompt_save(handler, *, save_pinterest_pin_prompt):
    """Persist an analyzed prompt beside a synchronized Pinterest image."""
    try:
        data = handler.read_json_body(max_bytes=320 * 1024)
        result = save_pinterest_pin_prompt(
            data.get("board_id"),
            data.get("pin_id"),
            data.get("prompt"),
        )
        handler.send_json(result)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 图片提示词保存失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_download_board(handler, *, start_pinterest_board_sync):
    """Create a pollable run and discover/download the board in its worker."""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        board_id = str(data.get("board_id") or "").strip()
        refresh = bool(data.get("refresh"))
        discover_board = type(handler)._pinterest_board_and_pins

        def discover():
            return discover_board(board_id, refresh=refresh)

        result = start_pinterest_board_sync(board_id, discover)
        handler.send_json(result, 202 if result.get("started") else 200)
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 图板下载启动失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_pinterest_download_status(handler, parsed, *, get_pinterest_board_download, urllib):
    """Return progress for a Pinterest board download."""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        run_id = str(query.get("run_id", [""])[0] or "").strip()
        run = get_pinterest_board_download(run_id)
        if not run:
            handler.send_json({"ok": False, "error": "Pinterest 图板下载任务不存在"}, 404)
            return
        handler.send_json({"ok": True, "run": run})
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_sync_status(handler, parsed, *, ensure_pinterest_auth_storage, get_pinterest_sync_status, urllib):
    """Return a remote/local Pinterest difference summary without remote image URLs."""
    try:
        ensure_pinterest_auth_storage()
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get("limit", [5000])[0])
        refresh = str(query.get("refresh", [""])[0] or "").strip().lower() in {"1", "true", "yes"}
        handler.send_json(get_pinterest_sync_status(limit=limit, refresh=refresh))
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 同步状态检查失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_prompt_source_items(handler, parsed, *, list_prompt_source_items, urllib):
    """返回远程提示词源本地化条目，不进入图库资产索引。"""
    try:
        query = urllib.parse.parse_qs(parsed.query)
        limit = int(query.get('limit', [200])[0])
        offset = int(query.get('offset', [0])[0])
        handler.send_json(list_prompt_source_items(
            source_slug=str(query.get('source', [''])[0] or '').strip(),
            query=str(query.get('query', [''])[0] or '').strip(),
            tag=str(query.get('tag', [''])[0] or '').strip(),
            style=str(query.get('style', [''])[0] or '').strip(),
            subject=str(query.get('subject', [''])[0] or '').strip(),
            item_type=str(query.get('type', [''])[0] or query.get('item_type', [''])[0] or '').strip(),
            limit=limit,
            offset=offset,
        ))
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_prompt_source_sync(handler, *, start_prompt_source_sync):
    """启动远程提示词源同步任务。"""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        handler.send_json(start_prompt_source_sync(str(data.get('source') or 'all')), 202)
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_prompt_source_stop(handler, *, stop_prompt_source_sync):
    """停止正在运行的远程提示词源同步任务。"""
    try:
        data = handler.read_json_body(max_bytes=64 * 1024)
        handler.send_json(stop_prompt_source_sync(str(data.get('run_id') or data.get('runId') or '')))
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)


def handle_prompt_source_run(handler, run_id, *, get_prompt_source_run):
    """查询远程提示词源同步任务。"""
    try:
        run = get_prompt_source_run(run_id)
        if not run:
            handler.send_json({"ok": False, "error": "同步任务不存在"}, 404)
            return
        handler.send_json({"ok": True, "run": run})
    except Exception as e:
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_auth_start(handler, *, _normalize_pinterest_profile_url, start_pinterest_browser_login):
    """Open an isolated local browser for Pinterest login."""
    try:
        payload = handler.read_json_body(max_bytes=64 * 1024)
        profile_url = _normalize_pinterest_profile_url(payload.get("profile_url"))
        handler.send_json(start_pinterest_browser_login(profile_url))
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 登录浏览器启动失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_auth_complete(handler, *, complete_pinterest_browser_login):
    """Capture the isolated browser state after the user logs in."""
    try:
        payload = handler.read_json_body(max_bytes=64 * 1024)
        handler.send_json(complete_pinterest_browser_login(payload.get("session_id")))
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 登录完成失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_pinterest_auth_cancel(handler, *, cancel_pinterest_browser_login):
    """Close and remove an unfinished Pinterest login browser."""
    try:
        payload = handler.read_json_body(max_bytes=64 * 1024)
        handler.send_json(cancel_pinterest_browser_login(payload.get("session_id")))
    except Exception as e:
        print(f"❌ Pinterest 登录取消失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def handle_pinterest_auth_verify(handler, *, verify_pinterest_saved_auth):
    """Verify saved Pinterest browser state without exposing it."""
    try:
        handler.send_json(verify_pinterest_saved_auth())
    except ValueError as e:
        handler.send_json({"ok": False, "error": str(e)}, 400)
    except Exception as e:
        print(f"❌ Pinterest 登录态验证失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 502)


def handle_pinterest_auth_logout(handler, *, delete_pinterest_auth):
    """Delete saved Pinterest browser authentication."""
    try:
        handler.send_json(delete_pinterest_auth())
    except Exception as e:
        print(f"❌ Pinterest 退出登录失败：{e}")
        handler.send_json({"ok": False, "error": str(e)}, 500)


def _pinterest_board_and_pins(
    board_id,
    *,
    refresh=False,
    ensure_pinterest_auth_storage,
    get_pinterest_config,
    get_pinterest_library,
):
    clean_board_id = str(board_id or "").strip()
    if not clean_board_id:
        raise ValueError("缺少 Pinterest 图板 ID")
    ensure_pinterest_auth_storage()
    config = get_pinterest_config()
    library = get_pinterest_library(
        board_id=clean_board_id,
        limit=int(config.get("max_pins_per_board") or 500),
        refresh=refresh,
    )
    board = next(
        (
            item for item in library.get("boards") or []
            if str(item.get("id") or "") == clean_board_id
        ),
        None,
    )
    if not board:
        raise ValueError("Pinterest 图板不存在")
    return board, list(library.get("pins") or [])
