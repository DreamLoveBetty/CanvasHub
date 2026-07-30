#!/usr/bin/env python3
"""Pinterest browser login and private storage-state management."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

import requests

from .app_config import (
    APP_DATA_DIR,
    get_pinterest_auth_file,
    get_pinterest_config,
    load_app_settings,
    save_app_settings,
)

SESSION_TTL_SECONDS = 15 * 60
MAX_LEGACY_AUTH_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_PINTEREST_LOGIN_URL = "https://www.pinterest.com/login/"
CHROME_CANDIDATES = (
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
)

_LOCK = threading.RLock()
_PENDING: dict[str, dict[str, Any]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fixed_auth_file() -> Path:
    return get_pinterest_auth_file()


def _checked_auth_path(path: Path) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise RuntimeError("Pinterest 授权文件不能是符号链接")
    target = candidate.parent.resolve() / candidate.name
    fixed = _fixed_auth_file()
    if target != fixed:
        raise RuntimeError("Pinterest 授权文件必须使用应用管理的固定路径")
    return fixed


def _auth_file() -> Path:
    return ensure_pinterest_auth_storage()


def _read_auth(path: Path | None = None) -> dict[str, Any]:
    target = _checked_auth_path(path) if path is not None else _auth_file()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_auth(data: dict[str, Any], path: Path | None = None) -> Path:
    target = _checked_auth_path(path) if path is not None else _auth_file()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.parent.chmod(0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, target)
    finally:
        try:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        except Exception:
            pass
    return target


def _cookie_header_parts(raw: str) -> list[tuple[str, str]]:
    text = str(raw or "").strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    text = re.sub(r"[\r\n]+", " ", text).strip()
    items: list[tuple[str, str]] = []
    for chunk in text.split(";"):
        name, separator, value = chunk.strip().partition("=")
        if not separator or not name.strip():
            continue
        items.append((name.strip(), value.strip()))
    return items


def _storage_state_cookies(data: dict[str, Any]) -> list[dict[str, Any]]:
    state = data.get("storage_state") if isinstance(data.get("storage_state"), dict) else {}
    cookies = state.get("cookies") if isinstance(state.get("cookies"), list) else []
    return [dict(item) for item in cookies if isinstance(item, dict) and item.get("name")]


def _is_pinterest_cookie_domain(raw_domain: Any) -> bool:
    domain = str(raw_domain or "").strip().lower().lstrip(".")
    return domain == "pinterest.com" or domain.endswith(".pinterest.com")


def _pinterest_host(raw_url: Any) -> str:
    parsed = urllib.parse.urlparse(str(raw_url or "").strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "pinterest.com" or host.endswith(".pinterest.com"):
        return host
    return "www.pinterest.com"


def _clean_account_text(value: Any, limit: int = 200) -> str:
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)[:limit]


def _normalize_account_identity(raw: Any, source_url: Any = "") -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    username = _clean_account_text(raw.get("username"), 100)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", username):
        return {}
    display_name = _clean_account_text(
        raw.get("display_name")
        or raw.get("full_name")
        or raw.get("first_name")
        or username,
        200,
    )
    host = _pinterest_host(raw.get("profile_url") or source_url)
    profile_url = f"https://{host}/{urllib.parse.quote(username, safe='')}/"
    return {
        "username": username,
        "display_name": display_name or username,
        "profile_url": profile_url,
    }


def _script_json(document: str, script_id: str) -> dict[str, Any]:
    match = re.search(
        rf"<script[^>]*\bid=[\"']{re.escape(script_id)}[\"'][^>]*>(.*?)</script>",
        str(document or ""),
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return {}
    try:
        data = json.loads(unescape(match.group(1)))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _account_from_settings_document(document: str, response_url: str) -> dict[str, str]:
    """Extract only public account identity fields from Pinterest's settings page."""
    pws_data = _script_json(document, "__PWS_DATA__")
    context = pws_data.get("context") if isinstance(pws_data.get("context"), dict) else {}
    account = _normalize_account_identity(context.get("user"), response_url)
    if account:
        return account

    initial_props = _script_json(document, "__PWS_INITIAL_PROPS__")
    state = (
        initial_props.get("initialReduxState")
        if isinstance(initial_props.get("initialReduxState"), dict)
        else {}
    )
    for key in ("current_user", "currentUser", "logged_in_user", "loggedInUser"):
        account = _normalize_account_identity(state.get(key), response_url)
        if account:
            return account
    users = state.get("users") if isinstance(state.get("users"), dict) else {}
    candidates = [
        account
        for account in (
            _normalize_account_identity(item, response_url)
            for item in users.values()
        )
        if account
    ]
    return candidates[0] if len(candidates) == 1 else {}


def _is_pinterest_auth_document(data: dict[str, Any], *, require_cookies: bool = False) -> bool:
    if data.get("provider") != "pinterest_browser" or data.get("version") != 1:
        return False
    if not isinstance(data.get("auth"), dict):
        return False
    state = data.get("storage_state")
    if not isinstance(state, dict) or not isinstance(state.get("cookies"), list):
        return False
    cookies = state["cookies"]
    if require_cookies and not cookies:
        return False
    for cookie in cookies:
        if not isinstance(cookie, dict) or not str(cookie.get("name") or "").strip():
            return False
        if not _is_pinterest_cookie_domain(cookie.get("domain")):
            return False
    return True


def _legacy_auth_file(raw_path: str) -> Path:
    target = Path(str(raw_path or "").strip()).expanduser()
    if not target.is_absolute():
        target = APP_DATA_DIR / target
    return target.parent.resolve() / target.name


def _read_legacy_auth(path: Path) -> dict[str, Any]:
    try:
        if path.is_symlink():
            return {}
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_LEGACY_AUTH_FILE_BYTES:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict) or not _is_pinterest_auth_document(data, require_cookies=True):
        return {}
    return data


def ensure_pinterest_auth_storage() -> Path:
    """Migrate one legacy auth path into canonical storage without deleting the source."""
    target = _fixed_auth_file()
    with _LOCK:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.parent.chmod(0o700)
        settings = load_app_settings()
        pinterest = settings.get("pinterest") if isinstance(settings.get("pinterest"), dict) else {}
        pinterest = dict(pinterest)
        legacy_raw = str(pinterest.get("auth_file") or "").strip()
        if not legacy_raw:
            return target

        legacy_path = _legacy_auth_file(legacy_raw)
        if legacy_path != target and not target.exists():
            legacy_data = _read_legacy_auth(legacy_path)
            if legacy_data:
                _write_auth(legacy_data, target)

        pinterest.pop("auth_file", None)
        settings["pinterest"] = pinterest
        save_app_settings(settings)
    return target


def _cookie_matches_host(cookie: dict[str, Any], host: str, now: float) -> bool:
    domain = str(cookie.get("domain") or "").lower().lstrip(".")
    if not domain or not (host == domain or host.endswith(f".{domain}")):
        return False
    try:
        expires = float(cookie.get("expires") or -1)
    except (TypeError, ValueError):
        expires = -1
    return expires <= 0 or expires > now


def cookie_header_from_storage_state(data: dict[str, Any], profile_url: str = "") -> str:
    profile = str(profile_url or data.get("profile_url") or get_pinterest_config().get("profile_url") or "").strip()
    host = (urllib.parse.urlparse(profile).hostname or "www.pinterest.com").lower()
    cookies = [
        item
        for item in _storage_state_cookies(data)
        if _cookie_matches_host(item, host, time.time())
    ]
    cookies.sort(key=lambda item: len(str(item.get("path") or "/")), reverse=True)
    return "; ".join(
        f"{str(item.get('name') or '').strip()}={str(item.get('value') or '')}"
        for item in cookies
        if str(item.get("name") or "").strip()
    )


def load_saved_cookie_header(profile_url: str = "") -> str:
    path = _auth_file()
    config = get_pinterest_config()
    data = _read_auth(path)
    header = cookie_header_from_storage_state(data, profile_url or str(config.get("profile_url") or ""))
    return header or str(config.get("legacy_auth_cookie") or "").strip()


def _auth_document(
    cookies: list[dict[str, Any]],
    profile_url: str,
    source: str,
    path: Path | None = None,
) -> dict[str, Any]:
    now = _now_iso()
    previous = _read_auth(path)
    return {
        "version": 1,
        "provider": "pinterest_browser",
        "profile_url": profile_url,
        "account": {},
        "created_at": str(previous.get("created_at") or now),
        "updated_at": now,
        "source": source,
        "auth": {
            "status": "unverified",
            "last_verified_at": "",
        },
        "storage_state": {
            "cookies": cookies,
            "origins": [],
        },
    }


def import_cookie_header(cookie_header: str, profile_url: str) -> dict[str, Any]:
    items = _cookie_header_parts(cookie_header)
    if not items:
        raise ValueError("Pinterest Cookie 格式为空或无效")
    cookies = [
        {
            "name": name,
            "value": value,
            "domain": ".pinterest.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        }
        for name, value in items
    ]
    target = _auth_file()
    document = _auth_document(cookies, profile_url, "cookie_import", target)
    _write_auth(document, target)
    return public_auth_status(target)


def _update_auth_verification(
    authenticated: bool,
    path: Path | None = None,
    account: dict[str, str] | None = None,
) -> dict[str, Any]:
    target = path or _auth_file()
    data = _read_auth(target)
    if not data:
        raise RuntimeError("Pinterest 授权文件不存在或格式错误")
    now = _now_iso()
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    auth["status"] = "authenticated" if authenticated else "invalid"
    auth["last_verified_at"] = now
    data["auth"] = auth
    normalized_account = _normalize_account_identity(
        account,
        (account or {}).get("profile_url") if isinstance(account, dict) else "",
    )
    if authenticated and normalized_account:
        data["account"] = normalized_account
        data["profile_url"] = normalized_account["profile_url"]
    data["updated_at"] = now
    _write_auth(data, target)
    return public_auth_status(target)


def inspect_cookie_header(
    cookie_header: str,
    profile_url: str = "",
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    cookie = re.sub(r"[\r\n]+", " ", str(cookie_header or "")).strip()
    if not cookie:
        raise ValueError("尚未配置 Pinterest 登录态")
    host = _pinterest_host(profile_url)
    referer = str(profile_url or "").strip() or f"https://{host}/"
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        f"https://{host}/settings/",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Cookie": cookie,
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36"
            ),
        },
        timeout=max(5, min(60, int(timeout_seconds or 20))),
        allow_redirects=True,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Pinterest 登录验证请求失败（HTTP {response.status_code}）")
    body = response.text or ""
    account = _account_from_settings_document(body, str(response.url or referer))
    authenticated = any(
        re.search(marker, body, flags=re.IGNORECASE)
        for marker in (
            r'"is_authenticated"\s*:\s*true',
            r'"isAuthenticated"\s*:\s*true',
            r'"isAuthenticated"\s*:\s*1',
        )
    )
    if authenticated or account:
        return {"authenticated": True, "account": account}
    if (
        any(
            re.search(marker, body, flags=re.IGNORECASE)
            for marker in (
                r'"is_authenticated"\s*:\s*false',
                r'"isAuthenticated"\s*:\s*false',
                r'"isAuthenticated"\s*:\s*0',
            )
        )
        or "/login" in urllib.parse.urlparse(response.url).path.lower()
    ):
        return {"authenticated": False, "account": {}}
    raise RuntimeError("Pinterest 未返回可识别的登录状态")


def verify_cookie_header(cookie_header: str, profile_url: str, timeout_seconds: int = 20) -> bool:
    """Compatibility wrapper for callers that only need an authentication boolean."""
    return bool(
        inspect_cookie_header(cookie_header, profile_url, timeout_seconds).get("authenticated")
    )


def verify_saved_auth() -> dict[str, Any]:
    path = _auth_file()
    config = get_pinterest_config()
    header = load_saved_cookie_header(str(config.get("profile_url") or ""))
    inspection = inspect_cookie_header(
        header,
        str(config.get("profile_url") or ""),
        int(config.get("request_timeout_seconds") or 20),
    )
    authenticated = bool(inspection.get("authenticated"))
    status = _update_auth_verification(
        authenticated,
        path,
        inspection.get("account") if isinstance(inspection.get("account"), dict) else None,
    )
    return {"ok": True, "authenticated": authenticated, **status}


def public_auth_status(path: Path | None = None) -> dict[str, Any]:
    target = _checked_auth_path(path) if path is not None else _auth_file()
    data = _read_auth(target)
    cookies = _storage_state_cookies(data)
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    account = _normalize_account_identity(
        data.get("account"),
        (
            data.get("account", {}).get("profile_url")
            if isinstance(data.get("account"), dict)
            else data.get("profile_url")
        ),
    )
    return {
        "auth_configured": bool(cookies),
        "auth_status": str(auth.get("status") or ("unverified" if cookies else "not_configured")),
        "auth_updated_at": str(data.get("updated_at") or ""),
        "last_verified_at": str(auth.get("last_verified_at") or ""),
        "auth_source": str(data.get("source") or ("browser_auth_json" if cookies else "none")),
        "auth_username": account.get("username", ""),
        "auth_display_name": account.get("display_name", ""),
        "auth_profile_url": account.get("profile_url", ""),
    }


def _chrome_binary() -> Path | None:
    configured = str(os.environ.get("PINTEREST_CHROME_BINARY") or "").strip()
    if configured and Path(configured).expanduser().is_file():
        return Path(configured).expanduser()
    return next((path for path in CHROME_CANDIDATES if path.is_file()), None)


def browser_login_capability() -> dict[str, Any]:
    chrome = _chrome_binary()
    return {
        "available": bool(chrome),
        "browser": chrome.parent.parent.parent.name.replace(".app", "") if chrome else "",
    }


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _debug_value(port: int, path: str, timeout: float = 3.0) -> Any:
    request = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}{path}",
        headers={"User-Agent": "CanvasHub Pinterest Auth"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _debug_json(port: int, path: str = "/json/version", timeout: float = 3.0) -> dict[str, Any]:
    data = _debug_value(port, path, timeout)
    return data if isinstance(data, dict) else {}


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise RuntimeError("Chrome DevTools WebSocket 已断开")
        chunks.extend(chunk)
    return bytes(chunks)


def _send_ws_frame(sock: socket.socket, payload: bytes, opcode: int = 0x1) -> None:
    mask = os.urandom(4)
    length = len(payload)
    header = bytearray([0x80 | opcode])
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    sock.sendall(bytes(header) + mask + masked)


def _recv_ws_message(sock: socket.socket) -> tuple[int, bytes]:
    fragments = bytearray()
    message_opcode = 0
    while True:
        first, second = _recv_exact(sock, 2)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
        mask = _recv_exact(sock, 4) if masked else b""
        payload = _recv_exact(sock, length)
        if masked:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("Chrome DevTools WebSocket 已关闭")
        if opcode == 0x9:
            _send_ws_frame(sock, payload, opcode=0xA)
            continue
        if opcode in {0x1, 0x2}:
            message_opcode = opcode
        if opcode in {0x0, 0x1, 0x2}:
            fragments.extend(payload)
        if final and opcode != 0x0 or (final and fragments):
            return message_opcode, bytes(fragments)


def _cdp_call_url(
    ws_url: str,
    method: str,
    params: dict[str, Any] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(ws_url)
    if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Chrome DevTools 调试地址不可用")
    sock = socket.create_connection((parsed.hostname, int(parsed.port or 80)), timeout=timeout)
    sock.settimeout(timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {parsed.netloc}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Origin: http://localhost\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        response = bytearray()
        while b"\r\n\r\n" not in response:
            response.extend(sock.recv(4096))
        if b" 101 " not in bytes(response).split(b"\r\n", 1)[0]:
            raise RuntimeError("Chrome DevTools WebSocket 握手失败")
        command_id = secrets.randbelow(1_000_000) + 1
        _send_ws_frame(
            sock,
            json.dumps({"id": command_id, "method": method, "params": params or {}}).encode("utf-8"),
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, payload = _recv_ws_message(sock)
            message = json.loads(payload.decode("utf-8"))
            if message.get("id") != command_id:
                continue
            if message.get("error"):
                raise RuntimeError(str(message["error"].get("message") or "Chrome DevTools 命令失败"))
            result = message.get("result")
            return result if isinstance(result, dict) else {}
        raise RuntimeError("Chrome DevTools 命令超时")
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _cdp_call(port: int, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
    version = _debug_json(port, timeout=timeout)
    ws_url = str(version.get("webSocketDebuggerUrl") or "").strip()
    return _cdp_call_url(ws_url, method, params, timeout)


def _cdp_page_call(port: int, method: str, params: dict[str, Any] | None = None, timeout: float = 8.0) -> dict[str, Any]:
    targets = _debug_value(port, "/json/list", timeout)
    if not isinstance(targets, list):
        targets = []
    pages = [
        item
        for item in targets
        if isinstance(item, dict)
        and item.get("type") == "page"
        and str(item.get("webSocketDebuggerUrl") or "").strip()
    ]
    target = next(
        (item for item in pages if "pinterest." in str(item.get("url") or "").lower()),
        pages[0] if pages else None,
    )
    if not target:
        raise RuntimeError("Pinterest 登录页面已关闭，请重新连接")
    return _cdp_call_url(str(target.get("webSocketDebuggerUrl") or ""), method, params, timeout)


def _cleanup_sessions_locked() -> None:
    now = time.time()
    expired = [key for key, item in _PENDING.items() if float(item.get("expires_at") or 0) <= now]
    for key in expired:
        session = _PENDING.pop(key, None)
        if session:
            _close_and_cleanup_session(session)


def _expire_session(session_id: str) -> None:
    with _LOCK:
        session = _PENDING.get(session_id)
        if not session or float(session.get("expires_at") or 0) > time.time():
            return
        _PENDING.pop(session_id, None)
    _close_and_cleanup_session(session)


def _close_and_cleanup_session(session: dict[str, Any]) -> None:
    port = int(session.get("debug_port") or 0)
    if port:
        try:
            _cdp_call(port, "Browser.close", timeout=2)
        except Exception:
            pass
    process = session.get("process")
    if process and process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
    profile_dir_text = str(session.get("profile_dir") or "").strip()
    if profile_dir_text:
        profile_dir = Path(profile_dir_text)
        def cleanup() -> None:
            time.sleep(1)
            try:
                shutil.rmtree(profile_dir, ignore_errors=True)
            except Exception:
                pass

        threading.Thread(target=cleanup, name="pinterest-auth-cleanup", daemon=True).start()


def start_browser_login(profile_url: str = "") -> dict[str, Any]:
    capability = browser_login_capability()
    chrome = _chrome_binary()
    if not capability["available"] or not chrome:
        raise RuntimeError("未找到可用于 Pinterest 登录的 Chrome 或 Edge")
    auth_path = _auth_file()
    config = get_pinterest_config()
    host = _pinterest_host(profile_url or config.get("profile_url"))
    login_url = f"https://{host}/login/"
    verification_url = f"https://{host}/"
    with _LOCK:
        _cleanup_sessions_locked()
        previous_sessions = list(_PENDING.values())
        _PENDING.clear()
    for previous in previous_sessions:
        _close_and_cleanup_session(previous)
    session_id = secrets.token_urlsafe(24)
    root = auth_path.parent / "login_sessions"
    profile_dir = root / session_id
    profile_dir.mkdir(parents=True, exist_ok=True)
    debug_port = _find_free_port()
    process = subprocess.Popen(
        [
            str(chrome),
            f"--user-data-dir={profile_dir}",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={debug_port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-extensions",
            "--new-window",
            login_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            if _debug_json(debug_port, timeout=1).get("webSocketDebuggerUrl"):
                break
        except Exception:
            time.sleep(0.2)
    else:
        try:
            process.terminate()
        except Exception:
            pass
        raise RuntimeError("Pinterest 登录浏览器启动失败")

    session = {
        "session_id": session_id,
        "profile_url": verification_url,
        "login_url": login_url,
        "profile_dir": str(profile_dir),
        "debug_port": debug_port,
        "process": process,
        "created_at": time.time(),
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    with _LOCK:
        _cleanup_sessions_locked()
        _PENDING[session_id] = session
    expiry_timer = threading.Timer(SESSION_TTL_SECONDS + 0.1, _expire_session, args=(session_id,))
    expiry_timer.daemon = True
    expiry_timer.start()
    return {
        "ok": True,
        "pending": True,
        "session_id": session_id,
        "status": "waiting_login",
        "expires_at": datetime.fromtimestamp(session["expires_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
        "browser": capability["browser"],
        "message": "请在新打开的浏览器窗口中完成 Pinterest 登录",
    }


def _playwright_cookie(cookie: dict[str, Any]) -> dict[str, Any]:
    same_site = str(cookie.get("sameSite") or "Lax")
    if same_site not in {"Strict", "Lax", "None"}:
        same_site = "Lax"
    try:
        expires = float(cookie.get("expires") or -1)
    except (TypeError, ValueError):
        expires = -1
    if bool(cookie.get("session")) or expires <= 0:
        expires = -1
    return {
        "name": str(cookie.get("name") or ""),
        "value": str(cookie.get("value") or ""),
        "domain": str(cookie.get("domain") or ""),
        "path": str(cookie.get("path") or "/"),
        "expires": expires,
        "httpOnly": bool(cookie.get("httpOnly")),
        "secure": bool(cookie.get("secure")),
        "sameSite": same_site,
    }


def complete_browser_login(session_id: str) -> dict[str, Any]:
    target_id = str(session_id or "").strip()
    with _LOCK:
        _cleanup_sessions_locked()
        session = _PENDING.get(target_id)
    if not session:
        raise ValueError("Pinterest 登录会话不存在或已过期")
    try:
        result = _cdp_page_call(int(session["debug_port"]), "Network.getAllCookies")
    except Exception as page_error:
        try:
            result = _cdp_call(int(session["debug_port"]), "Storage.getCookies")
        except Exception:
            raise page_error
    cookies = [
        _playwright_cookie(item)
        for item in (result.get("cookies") or [])
        if isinstance(item, dict) and _is_pinterest_cookie_domain(item.get("domain"))
    ]
    profile_url = str(session.get("profile_url") or DEFAULT_PINTEREST_LOGIN_URL)
    auth_path = _auth_file()
    document = _auth_document(cookies, "", "browser_login", auth_path)
    header = cookie_header_from_storage_state(document, profile_url)
    inspection = (
        inspect_cookie_header(
            header,
            profile_url,
            int(get_pinterest_config().get("request_timeout_seconds") or 20),
        )
        if header
        else {"authenticated": False, "account": {}}
    )
    if not inspection.get("authenticated"):
        return {
            "ok": True,
            "pending": True,
            "session_id": target_id,
            "status": "waiting_login",
            "message": "尚未检测到有效 Pinterest 登录，请在浏览器完成登录后重试",
        }
    account = (
        inspection.get("account")
        if isinstance(inspection.get("account"), dict)
        else {}
    )
    if not account.get("username"):
        return {
            "ok": True,
            "pending": True,
            "session_id": target_id,
            "status": "waiting_identity",
            "message": "已检测到 Pinterest 登录，但暂未读取到账号用户名，请稍后重试",
        }
    now = _now_iso()
    document["account"] = account
    document["profile_url"] = str(account.get("profile_url") or "")
    document["auth"] = {"status": "authenticated", "last_verified_at": now}
    document["updated_at"] = now
    path = _write_auth(document, auth_path)
    with _LOCK:
        _PENDING.pop(target_id, None)
    _close_and_cleanup_session(session)
    return {
        "ok": True,
        "pending": False,
        "session_id": target_id,
        "status": "authenticated",
        "authenticated": True,
        **public_auth_status(path),
    }


def cancel_browser_login(session_id: str) -> dict[str, Any]:
    target_id = str(session_id or "").strip()
    with _LOCK:
        session = _PENDING.pop(target_id, None)
    if session:
        _close_and_cleanup_session(session)
    return {
        "ok": True,
        "pending": False,
        "session_id": target_id,
        "status": "cancelled",
    }


def delete_saved_auth() -> dict[str, Any]:
    with _LOCK:
        sessions = list(_PENDING.values())
        _PENDING.clear()
    for session in sessions:
        _close_and_cleanup_session(session)
    path = _auth_file()
    try:
        if path.exists():
            if not _is_pinterest_auth_document(_read_auth(path)):
                raise RuntimeError("Pinterest 固定授权文件缺少有效的授权标记，拒绝删除")
            path.unlink()
    except Exception as exc:
        raise RuntimeError(f"Pinterest 授权文件删除失败：{exc}") from exc
    settings = load_app_settings()
    pinterest = settings.get("pinterest") if isinstance(settings.get("pinterest"), dict) else {}
    pinterest = dict(pinterest)
    for key in ("auth_file", "auth_cookie", "auth_status", "auth_updated_at", "last_verified_at"):
        pinterest.pop(key, None)
    settings["pinterest"] = pinterest
    save_app_settings(settings)
    return {"ok": True, "authenticated": False, **public_auth_status(path)}
