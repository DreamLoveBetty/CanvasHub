#!/usr/bin/env python3
"""Project-managed Codex OAuth login and token storage."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import re
import secrets
import socketserver
import subprocess
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .app_config import (
    DEFAULT_MANAGED_CODEX_OAUTH_API_BASE,
    get_managed_codex_oauth_config,
    get_managed_codex_oauth_public_config,
)

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
TOKEN_URL = "https://auth.openai.com/oauth/token"
SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
SESSION_TTL_SECONDS = 15 * 60

_LOCK = threading.RLock()
_PENDING: dict[str, dict[str, Any]] = {}
_CALLBACK_SERVER: socketserver.TCPServer | None = None
_CALLBACK_THREAD: threading.Thread | None = None
_LAST_CALLBACK_RESULT: dict[str, Any] = {}

RELOGIN_REQUIRED_ERROR_MARKERS = (
    "refresh_token_invalidated",
    "token_invalidated",
    "session has ended",
    "please log in again",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _new_code_verifier() -> str:
    return _b64url(secrets.token_bytes(48))


def _code_challenge(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def _jwt_claims(token: str) -> dict[str, Any]:
    if token.count(".") < 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _parse_iso_timestamp(value: str) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _requires_relogin_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and any(marker in text for marker in RELOGIN_REQUIRED_ERROR_MARKERS))


def _read_auth_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _extract_tokens(raw: dict[str, Any]) -> dict[str, str]:
    token_obj = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else raw
    return {
        "access_token": str(token_obj.get("access_token") or raw.get("access_token") or "").strip(),
        "refresh_token": str(token_obj.get("refresh_token") or raw.get("refresh_token") or "").strip(),
        "id_token": str(token_obj.get("id_token") or raw.get("id_token") or "").strip(),
        "account_id": str(token_obj.get("account_id") or raw.get("account_id") or "").strip(),
        "expired": str(token_obj.get("expired") or token_obj.get("expire") or raw.get("expired") or raw.get("expire") or "").strip(),
    }


def _auth_file() -> Path:
    return Path(get_managed_codex_oauth_config().get("auth_file")).expanduser()


def _accounts_dir() -> Path:
    cfg = get_managed_codex_oauth_config()
    return Path(cfg.get("accounts_dir") or _auth_file().parent / "accounts").expanduser()


def _index_file() -> Path:
    return _accounts_dir() / "index.json"


def _safe_account_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return cleaned[:120].strip("._-") or f"acct_{secrets.token_hex(8)}"


def _account_id_from_auth(raw: dict[str, Any]) -> str:
    tokens = _extract_tokens(raw)
    account = raw.get("account") if isinstance(raw.get("account"), dict) else {}
    seed = (
        tokens.get("account_id")
        or account.get("chatgpt_account_id")
        or account.get("chatgpt_user_id")
        or account.get("email")
        or tokens.get("refresh_token")
        or tokens.get("access_token")
        or secrets.token_hex(12)
    )
    if str(seed).startswith("acct_") or str(seed).count("-") >= 2:
        return _safe_account_id(str(seed))
    digest = hashlib.sha256(str(seed).encode("utf-8")).hexdigest()[:16]
    return f"acct_{digest}"


def _account_file(account_id: str) -> Path:
    return _accounts_dir() / f"{_safe_account_id(account_id)}.json"


def _read_store_index() -> dict[str, Any]:
    path = _index_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_store_index(data: dict[str, Any]) -> None:
    path = _index_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _account_meta_from_id_token(id_token: str) -> dict[str, str]:
    claims = _jwt_claims(id_token)
    auth_info = claims.get("https://api.openai.com/auth")
    if not isinstance(auth_info, dict):
        auth_info = {}
    return {
        "email": str(claims.get("email") or "").strip(),
        "chatgpt_user_id": str(auth_info.get("chatgpt_user_id") or claims.get("sub") or "").strip(),
        "chatgpt_account_id": str(auth_info.get("chatgpt_account_id") or claims.get("account_id") or "").strip(),
        "chatgpt_plan_type": str(auth_info.get("chatgpt_plan_type") or "").strip(),
    }


def _auth_json_from_token_payload(payload: dict[str, Any], session: dict[str, Any] | None = None, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    session = session or {}
    previous = previous or {}
    previous_tokens = previous.get("tokens") if isinstance(previous.get("tokens"), dict) else previous

    access_token = str(payload.get("access_token") or "").strip()
    refresh_token = str(payload.get("refresh_token") or previous_tokens.get("refresh_token") or "").strip()
    id_token = str(payload.get("id_token") or previous_tokens.get("id_token") or "").strip()
    if not access_token:
        raise RuntimeError("Codex OAuth 返回缺少 access_token")
    if not refresh_token:
        raise RuntimeError("Codex OAuth 返回缺少 refresh_token，无法托管自动续期")

    expires_in = int(payload.get("expires_in") or 0)
    expires_at = datetime.fromtimestamp(time.time() + max(0, expires_in), timezone.utc).isoformat().replace("+00:00", "Z")
    account_meta = _account_meta_from_id_token(id_token)
    account_id = account_meta.get("chatgpt_account_id") or str(previous_tokens.get("account_id") or "").strip()

    return {
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "account_id": account_id,
            "expired": expires_at,
        },
        "account": account_meta,
        "oauth": {
            "provider": "managed_codex_oauth",
            "client_id": CLIENT_ID,
            "redirect_uri": str(session.get("redirect_uri") or get_managed_codex_oauth_config().get("redirect_uri") or ""),
            "scope": str(session.get("scope") or SCOPE),
        },
        "created_at": str(previous.get("created_at") or _now_iso()),
        "updated_at": _now_iso(),
    }


def _write_auth(raw: dict[str, Any]) -> Path:
    path = _auth_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def _write_account(raw: dict[str, Any], *, select: bool = True) -> tuple[str, Path]:
    account_id = _account_id_from_auth(raw)
    raw = dict(raw)
    raw["account_id"] = account_id
    raw.setdefault("status", "正常")
    raw["updated_at"] = _now_iso()
    path = _account_file(account_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    if select:
        index = _read_store_index()
        index["selected_account_id"] = account_id
        index["updated_at"] = _now_iso()
        _write_store_index(index)
        _write_auth(raw)
    return account_id, path


def _normalize_import_auth_json(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RuntimeError("Auth JSON 必须是对象")
    if isinstance(raw.get("tokens"), dict):
        auth_json = dict(raw)
        auth_json["tokens"] = dict(raw["tokens"])
    else:
        tokens = _extract_tokens(raw)
        auth_json = {
            "tokens": {
                "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "id_token": tokens["id_token"],
                "account_id": tokens["account_id"],
                "expired": tokens["expired"],
            },
            "account": raw.get("account") if isinstance(raw.get("account"), dict) else {},
            "oauth": {
                "provider": "managed_codex_oauth",
                "client_id": CLIENT_ID,
                "redirect_uri": str(get_managed_codex_oauth_config().get("redirect_uri") or ""),
                "scope": SCOPE,
            },
            "created_at": str(raw.get("created_at") or _now_iso()),
            "updated_at": _now_iso(),
        }
    tokens = _extract_tokens(auth_json)
    if not tokens["access_token"] and not tokens["refresh_token"]:
        raise RuntimeError("Auth JSON 缺少 access_token 或 refresh_token")
    account = auth_json.get("account") if isinstance(auth_json.get("account"), dict) else {}
    id_meta = _account_meta_from_id_token(tokens["id_token"])
    auth_json["account"] = {
        "email": str(account.get("email") or id_meta.get("email") or "").strip(),
        "chatgpt_account_id": str(account.get("chatgpt_account_id") or id_meta.get("chatgpt_account_id") or tokens["account_id"] or "").strip(),
        "chatgpt_plan_type": str(account.get("chatgpt_plan_type") or id_meta.get("chatgpt_plan_type") or account.get("plan_type") or "").strip(),
        "chatgpt_user_id": str(account.get("chatgpt_user_id") or id_meta.get("chatgpt_user_id") or "").strip(),
    }
    auth_json.setdefault("oauth", {})
    auth_json.setdefault("created_at", _now_iso())
    auth_json["updated_at"] = _now_iso()
    return auth_json


def _refresh_auth_json(raw: dict[str, Any]) -> dict[str, Any]:
    tokens = _extract_tokens(raw)
    if not tokens["refresh_token"]:
        raise RuntimeError("账号缺少 refresh_token，无法续期")
    sess = requests.Session()
    sess.trust_env = False
    response = sess.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "scope": "openid profile email",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"刷新失败：HTTP {response.status_code} {response.text[:500]}")
    auth_json = _auth_json_from_token_payload(response.json(), previous=raw)
    auth_json["created_at"] = raw.get("created_at") or auth_json["created_at"]
    auth_json["last_refresh"] = _now_iso()
    auth_json["disabled"] = bool(raw.get("disabled"))
    auth_json["status"] = str(raw.get("status") or ("禁用" if raw.get("disabled") else "正常"))
    return auth_json


def _exchange_code(session: dict[str, Any], code: str) -> dict[str, Any]:
    sess = requests.Session()
    sess.trust_env = False
    response = sess.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": session["redirect_uri"],
            "code_verifier": session["code_verifier"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Codex OAuth 换 token 失败：HTTP {response.status_code} {response.text[:500]}")
    payload = response.json()
    auth_json = _auth_json_from_token_payload(payload, session=session)
    account_id, path = _write_account(auth_json, select=True)
    return {
        "ok": True,
        "account_id": account_id,
        "auth_file": str(path),
        "account": auth_json.get("account") or {},
        "expires_at": auth_json["tokens"]["expired"],
    }


def _cleanup_pending_locked() -> None:
    now = time.time()
    expired_states = [state for state, item in _PENDING.items() if float(item.get("expires_at") or 0) < now]
    for state in expired_states:
        _PENDING.pop(state, None)


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    server_version = "ManagedCodexOAuth/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        global _LAST_CALLBACK_RESULT
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_error(404, "Not Found")
            return
        callback_url = f"http://{self.headers.get('Host', 'localhost:1455')}{self.path}"
        try:
            result = finish_oauth_callback(callback_url)
            _LAST_CALLBACK_RESULT = result
            self._send_html("Codex OAuth 已完成", "授权已写入项目托管账号，可以关闭这个页面。")
        except Exception as exc:
            _LAST_CALLBACK_RESULT = {"ok": False, "error": str(exc)}
            self._send_html("Codex OAuth 失败", str(exc), status=400)

    def _send_html(self, title: str, message: str, status: int = 200) -> None:
        body = f"""<!doctype html>
<meta charset="utf-8">
<title>{title}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:48px;line-height:1.5;background:#f7f7f8;color:#171717}}
main{{max-width:640px;padding:24px;border:1px solid #ddd;border-radius:10px;background:white}}
h1{{font-size:22px;margin:0 0 12px}}
p{{margin:0;color:#444}}
</style>
<main><h1>{title}</h1><p>{message}</p></main>"""
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _ensure_callback_server(redirect_uri: str) -> dict[str, Any]:
    global _CALLBACK_SERVER, _CALLBACK_THREAD
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/auth/callback":
        raise RuntimeError("Codex OAuth redirect_uri 必须是本机 /auth/callback")
    port = int(parsed.port or 80)
    host = parsed.hostname or "127.0.0.1"
    with _LOCK:
        if _CALLBACK_SERVER:
            return {"listening": True, "host": host, "port": port}
        try:
            _CALLBACK_SERVER = _ThreadingHTTPServer((host, port), _CallbackHandler)
        except OSError as exc:
            _CALLBACK_SERVER = None
            raise RuntimeError(f"Codex OAuth 回调端口 {host}:{port} 无法监听：{exc}") from exc
        _CALLBACK_THREAD = threading.Thread(target=_CALLBACK_SERVER.serve_forever, name="managed-codex-oauth-callback", daemon=True)
        _CALLBACK_THREAD.start()
    return {"listening": True, "host": host, "port": port}


def start_oauth_login(open_browser: bool = True, force_reauth: bool = False, email_hint: str = "") -> dict[str, Any]:
    cfg = get_managed_codex_oauth_config()
    if not cfg.get("enabled"):
        raise RuntimeError("managed_codex_oauth 已关闭")
    redirect_uri = str(cfg.get("redirect_uri") or "").strip()
    listener = _ensure_callback_server(redirect_uri)
    verifier = _new_code_verifier()
    state = secrets.token_urlsafe(24)
    session = {
        "state": state,
        "code_verifier": verifier,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "created_at": time.time(),
        "expires_at": time.time() + SESSION_TTL_SECONDS,
    }
    with _LOCK:
        _cleanup_pending_locked()
        _PENDING[state] = session

    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": _code_challenge(verifier),
        "code_challenge_method": "S256",
    }
    if force_reauth:
        params["prompt"] = "login"
    if email_hint:
        params["login_hint"] = str(email_hint).strip()
    authorize_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    if open_browser:
        subprocess.Popen(["open", authorize_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {
        "ok": True,
        "session_id": state,
        "authorize_url": authorize_url,
        "redirect_uri": redirect_uri,
        "callback_listener": listener,
    }


def finish_oauth_callback(callback_url: str = "", code: str = "", state: str = "", session_id: str = "") -> dict[str, Any]:
    callback = str(callback_url or "").strip()
    parsed_query: dict[str, list[str]] = {}
    if callback:
        parsed = urllib.parse.urlparse(callback)
        parsed_query = urllib.parse.parse_qs(parsed.query)
    error = (parsed_query.get("error") or [""])[0]
    if error:
        raise RuntimeError(f"Codex OAuth 授权失败：{error}")
    code_value = str(code or (parsed_query.get("code") or [""])[0]).strip()
    state_value = str(state or session_id or (parsed_query.get("state") or [""])[0]).strip()
    if not code_value:
        raise RuntimeError("缺少 OAuth code")
    if not state_value:
        raise RuntimeError("缺少 OAuth state/session_id")
    with _LOCK:
        _cleanup_pending_locked()
        session = _PENDING.pop(state_value, None)
    if not session:
        raise RuntimeError("Codex OAuth 会话已过期或不存在，请重新生成授权")
    return _exchange_code(session, code_value)


def _account_summary(account_id: str, path: Path, raw: dict[str, Any], selected_id: str = "", legacy: bool = False) -> dict[str, Any]:
    tokens = _extract_tokens(raw)
    account = raw.get("account") if isinstance(raw.get("account"), dict) else _account_meta_from_id_token(tokens["id_token"])
    exp_ts = _parse_iso_timestamp(tokens["expired"])
    now = time.time()
    disabled = bool(raw.get("disabled")) or str(raw.get("status") or "").strip() in {"禁用", "disabled", "off"}
    configured = bool(tokens["access_token"] and tokens["refresh_token"])
    expired = bool(exp_ts and exp_ts <= now)
    last_refresh_error = str(raw.get("last_refresh_error") or "")
    requires_relogin = _requires_relogin_error(last_refresh_error)
    if disabled:
        status = "禁用"
    elif requires_relogin:
        status = "需要重新登录"
    elif not configured:
        status = "异常"
    elif expired:
        status = "AT过期"
    else:
        status = "正常"
    return {
        "id": account_id,
        "account_id": account_id,
        "path": str(path),
        "legacy": legacy,
        "selected": account_id == selected_id,
        "disabled": disabled,
        "enabled": not disabled,
        "configured": configured,
        "available": bool(configured and not disabled and not requires_relogin),
        "requires_relogin": requires_relogin,
        "status": status,
        "email": str(account.get("email") or "").strip(),
        "chatgpt_account_id": str(account.get("chatgpt_account_id") or tokens["account_id"] or "").strip(),
        "chatgpt_user_id": str(account.get("chatgpt_user_id") or "").strip(),
        "chatgpt_plan_type": str(account.get("chatgpt_plan_type") or account.get("plan_type") or "").strip(),
        "plan_type": str(account.get("chatgpt_plan_type") or account.get("plan_type") or "").strip(),
        "has_access_token": bool(tokens["access_token"]),
        "has_refresh_token": bool(tokens["refresh_token"]),
        "has_id_token": bool(tokens["id_token"]),
        "has_account_id": bool(tokens["account_id"]),
        "refreshable": bool(tokens["refresh_token"]),
        "expired": tokens["expired"],
        "expires_at": tokens["expired"],
        "expires_at_ts": exp_ts,
        "expiring": bool(exp_ts and exp_ts - now < 300),
        "at_expired": expired,
        "last_refresh": str(raw.get("last_refresh") or ""),
        "last_refresh_error": last_refresh_error,
        "created_at": str(raw.get("created_at") or ""),
        "updated_at": str(raw.get("updated_at") or ""),
    }


def _load_account_records(include_legacy: bool = True) -> list[dict[str, Any]]:
    index = _read_store_index()
    selected_id = str(index.get("selected_account_id") or "").strip()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    account_dir = _accounts_dir()
    if account_dir.exists():
        for path in sorted(account_dir.glob("*.json")):
            if path.name == "index.json" or path.name.startswith("."):
                continue
            try:
                raw = _read_auth_file(path)
                account_id = str(raw.get("account_id") or path.stem or _account_id_from_auth(raw))
                account_id = _safe_account_id(account_id)
                if account_id in seen:
                    continue
                seen.add(account_id)
                records.append({"id": account_id, "path": path, "raw": raw, "summary": _account_summary(account_id, path, raw, selected_id)})
            except Exception:
                continue
    legacy_path = _auth_file()
    if include_legacy and legacy_path.exists():
        try:
            raw = _read_auth_file(legacy_path)
            legacy_id = _safe_account_id(str(raw.get("account_id") or _account_id_from_auth(raw)))
            if legacy_id not in seen:
                records.append({"id": legacy_id, "path": legacy_path, "raw": raw, "legacy": True, "summary": _account_summary(legacy_id, legacy_path, raw, selected_id or legacy_id, legacy=True)})
        except Exception:
            pass

    def sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
        summary = item.get("summary") or {}
        return (
            0 if summary.get("selected") else 1,
            0 if summary.get("enabled") and summary.get("configured") else 1,
            str(summary.get("email") or summary.get("chatgpt_account_id") or item.get("id") or ""),
        )

    return sorted(records, key=sort_key)


def _usable_record(record: dict[str, Any]) -> bool:
    summary = record.get("summary") or {}
    return bool(summary.get("configured") and summary.get("enabled") and not summary.get("requires_relogin"))


def _find_account_record(account_id: str) -> dict[str, Any] | None:
    clean = _safe_account_id(account_id)
    for record in _load_account_records(include_legacy=True):
        if record.get("id") == clean:
            return record
    return None


def _select_usable_account_record() -> dict[str, Any] | None:
    records = _load_account_records(include_legacy=True)
    index = _read_store_index()
    selected_id = str(index.get("selected_account_id") or "").strip()
    if selected_id:
        for record in records:
            if record.get("id") == selected_id and _usable_record(record):
                return record
    for record in records:
        if _usable_record(record):
            return record
    return None


def import_managed_auth_accounts(payload: dict[str, Any]) -> dict[str, Any]:
    raw_value: Any = payload.get("accounts") if isinstance(payload, dict) and "accounts" in payload else payload
    if isinstance(raw_value, str):
        raw_value = json.loads(raw_value)
    items = raw_value if isinstance(raw_value, list) else [raw_value]
    imported: list[dict[str, Any]] = []
    first = True
    for item in items:
        if isinstance(item, str):
            item = json.loads(item)
        auth_json = _normalize_import_auth_json(item)
        account_id, path = _write_account(auth_json, select=first)
        imported.append(_account_summary(account_id, path, auth_json, selected_id=account_id if first else ""))
        first = False
    return {"ok": True, "imported": len(imported), "items": imported, "managed_codex_oauth": get_auth_status()}


def refresh_managed_auth(account_id: str = "", refresh_all: bool = False) -> dict[str, Any]:
    records = _load_account_records(include_legacy=True)
    if refresh_all:
        targets = [record for record in records if (record.get("summary") or {}).get("refreshable") and (record.get("summary") or {}).get("enabled")]
    elif account_id:
        record = _find_account_record(account_id)
        targets = [record] if record else []
    else:
        record = _select_usable_account_record()
        targets = [record] if record else []
    if not targets:
        raise RuntimeError("没有可刷新的托管 Codex OAuth 账号")

    index = _read_store_index()
    selected_id = str(index.get("selected_account_id") or "").strip()
    refreshed: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for record in targets:
        try:
            raw = _refresh_auth_json(record["raw"])
            select = record.get("id") == selected_id or (not selected_id and not refreshed)
            account_id_written, path = _write_account(raw, select=select)
            refreshed.append(_account_summary(account_id_written, path, raw, selected_id=account_id_written if select else selected_id))
        except Exception as exc:
            raw = dict(record.get("raw") or {})
            raw["last_refresh_error"] = str(exc)
            try:
                if record.get("path"):
                    Path(record["path"]).write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
            errors.append({"account_id": str(record.get("id") or ""), "error": str(exc)})
            if not refresh_all:
                raise RuntimeError(str(exc)) from exc
    return {"ok": not errors, "refreshed": refreshed, "errors": errors, "managed_codex_oauth": get_auth_status()}


def update_managed_auth_account(account_id: str, *, disabled: bool | None = None, select: bool = False) -> dict[str, Any]:
    record = _find_account_record(account_id)
    if not record:
        raise RuntimeError("托管 Codex OAuth 账号不存在")
    raw = dict(record["raw"])
    if disabled is not None:
        raw["disabled"] = bool(disabled)
        raw["status"] = "禁用" if disabled else "正常"
    if select and raw.get("disabled"):
        raw["disabled"] = False
        raw["status"] = "正常"
    account_id_written, path = _write_account(raw, select=select)
    return {"ok": True, "account": _account_summary(account_id_written, path, raw, selected_id=account_id_written if select else str(_read_store_index().get("selected_account_id") or "")), "managed_codex_oauth": get_auth_status()}


def delete_managed_auth(account_id: str = "", delete_all: bool = False) -> dict[str, Any]:
    if delete_all or not account_id:
        for record in _load_account_records(include_legacy=True):
            try:
                Path(record["path"]).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            _index_file().unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": True, "configured": False, "managed_codex_oauth": get_auth_status()}

    record = _find_account_record(account_id)
    if not record:
        raise RuntimeError("托管 Codex OAuth 账号不存在")
    try:
        Path(record["path"]).unlink(missing_ok=True)
    except Exception:
        pass
    index = _read_store_index()
    if str(index.get("selected_account_id") or "") == record.get("id"):
        index.pop("selected_account_id", None)
        _write_store_index(index)
    selected = _select_usable_account_record()
    if selected:
        _write_account(selected["raw"], select=True)
    return {"ok": True, "deleted": record.get("id"), "managed_codex_oauth": get_auth_status()}


def get_auth_status() -> dict[str, Any]:
    cfg = get_managed_codex_oauth_public_config()
    configured_path = Path(cfg.get("auth_file") or "").expanduser()
    records = _load_account_records(include_legacy=True)
    selected = _select_usable_account_record()
    selected_summary = selected.get("summary") if selected else {}
    items = [record.get("summary") or {} for record in records]
    stats = {
        "total": len(items),
        "enabled": len([item for item in items if item.get("enabled")]),
        "disabled": len([item for item in items if item.get("disabled")]),
        "configured": len([item for item in items if item.get("configured")]),
        "available": len([item for item in items if item.get("available")]),
        "refreshable": len([item for item in items if item.get("refreshable")]),
        "expired": len([item for item in items if item.get("at_expired")]),
        "requires_relogin": len([item for item in items if item.get("requires_relogin")]),
    }
    status: dict[str, Any] = {
        **cfg,
        "configured": bool(selected_summary),
        "exists": configured_path.exists() or bool(items),
        "readable": bool(items),
        "has_access_token": bool(selected_summary.get("has_access_token")),
        "has_refresh_token": bool(selected_summary.get("has_refresh_token")),
        "has_id_token": bool(selected_summary.get("has_id_token")),
        "has_account_id": bool(selected_summary.get("has_account_id")),
        "expired": selected_summary.get("expired") or "",
        "expiring": selected_summary.get("expiring") if selected_summary else None,
        "account": {
            "email": str(selected_summary.get("email") or ""),
            "chatgpt_account_id": str(selected_summary.get("chatgpt_account_id") or ""),
            "chatgpt_plan_type": str(selected_summary.get("chatgpt_plan_type") or ""),
            "chatgpt_user_id": str(selected_summary.get("chatgpt_user_id") or ""),
        },
        "selected_account_id": selected_summary.get("id") or "",
        "selected_auth_file": selected_summary.get("path") or "",
        "accounts": {"items": items, "stats": stats},
        "stats": stats,
        "last_callback": _LAST_CALLBACK_RESULT if isinstance(_LAST_CALLBACK_RESULT, dict) else {},
        "pending_sessions": 0,
        "error": "",
    }
    with _LOCK:
        _cleanup_pending_locked()
        status["pending_sessions"] = len(_PENDING)
    if not selected_summary:
        if any(item.get("requires_relogin") for item in items):
            status["error"] = "managed Codex OAuth 需要重新登录"
        else:
            status["error"] = "managed Codex OAuth account not found"
    return status


def get_provider_env() -> dict[str, str]:
    cfg = get_managed_codex_oauth_config()
    if not cfg.get("enabled"):
        raise RuntimeError("managed_codex_oauth 已关闭")
    selected = _select_usable_account_record()
    if not selected:
        status = get_auth_status()
        detail = status.get("error") or "未完成 Codex OAuth 授权"
        raise RuntimeError(f"managed_codex_oauth 不可用：{detail}")
    return {
        "CODEX_API_AUTH_FILE": str(selected.get("path") or cfg.get("auth_file") or ""),
        "CODEX_API_AUTH_DIR": "",
        "GPT_PROVIDER_AUTH_FILE": "",
        "GPT_PROVIDER_AUTH_DIR": "",
        "CODEX_API_AUTH_STRICT": "1",
        "CODEX_API_BASE": str(cfg.get("api_base") or DEFAULT_MANAGED_CODEX_OAUTH_API_BASE).rstrip("/"),
    }
