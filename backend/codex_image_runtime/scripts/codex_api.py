#!/usr/bin/env python3
"""Shared standalone gpt-image-2 skill helpers."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:
    sys.exit("requests not installed. Run: pip install requests")


CODEX_API_BASE = os.environ.get("CODEX_API_BASE", "https://chatgpt.com/backend-api/codex").rstrip("/")
TOKEN_URL = "https://auth.openai.com/oauth/token"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
USER_AGENT = "codex-tui/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9 (codex-tui; 0.118.0)"
ORIGINATOR = "codex-tui"
DEFAULT_TIMEOUT = int(os.environ.get("CODEX_API_TIMEOUT", "900"))
DEFAULT_CHAT_MODEL = "gpt-5.5"
DEFAULT_IMAGE_TOOL_MODEL = "gpt-image-2"
RELOGIN_REQUIRED_ERROR_MARKERS = (
    "refresh_token_invalidated",
    "token_invalidated",
    "session has ended",
    "please log in again",
)
try:
    from app_config import (  # type: ignore
        DEFAULT_GPT_IMAGE_MAIN_MODEL as PROJECT_DEFAULT_IMAGE_MAIN_MODEL,
        DEFAULT_GPT_REASONING_EFFORT as PROJECT_DEFAULT_REASONING_EFFORT,
        GPT_IMAGE_MAIN_MODELS as PROJECT_IMAGE_MAIN_MODELS,
        GPT_REASONING_EFFORTS as PROJECT_REASONING_EFFORTS,
        get_gpt_provider_config,
    )
except Exception:
    PROJECT_DEFAULT_IMAGE_MAIN_MODEL = DEFAULT_CHAT_MODEL
    PROJECT_DEFAULT_REASONING_EFFORT = "medium"
    PROJECT_IMAGE_MAIN_MODELS = {
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
    }
    PROJECT_REASONING_EFFORTS = {
        "none",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    }
    get_gpt_provider_config = None

SUPPORTED_IMAGE_MAIN_MODELS = set(PROJECT_IMAGE_MAIN_MODELS)
SUPPORTED_REASONING_EFFORTS = set(PROJECT_REASONING_EFFORTS)
DEFAULT_IMAGE_MAIN_MODEL = (
    os.environ.get("GPT_IMAGE_MAIN_MODEL")
    or os.environ.get("GPT_PROVIDER_MAIN_MODEL")
    or PROJECT_DEFAULT_IMAGE_MAIN_MODEL
)
DEFAULT_REASONING_EFFORT = (
    os.environ.get("GPT_REASONING_EFFORT")
    or os.environ.get("GPT_PROVIDER_REASONING_EFFORT")
    or PROJECT_DEFAULT_REASONING_EFFORT
)


def _codex_api_base() -> str:
    return os.environ.get("CODEX_API_BASE", CODEX_API_BASE).rstrip("/")


class CodexAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class AuthBundle:
    path: Path
    raw: dict[str, Any]
    access_token: str
    refresh_token: str
    id_token: str
    account_id: str
    expired: str


RESOLUTIONS = {
    ("1k", "1:1"): "1024x1024",
    ("1k", "4:3"): "1024x768",
    ("1k", "3:4"): "768x1024",
    ("1k", "16:9"): "1088x608",
    ("1k", "9:16"): "608x1088",
    ("1k", "9:21"): "528x1248",
    ("1k", "3:2"): "1024x688",
    ("1k", "2:3"): "688x1024",
    ("1k", "4:5"): "816x1024",
    ("1k", "5:4"): "1024x816",
    ("1k", "21:9"): "1248x528",
    ("2k", "1:1"): "2048x2048",
    ("2k", "4:3"): "2048x1536",
    ("2k", "3:4"): "1536x2048",
    ("2k", "16:9"): "2048x1152",
    ("2k", "9:16"): "1152x2048",
    ("2k", "9:21"): "880x2048",
    ("2k", "3:2"): "2048x1360",
    ("2k", "2:3"): "1360x2048",
    ("2k", "4:5"): "1632x2048",
    ("2k", "5:4"): "2048x1632",
    ("2k", "21:9"): "2048x880",
    ("4k", "1:1"): "2880x2880",
    ("4k", "4:3"): "3312x2480",
    ("4k", "3:4"): "2480x3312",
    ("4k", "16:9"): "3840x2160",
    ("4k", "9:16"): "2160x3840",
    ("4k", "9:21"): "1648x3840",
    ("4k", "3:2"): "3520x2352",
    ("4k", "2:3"): "2352x3520",
    ("4k", "4:5"): "2576x3216",
    ("4k", "5:4"): "3216x2576",
    ("4k", "21:9"): "3840x1648",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _strict_auth_candidates_enabled() -> bool:
    return str(os.environ.get("CODEX_API_AUTH_STRICT") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def _auth_candidate_paths(existing_only: bool = True) -> list[Path]:
    candidates: list[Path] = []
    explicit = (
        os.environ.get("CODEX_API_AUTH_FILE", "").strip()
        or os.environ.get("GPT_PROVIDER_AUTH_FILE", "").strip()
    )
    if explicit:
        candidates.append(Path(explicit).expanduser())

    explicit_dir = (
        os.environ.get("CODEX_API_AUTH_DIR", "").strip()
        or os.environ.get("GPT_PROVIDER_AUTH_DIR", "").strip()
    )
    if explicit_dir:
        auth_dir = Path(explicit_dir).expanduser()
        candidates.append(auth_dir / "auth.json")
        if auth_dir.exists():
            candidates.extend(
                sorted(
                    auth_dir.glob("codex-*.json"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            )

    strict_explicit = _strict_auth_candidates_enabled() and bool(explicit or explicit_dir)
    if not strict_explicit:
        # Prefer the active Codex auth. Browser account switches generally refresh
        # ~/.codex/auth.json, while older cli-proxy files can belong to stale accounts.
        candidates.append(Path.home() / ".codex" / "auth.json")
        cli_dir = Path.home() / ".cli-proxy-api"
        if cli_dir.exists():
            candidates.extend(sorted(cli_dir.glob("codex-*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        path = path.expanduser()
        if path in seen:
            continue
        seen.add(path)
        if not existing_only or path.exists():
            unique.append(path)
    return unique


def _auth_candidates() -> list[Path]:
    return _auth_candidate_paths(existing_only=True)


def _extract_tokens(raw: dict[str, Any]) -> tuple[str, str, str, str, str]:
    token_obj = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else raw
    access_token = str(token_obj.get("access_token") or raw.get("access_token") or "")
    refresh_token = str(token_obj.get("refresh_token") or raw.get("refresh_token") or "")
    id_token = str(token_obj.get("id_token") or raw.get("id_token") or "")
    account_id = str(token_obj.get("account_id") or raw.get("account_id") or "")
    expired = str(token_obj.get("expired") or token_obj.get("expire") or raw.get("expired") or raw.get("expire") or "")
    return access_token, refresh_token, id_token, account_id, expired


def load_auth() -> AuthBundle:
    errors: list[str] = []
    for path in _auth_candidates():
        try:
            raw = _read_json(path)
            last_refresh_error = str(raw.get("last_refresh_error") or "")
            if _requires_relogin_error(last_refresh_error):
                errors.append(f"{path}: requires re-login ({last_refresh_error[:160]})")
                continue
            access_token, refresh_token, id_token, account_id, expired = _extract_tokens(raw)
            if access_token and refresh_token:
                return AuthBundle(path, raw, access_token, refresh_token, id_token, account_id, expired)
            errors.append(f"{path}: missing access_token or refresh_token")
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    detail = "; ".join(errors) if errors else "no auth files found"
    raise CodexAPIError(f"Cannot load Codex auth: {detail}")


def inspect_auth_status() -> dict[str, Any]:
    """Inspect auth files without returning token values or refreshing tokens."""
    result: dict[str, Any] = {
        "configured": False,
        "selected_path": "",
        "candidate_count": 0,
        "candidates": [],
        "error": "",
    }
    for path in _auth_candidate_paths(existing_only=False):
        item: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "readable": False,
            "has_access_token": False,
            "has_refresh_token": False,
            "has_id_token": False,
            "has_account_id": False,
            "expired": "",
            "expiring": None,
            "requires_relogin": False,
            "last_refresh_error": "",
            "status": "missing",
            "selected": False,
        }
        if path.exists():
            try:
                raw = _read_json(path)
                access_token, refresh_token, id_token, account_id, expired = _extract_tokens(raw)
                last_refresh_error = str(raw.get("last_refresh_error") or "")
                requires_relogin = _requires_relogin_error(last_refresh_error)
                item.update(
                    {
                        "readable": True,
                        "has_access_token": bool(access_token),
                        "has_refresh_token": bool(refresh_token),
                        "has_id_token": bool(id_token),
                        "has_account_id": bool(account_id),
                        "expired": expired,
                        "requires_relogin": requires_relogin,
                        "last_refresh_error": last_refresh_error,
                        "status": "需要重新登录" if requires_relogin else ("正常" if access_token and refresh_token else "异常"),
                    }
                )
                if access_token and refresh_token and not requires_relogin:
                    auth = AuthBundle(path, raw, access_token, refresh_token, id_token, account_id, expired)
                    item["expiring"] = _is_expiring(auth)
                    if not result["configured"]:
                        item["selected"] = True
                        result["configured"] = True
                        result["selected_path"] = str(path)
            except Exception as exc:
                item["error"] = str(exc)
                if not result["error"]:
                    result["error"] = str(exc)
        result["candidates"].append(item)
    result["candidate_count"] = len(result["candidates"])
    if not result["configured"] and not result["error"]:
        if any(item.get("requires_relogin") for item in result["candidates"]):
            result["error"] = "Codex auth requires re-login"
        else:
            result["error"] = "no usable auth file found"
    result["requires_relogin"] = any(item.get("requires_relogin") for item in result["candidates"])
    return result


def _parse_time(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _jwt_claims(token: str) -> dict[str, Any]:
    if token.count(".") < 2:
        return {}
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    except Exception:
        return {}


def _is_expiring(auth: AuthBundle) -> bool:
    expires_at = _parse_time(auth.expired)
    if expires_at is not None:
        return expires_at.timestamp() - time.time() < 300
    claims = _jwt_claims(auth.access_token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)):
        return float(exp) - time.time() < 300
    return False


def _requires_relogin_error(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and any(marker in text for marker in RELOGIN_REQUIRED_ERROR_MARKERS))


def _write_auth_error(path: Path, raw: dict[str, Any], message: str) -> None:
    try:
        raw["last_refresh_error"] = str(message or "")[:1200]
        raw["last_refresh_error_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _write_auth(path: Path, raw: dict[str, Any], token_data: dict[str, Any]) -> None:
    target = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else raw
    target["access_token"] = token_data["access_token"]
    target["refresh_token"] = token_data["refresh_token"]
    target["id_token"] = token_data["id_token"]
    target["account_id"] = token_data.get("account_id", target.get("account_id", ""))
    target["expired"] = token_data["expired"]
    target["last_refresh"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if "tokens" in raw and isinstance(raw["tokens"], dict):
        raw["last_refresh"] = target["last_refresh"]
    raw["last_refresh_error"] = ""
    raw.pop("last_refresh_error_at", None)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def refresh_auth(auth: AuthBundle, session: requests.Session | None = None) -> AuthBundle:
    sess = session or requests.Session()
    data = {
        "client_id": CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": auth.refresh_token,
        "scope": "openid profile email",
    }
    resp = sess.post(
        TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        timeout=60,
    )
    if resp.status_code != 200:
        message = f"Token refresh failed with status {resp.status_code}: {resp.text[:1000]}"
        _write_auth_error(auth.path, auth.raw, message)
        raise CodexAPIError(message, resp.status_code)
    payload = resp.json()
    expires_in = int(payload.get("expires_in") or 0)
    expired = datetime.now(timezone.utc).timestamp() + max(expires_in, 0)
    id_token = str(payload.get("id_token") or auth.id_token)
    claims = _jwt_claims(id_token)
    auth_info = claims.get("https://api.openai.com/auth")
    if not isinstance(auth_info, dict):
        auth_info = {}
    token_data = {
        "access_token": str(payload.get("access_token") or ""),
        "refresh_token": str(payload.get("refresh_token") or auth.refresh_token),
        "id_token": id_token,
        "account_id": str(auth_info.get("chatgpt_account_id") or claims.get("account_id") or auth.account_id or ""),
        "expired": datetime.fromtimestamp(expired, timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    if not token_data["access_token"]:
        raise CodexAPIError("Token refresh response did not include access_token")
    _write_auth(auth.path, auth.raw, token_data)
    return load_auth()


def get_auth(session: requests.Session | None = None) -> AuthBundle:
    auth = load_auth()
    if _is_expiring(auth):
        auth = refresh_auth(auth, session=session)
    return auth


def codex_headers(auth: AuthBundle, stream: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {auth.access_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
        "Connection": "Keep-Alive",
        "User-Agent": USER_AGENT,
        "OpenAI-Beta": "responses=experimental",
        "Originator": ORIGINATOR,
        "Session_id": str(uuid.uuid4()),
    }
    if auth.account_id:
        headers["Chatgpt-Account-Id"] = auth.account_id
    return headers


def _event_message(event: dict[str, Any]) -> str:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    error = response.get("error") if isinstance(response.get("error"), dict) else event.get("error")
    pieces = [str(event.get("type") or "upstream_error")]
    if response.get("status"):
        pieces.append(f"status={response['status']}")
    incomplete_details = response.get("incomplete_details")
    if incomplete_details:
        pieces.append(f"incomplete_details={incomplete_details}")
    if isinstance(error, dict):
        if error.get("message"):
            pieces.append(str(error["message"]))
        if error.get("code"):
            pieces.append(f"code={error['code']}")
    elif error:
        pieces.append(str(error))
    request_id = response.get("id") or event.get("request_id") or event.get("id")
    if request_id:
        pieces.append(f"request_id={request_id}")
    return ": ".join(pieces)


def iter_sse_events(resp: requests.Response) -> Iterable[dict[str, Any]]:
    for line in resp.iter_lines(chunk_size=1024 * 1024, decode_unicode=True):
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CodexAPIError(f"Invalid SSE JSON: {exc}: {payload[:200]}") from exc


def _redact_image_request_for_log(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"result", "b64_json"}:
                out[key] = f"[base64 omitted: {len(str(item))} chars]"
            elif key == "image_url" and isinstance(item, str) and item.startswith("data:"):
                out[key] = f"[data image omitted: {len(item)} chars]"
            else:
                out[key] = _redact_image_request_for_log(item)
        return out
    if isinstance(value, list):
        return [_redact_image_request_for_log(item) for item in value]
    return value


def _is_image_request(payload: dict[str, Any]) -> bool:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        return False
    return any(isinstance(tool, dict) and tool.get("type") == "image_generation" for tool in tools)


def _short_log_value(value: Any, max_len: int = 220) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        text = json.dumps(_redact_image_request_for_log(value), ensure_ascii=False, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > max_len:
        return f"{text[:max_len]}…"
    return text


def _event_error(event: dict[str, Any]) -> Any:
    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    return response.get("error") if isinstance(response.get("error"), dict) else event.get("error")


def _log_sse_event(event: dict[str, Any], event_index: int, *, verbose: bool) -> None:
    if not verbose:
        return
    event_type = str(event.get("type") or "")
    parts = [f"#{event_index}", event_type or "unknown_event"]

    response = event.get("response") if isinstance(event.get("response"), dict) else {}
    if response.get("id"):
        parts.append(f"response_id={response['id']}")
    if response.get("status"):
        parts.append(f"response_status={response['status']}")
    if response.get("incomplete_details"):
        parts.append(f"incomplete_details={_short_log_value(response['incomplete_details'])}")

    for key in ("output_index", "content_index", "partial_image_index", "item_id", "response_id"):
        if event.get(key) is not None:
            parts.append(f"{key}={event[key]}")

    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    if item:
        if item.get("type"):
            parts.append(f"item_type={item['type']}")
        if item.get("id"):
            parts.append(f"item_id={item['id']}")
        if item.get("status"):
            parts.append(f"item_status={item['status']}")
        if item.get("action"):
            parts.append(f"action={item['action']}")
        if item.get("model"):
            parts.append(f"item_model={item['model']}")
        if item.get("error"):
            parts.append(f"item_error={_short_log_value(item['error'])}")
        if item.get("revised_prompt"):
            parts.append(f"revised_prompt={_short_log_value(item['revised_prompt'])}")
        if item.get("result"):
            parts.append(f"result_chars={len(str(item['result']))}")

    if event.get("partial_image_b64"):
        parts.append(f"partial_image_b64_chars={len(str(event['partial_image_b64']))}")

    error = _event_error(event)
    if isinstance(error, dict):
        if error.get("code"):
            parts.append(f"error_code={error['code']}")
        if error.get("type"):
            parts.append(f"error_type={error['type']}")
        if error.get("message"):
            parts.append(f"error_message={_short_log_value(error['message'])}")
    elif error:
        parts.append(f"error={_short_log_value(error)}")

    print("🧪 SSE " + " | ".join(parts))


def _log_revised_prompt_from_item(item: dict[str, Any]) -> None:
    revised_prompt = item.get("revised_prompt")
    if revised_prompt:
        print(f"🧾 image_generation_call.revised_prompt: {revised_prompt}")


def _stream_transport_error(exc: requests.exceptions.RequestException, last_event: dict[str, Any] | None, event_index: int) -> CodexAPIError:
    error_type = type(exc).__name__
    detail = str(exc).strip()
    if last_event:
        last_type = str(last_event.get("type") or "unknown_event")
        message = f"stream disconnected before completion; last_event={last_type}; events={event_index}; transport_error={error_type}"
    else:
        message = f"stream disconnected before first event; events={event_index}; transport_error={error_type}"
    if detail:
        message = f"{message}: {detail}"
    return CodexAPIError(message, 502)


def post_codex_images(endpoint: str, payload: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    endpoint_key = str(endpoint or "").strip().strip("/")
    if endpoint_key not in {"generations", "edits"}:
        raise ValueError(f"Unsupported Codex images endpoint: {endpoint}")
    auth = get_auth()
    url = f"{_codex_api_base()}/images/{endpoint_key}"
    print(f"🧾 Codex images/{endpoint_key} request body:")
    print(json.dumps(_redact_image_request_for_log(payload), ensure_ascii=False, indent=2))
    resp = requests.post(url, headers=codex_headers(auth, stream=False), json=payload, timeout=timeout)
    if resp.status_code >= 400:
        message = f"HTTP {resp.status_code}: {resp.text[:2000]}"
        if _requires_relogin_error(message):
            _write_auth_error(auth.path, auth.raw, message)
        raise CodexAPIError(message, resp.status_code)
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise CodexAPIError(f"Invalid images/{endpoint_key} JSON: {exc}: {resp.text[:200]}", 502) from exc
    if not isinstance(data, dict):
        raise CodexAPIError(f"images/{endpoint_key} response was not a JSON object", 502)
    if not isinstance(data.get("data"), list) or not data["data"]:
        raise CodexAPIError(f"images/{endpoint_key} response did not include image data", 502)
    return data


def post_responses_stream(payload: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    auth = get_auth()
    url = f"{_codex_api_base()}/responses"
    request_payload = dict(payload)
    request_payload["stream"] = True
    image_request = _is_image_request(payload)
    if image_request:
        print("🧾 Codex image request body:")
        print(json.dumps(_redact_image_request_for_log(request_payload), ensure_ascii=False, indent=2))
    resp = requests.post(url, headers=codex_headers(auth, stream=True), json=request_payload, stream=True, timeout=timeout)
    if resp.status_code >= 400:
        message = f"HTTP {resp.status_code}: {resp.text[:2000]}"
        if _requires_relogin_error(message):
            _write_auth_error(auth.path, auth.raw, message)
        raise CodexAPIError(message, resp.status_code)
    last_event: dict[str, Any] | None = None
    output_items: dict[int, dict[str, Any]] = {}
    output_items_fallback: list[dict[str, Any]] = []
    event_index = 0
    try:
        for event in iter_sse_events(resp):
            event_index += 1
            last_event = event
            event_type = str(event.get("type") or "")
            _log_sse_event(event, event_index, verbose=image_request)
            if event_type == "response.output_item.done" and isinstance(event.get("item"), dict):
                _log_revised_prompt_from_item(event["item"])
                output_index = event.get("output_index")
                if isinstance(output_index, int):
                    output_items[output_index] = event["item"]
                else:
                    output_items_fallback.append(event["item"])
                continue
            if event_type == "response.completed":
                response = event.get("response")
                if isinstance(response, dict) and not response.get("output"):
                    ordered = [output_items[i] for i in sorted(output_items)]
                    ordered.extend(output_items_fallback)
                    if ordered:
                        response["output"] = ordered
                return event
            if event_type in {"response.failed", "response.incomplete"}:
                for item in [output_items[i] for i in sorted(output_items)] + output_items_fallback:
                    _log_revised_prompt_from_item(item)
                if image_request:
                    print("🧪 SSE failure event:")
                    print(json.dumps(_redact_image_request_for_log(event), ensure_ascii=False, indent=2))
                raise CodexAPIError(f"upstream {event_type}: {_event_message(event)}", 502)
    except requests.exceptions.RequestException as exc:
        raise _stream_transport_error(exc, last_event, event_index) from exc
    if last_event:
        raise CodexAPIError(f"stream disconnected before completion; last_event={last_event.get('type')}", 502)
    raise CodexAPIError("stream disconnected before completion", 502)


def _response_json_to_event(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CodexAPIError("nonstream response was not a JSON object", 502)
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    status = str(response.get("status") or "").strip().lower()
    event_type = f"response.{status}" if status else "response.completed"
    event = {"type": event_type, "response": response}
    if status in {"failed", "incomplete"}:
        raise CodexAPIError(f"upstream {event_type}: {_event_message(event)}", 502)
    if status and status != "completed":
        raise CodexAPIError(f"upstream response did not complete: status={status}", 502)
    return {"type": "response.completed", "response": response}


def post_responses_nonstream(payload: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    auth = get_auth()
    url = f"{_codex_api_base()}/responses"
    request_payload = dict(payload)
    request_payload["stream"] = False
    image_request = _is_image_request(request_payload)
    if image_request:
        print("🧾 Codex image nonstream request body:")
        print(json.dumps(_redact_image_request_for_log(request_payload), ensure_ascii=False, indent=2))
    resp = requests.post(url, headers=codex_headers(auth, stream=False), json=request_payload, stream=False, timeout=timeout)
    if resp.status_code >= 400:
        message = f"HTTP {resp.status_code}: {resp.text[:2000]}"
        if _requires_relogin_error(message):
            _write_auth_error(auth.path, auth.raw, message)
        raise CodexAPIError(message, resp.status_code)
    try:
        return _response_json_to_event(resp.json())
    except json.JSONDecodeError as exc:
        raise CodexAPIError(f"Invalid nonstream JSON: {exc}: {resp.text[:200]}") from exc


def _is_stream_transport_disconnect(error: Exception | str) -> bool:
    text = str(error or "").lower()
    return (
        "stream disconnected" in text
        or "transport_error=chunkedencodingerror" in text
        or "chunkedencodingerror" in text
        or "response ended prematurely" in text
    )


def normalize_transport_mode(value: str | None) -> str:
    mode = str(value or "stream_then_nonstream").strip().lower()
    return mode if mode in {"stream", "nonstream", "stream_then_nonstream"} else "stream_then_nonstream"


def post_responses(payload: dict[str, Any], timeout: int = DEFAULT_TIMEOUT, transport_mode: str | None = "stream_then_nonstream") -> dict[str, Any]:
    mode = normalize_transport_mode(transport_mode)
    if mode == "nonstream":
        return post_responses_nonstream(payload, timeout=timeout)
    if mode == "stream":
        return post_responses_stream(payload, timeout=timeout)
    try:
        return post_responses_stream(payload, timeout=timeout)
    except CodexAPIError as exc:
        if not _is_stream_transport_disconnect(exc):
            raise
        print(f"⚠️ stream transport failed; retrying nonstream: {exc}")
        return post_responses_nonstream(payload, timeout=timeout)


def build_text_request(
    prompt: str,
    model: str = DEFAULT_CHAT_MODEL,
    system: str | None = None,
    reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
    return {
        "model": model,
        "instructions": system or "",
        "input": [{"type": "message", "role": "user", "content": content}],
        "stream": True,
        "store": False,
        "reasoning": {"effort": normalize_reasoning_effort(reasoning_effort), "summary": "auto"},
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
    }


def extract_text(completed_event: dict[str, Any]) -> str:
    response = completed_event.get("response") if isinstance(completed_event.get("response"), dict) else {}
    output = response.get("output") if isinstance(response.get("output"), list) else []
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                    if part.get("text"):
                        parts.append(str(part["text"]))
        elif item.get("type") in {"output_text", "message"} and item.get("text"):
            parts.append(str(item["text"]))
    return "".join(parts).strip()


def validate_pixel_size(size: str) -> str:
    low = size.lower().strip()
    if "x" not in low:
        raise ValueError(f"Unsupported size '{size}'. Use auto, 1k, 2k, 4k, or a valid WxH value.")
    left, right = low.split("x", 1)
    if not left.isdigit() or not right.isdigit():
        raise ValueError(f"Unsupported size '{size}'. Width and height must be numeric.")
    width, height = int(left), int(right)
    pixels = width * height
    short_edge = min(width, height)
    long_edge = max(width, height)
    if long_edge > 3840:
        raise ValueError(f"Unsupported size '{size}'. Maximum edge length is 3840px.")
    if width % 16 != 0 or height % 16 != 0:
        raise ValueError(f"Unsupported size '{size}'. Both edges must be multiples of 16px.")
    if long_edge / short_edge > 3:
        raise ValueError(f"Unsupported size '{size}'. Long:short edge ratio must not exceed 3:1.")
    if pixels < 655_360 or pixels > 8_294_400:
        raise ValueError(f"Unsupported size '{size}'. Total pixels must be between 655,360 and 8,294,400.")
    return f"{width}x{height}"


def resolve_size(size_arg: str, ratio: str | None) -> str:
    low = (size_arg or "auto").lower().strip()
    if low == "auto":
        return low
    if low in {"1k", "2k", "4k"}:
        selected_ratio = ratio or "1:1"
        if (low, selected_ratio) not in RESOLUTIONS:
            raise ValueError(f"Unsupported ratio '{selected_ratio}' for {low}.")
        return validate_pixel_size(RESOLUTIONS[(low, selected_ratio)])
    return validate_pixel_size(low)


def image_file_to_data_url(path: str) -> str:
    file_path = Path(path).expanduser()
    data = file_path.read_bytes()
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


FAITHFUL_IMAGE_INSTRUCTIONS = """
Use the user's prompt as the authoritative image brief.
Do not rewrite, summarize, simplify, moralize, or add creative elements.
Preserve concrete subject, pose, composition, style, camera, lighting, aspect ratio, text, and negative constraints exactly.
If an internal image prompt revision is required, make it a faithful restatement only.
""".strip()


def normalize_prompt_mode(value: str | None) -> str:
    mode = str(value or "smart").strip().lower()
    return "faithful" if mode in {"faithful", "literal", "忠实原文"} else "smart"


def normalize_image_main_model(value: str | None) -> str:
    configured = DEFAULT_IMAGE_MAIN_MODEL
    if get_gpt_provider_config:
        try:
            configured = str(get_gpt_provider_config().get("image_main_model") or configured)
        except Exception:
            pass
    if configured not in SUPPORTED_IMAGE_MAIN_MODELS:
        configured = PROJECT_DEFAULT_IMAGE_MAIN_MODEL
    model = str(value or configured).strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model):
        return model
    return configured


def normalize_reasoning_effort(value: str | None) -> str:
    configured = DEFAULT_REASONING_EFFORT
    if get_gpt_provider_config:
        try:
            configured = str(get_gpt_provider_config().get("reasoning_effort") or configured)
        except Exception:
            pass
    configured = str(configured or "").strip().lower()
    if configured not in SUPPORTED_REASONING_EFFORTS:
        configured = PROJECT_DEFAULT_REASONING_EFFORT
    effort = str(value or configured).strip().lower()
    return effort if effort in SUPPORTED_REASONING_EFFORTS else configured


def prepare_image_prompt(prompt: str, prompt_mode: str | None = "smart") -> tuple[str, str]:
    mode = normalize_prompt_mode(prompt_mode)
    if mode != "faithful":
        return prompt, ""
    wrapped = "\n".join(
        [
            "Generate an image using the following prompt as a literal source brief.",
            "Rules:",
            "- Preserve the user's original prompt semantics exactly.",
            "- Do not add new subjects, settings, props, styles, emotions, or composition changes.",
            "- Do not make the prompt more generic.",
            "- Keep negative constraints active.",
            "- If you revise internally for the image tool, make it a faithful restatement only.",
            "",
            "User prompt:",
            "<<<",
            prompt,
            ">>>",
        ]
    )
    return wrapped, FAITHFUL_IMAGE_INSTRUCTIONS


def build_image_request(
    prompt: str,
    tool: dict[str, Any],
    images: list[str] | None = None,
    prompt_mode: str | None = "smart",
    main_model: str | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    request_prompt, instructions = prepare_image_prompt(prompt, prompt_mode)
    selected_model = normalize_image_main_model(main_model)
    selected_effort = normalize_reasoning_effort(reasoning_effort)
    content: list[dict[str, Any]] = [{"type": "input_text", "text": request_prompt}]
    for image_url in images or []:
        content.append({"type": "input_image", "image_url": image_url})
    return {
        "instructions": instructions,
        "stream": True,
        "reasoning": {"effort": selected_effort, "summary": "auto"},
        "parallel_tool_calls": True,
        "include": ["reasoning.encrypted_content"],
        "model": selected_model,
        "store": False,
        "tool_choice": {"type": "image_generation"},
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [tool],
    }


def extract_images(completed_event: dict[str, Any], response_format: str = "b64_json") -> dict[str, Any]:
    response = completed_event.get("response") if isinstance(completed_event.get("response"), dict) else {}
    output = response.get("output") if isinstance(response.get("output"), list) else []
    created = int(response.get("created_at") or time.time())
    data: list[dict[str, Any]] = []
    first_meta: dict[str, Any] = {}
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "image_generation_call":
            continue
        result = str(item.get("result") or "").strip()
        if not result:
            continue
        if not first_meta:
            first_meta = item
        if response_format == "url":
            output_format = str(item.get("output_format") or "png")
            mime = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "webp": "image/webp", "png": "image/png"}.get(output_format, "image/png")
            entry = {"url": f"data:{mime};base64,{result}"}
        else:
            entry = {"b64_json": result}
        if item.get("revised_prompt"):
            entry["revised_prompt"] = item["revised_prompt"]
        data.append(entry)
    if not data:
        text_output = extract_text(completed_event)
        if text_output:
            raise CodexAPIError(f"upstream did not return image output; output_text={_short_log_value(text_output, 500)}", 502)
        raise CodexAPIError("upstream did not return image output", 502)
    out: dict[str, Any] = {"created": created, "data": data}
    for key in ("background", "output_format", "quality", "size"):
        if first_meta.get(key):
            out[key] = first_meta[key]
    usage = response.get("tool_usage", {}).get("image_gen") if isinstance(response.get("tool_usage"), dict) else None
    if usage:
        out["usage"] = usage
    return out


def decode_image_items(data: dict[str, Any]) -> list[bytes]:
    return [item["image_bytes"] for item in decode_image_items_with_metadata(data)]


def decode_image_items_with_metadata(data: dict[str, Any]) -> list[dict[str, Any]]:
    images: list[bytes] = []
    items_with_meta: list[dict[str, Any]] = []
    for item in data.get("data", []):
        if not isinstance(item, dict):
            continue
        b64 = str(item.get("b64_json") or "")
        if not b64 and str(item.get("url") or "").startswith("data:"):
            b64 = str(item["url"]).split(",", 1)[1]
        if b64:
            image_bytes = base64.b64decode(b64)
            images.append(image_bytes)
            items_with_meta.append(
                {
                    "image_bytes": image_bytes,
                    "revised_prompt": str(item.get("revised_prompt") or ""),
                }
            )
    return items_with_meta
