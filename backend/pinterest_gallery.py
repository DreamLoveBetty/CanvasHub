#!/usr/bin/env python3
"""Read a Pinterest profile and its boards without mixing remote Pins into the local asset index."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

import requests

from .app_config import get_pinterest_config
from .pinterest_auth import load_saved_cookie_header
from .pinterest_storage import list_local_pinterest_library, pinterest_cached_pin_fields

CACHE_TTL_SECONDS = 5 * 60
CACHE_SCHEMA_VERSION = "authenticated-board-feed-v2"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_LOCK = threading.RLock()
_PROFILE_CACHE: dict[str, dict[str, Any]] = {}
_BOARD_CACHE: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cache_key(profile_url: str, auth_updated_at: str, suffix: str = "") -> str:
    return "\n".join((CACHE_SCHEMA_VERSION, profile_url, auth_updated_at, suffix))


def _cached(cache: dict[str, dict[str, Any]], key: str, refresh: bool) -> dict[str, Any] | None:
    if refresh:
        return None
    with _LOCK:
        item = cache.get(key)
        if item and time.time() - float(item.get("_cached_at") or 0) < CACHE_TTL_SECONDS:
            return dict(item)
    return None


def _store_cache(cache: dict[str, dict[str, Any]], key: str, value: dict[str, Any]) -> dict[str, Any]:
    stored = {**value, "_cached_at": time.time()}
    with _LOCK:
        cache[key] = stored
    return dict(stored)


def _profile_identity(profile_url: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(profile_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not (host == "pinterest.com" or host.endswith(".pinterest.com")):
        raise ValueError("Pinterest 主页地址无效")
    parts = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
    if not parts:
        raise ValueError("Pinterest 主页缺少用户名")
    username = parts[0]
    origin = f"https://{host}"
    normalized = f"{origin}/{urllib.parse.quote(username, safe='')}/"
    return normalized, origin, username


def _session(cookie_header: str) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "User-Agent": USER_AGENT,
    })
    if cookie_header:
        session.headers["Cookie"] = cookie_header
    return session


def _fetch_html(session: requests.Session, url: str, timeout_seconds: int) -> str:
    response = session.get(
        url,
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
        timeout=timeout_seconds,
        allow_redirects=True,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Pinterest 页面请求失败（HTTP {response.status_code}）")
    return response.text or ""


def _script_json(document: str, script_id: str, required: bool = True) -> dict[str, Any]:
    match = re.search(
        rf"<script[^>]*\bid=[\"']{re.escape(script_id)}[\"'][^>]*>(.*?)</script>",
        document,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        if required:
            raise RuntimeError(f"Pinterest 页面缺少 {script_id} 数据")
        return {}
    try:
        data = json.loads(unescape(match.group(1)))
    except Exception as exc:
        raise RuntimeError(f"Pinterest {script_id} 数据格式错误") from exc
    return data if isinstance(data, dict) else {}


def _initial_state(document: str) -> tuple[dict[str, Any], dict[str, Any]]:
    props = _script_json(document, "__PWS_INITIAL_PROPS__")
    state = props.get("initialReduxState")
    if not isinstance(state, dict):
        raise RuntimeError("Pinterest 页面没有可读取的图库数据")
    return state, _script_json(document, "__PWS_DATA__", required=False)


def _absolute_url(origin: str, value: Any) -> str:
    text = str(value or "").strip()
    return urllib.parse.urljoin(f"{origin}/", text) if text else ""


def _board_cover(board: dict[str, Any]) -> str:
    covers = board.get("cover_images") if isinstance(board.get("cover_images"), dict) else {}
    for key in ("474x", "236x", "200x150"):
        item = covers.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return str(board.get("image_cover_url") or board.get("image_thumbnail_url") or "")


def _normalize_board(board: dict[str, Any], origin: str) -> dict[str, Any] | None:
    board_id = str(board.get("id") or "").strip()
    name = str(board.get("name") or "").strip()
    path = str(board.get("url") or "").strip()
    if not board_id or not name or not path:
        return None
    return {
        "id": board_id,
        "name": name,
        "url": _absolute_url(origin, path),
        "path": urllib.parse.urlparse(_absolute_url(origin, path)).path,
        "description": str(board.get("description") or board.get("seo_description") or "").strip(),
        "privacy": str(board.get("privacy") or "public"),
        "pin_count": int(board.get("pin_count") or 0),
        "section_count": int(board.get("section_count") or 0),
        "cover_url": _board_cover(board),
    }


def _best_image(images: dict[str, Any]) -> dict[str, Any]:
    candidates = [item for item in images.values() if isinstance(item, dict) and item.get("url")]
    if not candidates:
        return {}
    return max(candidates, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))


def _thumbnail_image(images: dict[str, Any]) -> dict[str, Any]:
    for key in ("474x", "236x", "170x"):
        item = images.get(key)
        if isinstance(item, dict) and item.get("url"):
            return item
    return _best_image(images)


def _original_image_url(pin: dict[str, Any], fallback: str) -> str:
    signature = str(pin.get("image_signature") or "").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{12,}", signature):
        return fallback
    suffix = urllib.parse.urlparse(fallback).path.rsplit(".", 1)[-1].lower()
    if suffix not in {"jpg", "jpeg", "png", "webp", "gif"}:
        suffix = "jpg"
    return f"https://i.pinimg.com/originals/{signature[:2]}/{signature[2:4]}/{signature[4:6]}/{signature}.{suffix}"


def _timestamp(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return int(parsedate_to_datetime(text).timestamp())
    except Exception:
        return 0


def _normalize_pin(pin: dict[str, Any], origin: str, download_originals: bool) -> dict[str, Any] | None:
    pin_id = str(pin.get("id") or "").strip()
    images = pin.get("images") if isinstance(pin.get("images"), dict) else {}
    best = _best_image(images)
    thumb = _thumbnail_image(images)
    display_url = str(best.get("url") or "")
    if not pin_id or not display_url:
        return None
    image_url = _original_image_url(pin, display_url) if download_originals else display_url
    board = pin.get("board") if isinstance(pin.get("board"), dict) else {}
    description = str(
        pin.get("description")
        or pin.get("grid_title")
        or pin.get("alt_text")
        or pin.get("auto_alt_text")
        or ""
    ).strip()
    title = str(pin.get("title") or pin.get("grid_title") or description or "Pinterest Pin").strip()
    if len(title) > 120:
        title = f"{title[:117]}..."
    pin_url = f"{origin}/pin/{urllib.parse.quote(pin_id, safe='')}/"
    board_name = str(board.get("name") or "").strip()
    width = int(best.get("width") or 0)
    height = int(best.get("height") or 0)
    normalized = {
        "id": f"pinterest_{pin_id}",
        "pin_id": pin_id,
        "title": title,
        "prompt": description,
        "description": description,
        "image_url": image_url,
        "display_image_url": display_url,
        "thumb_url": str(thumb.get("url") or display_url),
        "width": width,
        "height": height,
        "format": urllib.parse.urlparse(image_url).path.rsplit(".", 1)[-1].lower(),
        "created_at": _timestamp(pin.get("created_at")),
        "provider": "pinterest",
        "provider_label": "Pinterest",
        "source_kind": "pinterest",
        "source_url": pin_url,
        "external_url": str(pin.get("link") or ""),
        "board_id": str(board.get("id") or ""),
        "board_name": board_name,
        "board_url": _absolute_url(origin, board.get("url")),
        "dominant_color": str(pin.get("dominant_color") or ""),
        "tags": [board_name] if board_name else [],
        "params": {
            "source_kind": "pinterest",
            "source_url": pin_url,
            "board_id": str(board.get("id") or ""),
            "board_name": board_name,
        },
    }
    normalized.update(pinterest_cached_pin_fields(normalized["board_id"], pin_id))
    return normalized


def _normalize_pins(
    values: list[Any],
    origin: str,
    download_originals: bool,
    limit: int,
) -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        pin = _normalize_pin(value, origin, download_originals)
        if not pin or pin["id"] in seen:
            continue
        seen.add(pin["id"])
        pins.append(pin)
        if len(pins) >= limit:
            break
    return pins


def _refresh_local_pin_fields(pin: dict[str, Any]) -> dict[str, Any]:
    refreshed = dict(pin)
    refreshed.update(pinterest_cached_pin_fields(pin.get("board_id"), pin.get("pin_id")))
    return refreshed


def _state_has_profile_gallery(state: dict[str, Any]) -> bool:
    boards = state.get("boards") if isinstance(state.get("boards"), dict) else {}
    pins = state.get("pins") if isinstance(state.get("pins"), dict) else {}
    return bool(boards or pins)


def _profile_payload(config: dict[str, Any], refresh: bool) -> dict[str, Any]:
    profile_url, origin, username = _profile_identity(str(config.get("profile_url") or ""))
    auth_updated_at = str(config.get("auth_updated_at") or "")
    key = _cache_key(profile_url, auth_updated_at)
    cached = _cached(_PROFILE_CACHE, key, refresh)
    if cached:
        return cached

    cookie_header = load_saved_cookie_header(profile_url)
    session = _session(cookie_header)
    document = _fetch_html(session, profile_url, int(config.get("request_timeout_seconds") or 20))
    state, _ = _initial_state(document)
    discovery_mode = "authenticated_browser" if cookie_header else "public_profile"
    if cookie_header and not _state_has_profile_gallery(state):
        public_document = _fetch_html(
            _session(""),
            profile_url,
            int(config.get("request_timeout_seconds") or 20),
        )
        public_state, _ = _initial_state(public_document)
        if _state_has_profile_gallery(public_state):
            state = public_state
            discovery_mode = "public_profile_fallback"
    raw_boards = state.get("boards") if isinstance(state.get("boards"), dict) else {}
    boards = [
        board
        for board in (_normalize_board(item, origin) for item in raw_boards.values())
        if board
    ]
    raw_pins = state.get("pins") if isinstance(state.get("pins"), dict) else {}
    pins = _normalize_pins(
        list(raw_pins.values()),
        origin,
        bool(config.get("download_originals", True)),
        int(config.get("max_pins_per_board") or 500),
    )
    users = state.get("users") if isinstance(state.get("users"), dict) else {}
    profile_user = next(
        (
            item for item in users.values()
            if isinstance(item, dict) and str(item.get("username") or "").lower() == username.lower()
        ),
        {},
    )
    result = {
        "profile": {
            "username": username,
            "name": str(profile_user.get("full_name") or profile_user.get("first_name") or username),
            "url": profile_url,
            "image_url": str(profile_user.get("image_xlarge_url") or profile_user.get("image_medium_url") or ""),
        },
        "boards": boards,
        "pins": pins,
        "source_mode": "authenticated_browser" if cookie_header else "public_profile",
        "discovery_mode": discovery_mode,
        "fetched_at": _now_iso(),
    }
    return _store_cache(_PROFILE_CACHE, key, result)


def _board_feed_entry(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    resources = state.get("resources") if isinstance(state.get("resources"), dict) else {}
    entries = resources.get("BoardFeedResource")
    if not isinstance(entries, dict):
        return {}, {}
    for options_json, entry in entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), list):
            continue
        try:
            options = dict(json.loads(options_json))
        except Exception:
            options = {}
        return options, entry
    return {}, {}


def _fetch_resource_page(
    session: requests.Session,
    origin: str,
    board_url: str,
    handler_id: str,
    options: dict[str, Any],
    bookmark: str | None,
    timeout_seconds: int,
) -> tuple[list[Any], str]:
    source_path = urllib.parse.urlparse(board_url).path
    next_options = dict(options)
    if bookmark is None:
        next_options.pop("bookmarks", None)
    else:
        next_options["bookmarks"] = [bookmark]
    next_options["page_size"] = 50
    payload = {"options": next_options, "context": {}}
    headers = {
        "Accept": "application/json, text/javascript, */*, q=0.01",
        "Referer": board_url,
        "X-Requested-With": "XMLHttpRequest",
        "X-Pinterest-AppState": "active",
        "X-Pinterest-PWS-Handler": handler_id or "www/[username]/[slug].js",
        "X-Pinterest-Source-Url": source_path,
    }
    cookie_header = str(session.headers.get("Cookie") or "")
    for cookie_part in cookie_header.split(";"):
        cookie_name, separator, cookie_value = cookie_part.strip().partition("=")
        if separator and cookie_name.lower() in {"csrftoken", "csrf_token"} and cookie_value:
            headers["X-CSRFToken"] = cookie_value
            break
    response = session.get(
        f"{origin}/resource/BoardFeedResource/get/",
        params={
            "source_url": source_path,
            "data": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            "_": str(int(time.time() * 1000)),
        },
        headers=headers,
        timeout=timeout_seconds,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Pinterest 图板分页请求失败（HTTP {response.status_code}）")
    data = response.json()
    resource = data.get("resource_response") if isinstance(data, dict) else {}
    if not isinstance(resource, dict) or resource.get("status") not in {None, "success"}:
        raise RuntimeError(str(resource.get("message") or "Pinterest 图板分页失败"))
    values = resource.get("data") if isinstance(resource.get("data"), list) else []
    return values, str(resource.get("bookmark") or "-end-")


def _board_payload(
    config: dict[str, Any],
    profile: dict[str, Any],
    board: dict[str, Any],
    limit: int,
    refresh: bool,
) -> dict[str, Any]:
    profile_url, origin, _ = _profile_identity(str(config.get("profile_url") or ""))
    key = _cache_key(profile_url, str(config.get("auth_updated_at") or ""), str(board["id"]))
    cached = _cached(_BOARD_CACHE, key, refresh)
    if cached and (len(cached.get("pins") or []) >= min(limit, int(board.get("pin_count") or limit))):
        cached["pins"] = list(cached.get("pins") or [])[:limit]
        return cached

    cookie_header = load_saved_cookie_header(profile_url)
    timeout_seconds = int(config.get("request_timeout_seconds") or 20)
    authenticated_session = _session(cookie_header)
    session = authenticated_session
    document = _fetch_html(session, str(board["url"]), timeout_seconds)
    state, pws_data = _initial_state(document)
    options, entry = _board_feed_entry(state)
    discovery_mode = "authenticated_browser" if cookie_header else "public_profile"
    if cookie_header and not entry:
        public_session = _session("")
        document = _fetch_html(
            public_session,
            str(board["url"]),
            timeout_seconds,
        )
        state, pws_data = _initial_state(document)
        options, entry = _board_feed_entry(state)
        discovery_mode = "public_profile_fallback"

    # Pinterest's authenticated HTML currently omits BoardFeedResource, while
    # its authenticated resource endpoint still returns the complete board.
    # Use the public HTML only to discover the resource options/handler, then
    # restart the feed from its first page with the saved login session. Public
    # SSR data/bookmarks are a filtered feed and must not be mixed into this run.
    raw_values: list[Any] = []
    bookmark: str | None = "-end-"
    warning = ""
    if cookie_header and entry and options:
        try:
            raw_values, bookmark = _fetch_resource_page(
                authenticated_session,
                origin,
                str(board["url"]),
                str(pws_data.get("initialHandlerId") or ""),
                options,
                None,
                timeout_seconds,
            )
        except Exception as exc:
            warning = str(exc)
            raw_values = []
            bookmark = "-end-"
        if raw_values:
            session = authenticated_session
            discovery_mode = "authenticated_resource"

    if not raw_values:
        raw_values = list(entry.get("data") or [])
        bookmark = str(entry.get("nextBookmark") or "-end-")
        if cookie_header:
            session = _session("")
            discovery_mode = "public_profile_fallback"

    normalized_ids = {
        pin["id"]
        for pin in (
            _normalize_pin(value, origin, bool(config.get("download_originals", True)))
            for value in raw_values
            if isinstance(value, dict)
        )
        if pin
    }
    seen_bookmarks: set[str] = set()
    while len(normalized_ids) < limit and bookmark and bookmark != "-end-":
        if bookmark in seen_bookmarks:
            warning = warning or "Pinterest 图板分页书签重复"
            break
        seen_bookmarks.add(bookmark)
        try:
            values, next_bookmark = _fetch_resource_page(
                session,
                origin,
                str(board["url"]),
                str(pws_data.get("initialHandlerId") or ""),
                options,
                bookmark,
                timeout_seconds,
            )
        except Exception as exc:
            warning = str(exc)
            break
        bookmark = next_bookmark
        if not values:
            break
        raw_values.extend(values)
        for value in values:
            if not isinstance(value, dict):
                continue
            pin = _normalize_pin(
                value,
                origin,
                bool(config.get("download_originals", True)),
            )
            if pin:
                normalized_ids.add(pin["id"])
    pins = _normalize_pins(
        raw_values,
        origin,
        bool(config.get("download_originals", True)),
        limit,
    )
    result = {
        "profile": profile,
        "board": board,
        "pins": pins,
        "source_mode": "authenticated_browser" if cookie_header else "public_profile",
        "discovery_mode": discovery_mode,
        "fetched_at": _now_iso(),
        "partial": bool(warning),
        "warning": warning,
    }
    return _store_cache(_BOARD_CACHE, key, result)


def _all_boards_payload(
    config: dict[str, Any],
    profile_payload: dict[str, Any],
    boards: list[dict[str, Any]],
    limit: int,
    refresh: bool,
) -> dict[str, Any]:
    profile = dict(profile_payload.get("profile") or {})
    if not boards:
        return {
            "pins": [
                _refresh_local_pin_fields(pin)
                for pin in list(profile_payload.get("pins") or [])
            ],
            "fetched_at": str(profile_payload.get("fetched_at") or ""),
            "partial": False,
            "warning": "",
            "source_mode": str(profile_payload.get("source_mode") or ""),
            "discovery_mode": str(
                profile_payload.get("discovery_mode")
                or profile_payload.get("source_mode")
                or ""
            ),
        }

    board_payloads: list[dict[str, Any] | None] = [None] * len(boards)
    warnings: list[str] = []
    with ThreadPoolExecutor(
        max_workers=min(4, len(boards)),
        thread_name_prefix="pinterest-library",
    ) as executor:
        futures = [
            executor.submit(_board_payload, config, profile, board, limit, refresh)
            for board in boards
        ]
        for index, (board, future) in enumerate(zip(boards, futures)):
            try:
                board_payloads[index] = future.result()
            except Exception as exc:
                warnings.append(f"图板「{board.get('name') or board.get('id') or index + 1}」：{exc}")

    pins_by_id: dict[str, dict[str, Any]] = {}
    fetched_at = str(profile_payload.get("fetched_at") or "")
    discovery_modes: list[str] = []
    for board, payload in zip(boards, board_payloads):
        if not payload:
            continue
        payload_fetched_at = str(payload.get("fetched_at") or "")
        if payload_fetched_at > fetched_at:
            fetched_at = payload_fetched_at
        discovery_mode = str(payload.get("discovery_mode") or "")
        if discovery_mode and discovery_mode not in discovery_modes:
            discovery_modes.append(discovery_mode)
        if payload.get("partial") and payload.get("warning"):
            warnings.append(f"图板「{board.get('name') or board.get('id')}」：{payload['warning']}")
        for pin in list(payload.get("pins") or []):
            pin_id = str(pin.get("pin_id") or pin.get("id") or "").strip()
            if pin_id and pin_id not in pins_by_id:
                pins_by_id[pin_id] = pin

    # Retain profile Pins for a board whose feed could not be read.
    for pin in list(profile_payload.get("pins") or []):
        pin_id = str(pin.get("pin_id") or pin.get("id") or "").strip()
        if pin_id and pin_id not in pins_by_id:
            pins_by_id[pin_id] = pin

    source_mode = str(profile_payload.get("source_mode") or "")
    profile_discovery_mode = str(profile_payload.get("discovery_mode") or source_mode)
    if "public_profile_fallback" in discovery_modes:
        discovery_mode = "public_profile_fallback"
    elif len(discovery_modes) == 1:
        discovery_mode = discovery_modes[0]
    else:
        discovery_mode = profile_discovery_mode
    return {
        "pins": [_refresh_local_pin_fields(pin) for pin in pins_by_id.values()],
        "fetched_at": fetched_at,
        "partial": bool(warnings),
        "warning": "；".join(warnings),
        "source_mode": source_mode,
        "discovery_mode": discovery_mode,
    }


def get_pinterest_library(
    board_id: str = "",
    limit: int = 200,
    refresh: bool = False,
    local_only: bool = False,
) -> dict[str, Any]:
    config = get_pinterest_config()
    safe_limit = max(20, min(int(config.get("max_pins_per_board") or 500), int(limit or 200)))
    if not config.get("enabled"):
        return {
            "ok": True,
            "enabled": False,
            "auth_configured": bool(config.get("auth_configured")),
            "auth_status": str(config.get("auth_status") or "not_configured"),
            "profile": {"url": str(config.get("profile_url") or "")},
            "boards": [],
            "pins": [],
            "active_board_id": "",
            "total": 0,
        }

    if local_only:
        local = list_local_pinterest_library(
            config.get("profile_url"),
            board_id,
            limit_per_board=safe_limit,
        )
        return {
            "ok": True,
            "enabled": True,
            "auth_configured": bool(config.get("auth_configured")),
            "auth_status": str(config.get("auth_status") or "not_configured"),
            "auth_source": str(config.get("auth_source") or "none"),
            **local,
        }

    profile_payload = _profile_payload(config, refresh)
    boards = list(profile_payload.get("boards") or [])
    target_id = str(board_id or "").strip()
    if target_id:
        board = next((item for item in boards if str(item.get("id") or "") == target_id), None)
        if not board:
            raise ValueError("Pinterest 图板不存在或当前登录态不可见")
        board_payload = _board_payload(
            config,
            dict(profile_payload.get("profile") or {}),
            board,
            safe_limit,
            refresh,
        )
        pins = [
            _refresh_local_pin_fields(pin)
            for pin in list(board_payload.get("pins") or [])[:safe_limit]
        ]
        fetched_at = str(board_payload.get("fetched_at") or profile_payload.get("fetched_at") or "")
        partial = bool(board_payload.get("partial"))
        warning = str(board_payload.get("warning") or "")
        total = int(board.get("pin_count") or len(pins))
        source_mode = str(board_payload.get("source_mode") or profile_payload.get("source_mode") or "")
        discovery_mode = str(
            board_payload.get("discovery_mode")
            or profile_payload.get("discovery_mode")
            or source_mode
        )
    else:
        all_boards_payload = _all_boards_payload(
            config,
            profile_payload,
            boards,
            safe_limit,
            refresh,
        )
        pins = list(all_boards_payload.get("pins") or [])
        fetched_at = str(all_boards_payload.get("fetched_at") or "")
        partial = bool(all_boards_payload.get("partial"))
        warning = str(all_boards_payload.get("warning") or "")
        total = sum(int(item.get("pin_count") or 0) for item in boards) or len(pins)
        source_mode = str(all_boards_payload.get("source_mode") or "")
        discovery_mode = str(all_boards_payload.get("discovery_mode") or source_mode)

    return {
        "ok": True,
        "enabled": True,
        "auth_configured": bool(config.get("auth_configured")),
        "auth_status": str(config.get("auth_status") or "not_configured"),
        "auth_source": str(config.get("auth_source") or "none"),
        "source_mode": source_mode,
        "discovery_mode": discovery_mode,
        "profile": profile_payload.get("profile") or {},
        "boards": boards,
        "pins": pins,
        "active_board_id": target_id,
        "loaded_count": len(pins),
        "cached_count": sum(1 for pin in pins if pin.get("local_cached")),
        "total": total,
        "fetched_at": fetched_at,
        "partial": partial,
        "warning": warning,
    }


def get_pinterest_sync_status(limit: int = 5000, refresh: bool = False) -> dict[str, Any]:
    """Compare discoverable remote Pin IDs with synchronized local Pin IDs."""
    config = get_pinterest_config()
    configured_limit = max(
        20,
        min(5000, int(config.get("max_pins_per_board") or 500)),
    )
    # Keep accepting the legacy query hint, but never let a smaller client
    # value reduce update coverage below the configured per-board ceiling.
    safe_limit = configured_limit
    remote = get_pinterest_library(limit=safe_limit, refresh=refresh)
    if not remote.get("enabled"):
        return {
            "ok": True,
            "enabled": False,
            "checked_at": _now_iso(),
            "has_updates": False,
            "unsynced_count": 0,
            "unresolved_count": 0,
            "local_count": 0,
            "remote_discovered_count": 0,
            "remote_reported_count": 0,
            "boards": [],
            "partial": False,
            "truncated": False,
            "warning": "",
            "update_token": "",
        }

    local = list_local_pinterest_library(
        config.get("profile_url"),
        # The remote ceiling must not truncate the local side of the diff.
        # Otherwise a fully cached large board can look permanently unsynced.
        limit_per_board=5000,
    )
    remote_ids_by_board: dict[str, set[str]] = {}
    local_ids_by_board: dict[str, set[str]] = {}
    for pin in list(remote.get("pins") or []):
        clean_board_id = str(pin.get("board_id") or "").strip()
        clean_pin_id = str(pin.get("pin_id") or pin.get("id") or "").removeprefix("pinterest_").strip()
        if clean_board_id and clean_pin_id:
            remote_ids_by_board.setdefault(clean_board_id, set()).add(clean_pin_id)
    for pin in list(local.get("pins") or []):
        clean_board_id = str(pin.get("board_id") or "").strip()
        clean_pin_id = str(pin.get("pin_id") or pin.get("id") or "").removeprefix("pinterest_").strip()
        if clean_board_id and clean_pin_id:
            local_ids_by_board.setdefault(clean_board_id, set()).add(clean_pin_id)

    remote_boards = list(remote.get("boards") or [])
    local_boards_by_id = {
        str(board.get("id") or ""): board
        for board in list(local.get("boards") or [])
        if board.get("id")
    }
    board_ids = [
        str(board.get("id") or "")
        for board in remote_boards
        if board.get("id")
    ]
    board_ids.extend(
        board_id
        for board_id in local_boards_by_id
        if board_id not in board_ids
    )
    remote_boards_by_id = {
        str(board.get("id") or ""): board
        for board in remote_boards
        if board.get("id")
    }
    boards: list[dict[str, Any]] = []
    update_token_parts: list[str] = []
    total_unsynced = 0
    total_unresolved = 0
    truncated_board_names: list[str] = []
    for clean_board_id in board_ids:
        remote_board = remote_boards_by_id.get(clean_board_id) or {}
        local_board = local_boards_by_id.get(clean_board_id) or {}
        remote_ids = remote_ids_by_board.get(clean_board_id, set())
        local_ids = local_ids_by_board.get(clean_board_id, set())
        unsynced_ids = remote_ids - local_ids
        remote_reported_count = max(
            len(remote_ids),
            int(remote_board.get("pin_count") or len(remote_ids)),
        )
        truncated = (
            len(remote_ids) >= safe_limit
            and remote_reported_count > len(remote_ids)
        )
        unresolved_count = max(0, remote_reported_count - len(remote_ids))
        unsynced_count = len(unsynced_ids)
        if truncated:
            unsynced_count = max(
                unsynced_count,
                max(0, remote_reported_count - len(local_ids)),
            )
        total_unsynced += unsynced_count
        total_unresolved += unresolved_count
        if unsynced_ids:
            update_token_parts.extend(
                f"{clean_board_id}:{pin_id}"
                for pin_id in sorted(unsynced_ids)
            )
        if truncated and unsynced_count > len(unsynced_ids):
            update_token_parts.append(
                f"{clean_board_id}:counts:{len(local_ids)}:{len(remote_ids)}:"
                f"{remote_reported_count}:{unsynced_count}"
            )
        if truncated:
            truncated_board_names.append(
                str(remote_board.get("name") or local_board.get("name") or clean_board_id)
            )
        boards.append({
            "id": clean_board_id,
            "name": str(remote_board.get("name") or local_board.get("name") or clean_board_id),
            "url": str(remote_board.get("url") or local_board.get("url") or ""),
            "path": str(remote_board.get("path") or local_board.get("path") or ""),
            "local_count": len(local_ids),
            "remote_discovered_count": len(remote_ids),
            "remote_reported_count": remote_reported_count,
            "unsynced_count": unsynced_count,
            "unresolved_count": unresolved_count,
            "local_only_count": len(local_ids - remote_ids),
            "has_updates": bool(unsynced_count),
            "partial": truncated,
            "truncated": truncated,
        })

    update_token = ""
    if update_token_parts:
        identity = str((remote.get("profile") or {}).get("username") or config.get("profile_url") or "")
        digest_source = "\n".join([identity, *sorted(update_token_parts)]).encode("utf-8")
        update_token = hashlib.sha256(digest_source).hexdigest()[:24]
    profile = dict(remote.get("profile") or {})
    profile["image_url"] = ""
    truncated = bool(truncated_board_names)
    warnings = [str(remote.get("warning") or "").strip()]
    if truncated:
        warnings.append(
            "以下图板超过当前每板读取上限，待同步数量为下界："
            + "、".join(truncated_board_names)
        )
    return {
        "ok": True,
        "enabled": True,
        "auth_configured": bool(remote.get("auth_configured")),
        "auth_status": str(remote.get("auth_status") or "not_configured"),
        "auth_source": str(remote.get("auth_source") or "none"),
        "source_mode": str(remote.get("source_mode") or ""),
        "discovery_mode": str(remote.get("discovery_mode") or ""),
        "profile": profile,
        "boards": boards,
        "checked_at": _now_iso(),
        "has_updates": bool(total_unsynced),
        "unsynced_count": total_unsynced,
        "unresolved_count": total_unresolved,
        "local_count": sum(len(values) for values in local_ids_by_board.values()),
        "remote_discovered_count": sum(len(values) for values in remote_ids_by_board.values()),
        "remote_reported_count": int(remote.get("total") or 0),
        "partial": bool(remote.get("partial")) or truncated,
        "truncated": truncated,
        "warning": "；".join(item for item in warnings if item),
        "update_token": update_token,
    }
