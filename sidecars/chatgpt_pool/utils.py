from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_uuid() -> str:
    return str(uuid.uuid4())


def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = str(token or "").split(".")[1]
        payload += "=" * ((4 - len(payload) % 4) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def jwt_exp(token: str) -> int:
    try:
        return int(decode_jwt_payload(token).get("exp") or 0)
    except (TypeError, ValueError):
        return 0


def iso_from_timestamp(value: object) -> str:
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def token_preview(token: str) -> str:
    value = str(token or "")
    if len(value) <= 16:
        return value[:4] + "..." if value else ""
    return f"{value[:8]}...{value[-6:]}"


def account_id_for_token(token: str) -> str:
    value = str(token or "").encode("utf-8", "ignore")
    if not value:
        return ""
    return hashlib.sha256(value).hexdigest()[:24]


def extract_email(access_token: str, id_token: str = "", explicit: str = "") -> str:
    if explicit:
        return explicit
    for payload in (decode_jwt_payload(access_token), decode_jwt_payload(id_token)):
        profile = payload.get("https://api.openai.com/profile")
        if isinstance(profile, dict) and profile.get("email"):
            return str(profile["email"])
        if payload.get("email"):
            return str(payload["email"])
    return ""


def extract_plan(access_token: str, explicit: str = "") -> str:
    explicit_value = str(explicit or "").strip()
    if explicit_value and explicit_value.lower() not in {"unknown", "none", "null"}:
        return explicit_value
    payload = decode_jwt_payload(access_token)
    auth = payload.get("https://api.openai.com/auth")
    if isinstance(auth, dict):
        for key in ("chatgpt_plan_type", "plan_type", "account_plan"):
            if auth.get(key):
                return str(auth[key])
    return "unknown"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def seconds_until_expiry(access_token: str) -> int | None:
    exp = jwt_exp(access_token)
    if exp <= 0:
        return None
    return exp - int(time.time())
