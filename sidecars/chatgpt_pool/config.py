from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_DIR / "data" / "chatgpt_pool"
SETTINGS_PATH = PROJECT_DIR / "settings.json"
DEFAULT_DB_PATH = DATA_DIR / "accounts.db"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
DEFAULT_MODEL = "gpt-image-2"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_LEASE_TIMEOUT_SECONDS = 1200


@dataclass(frozen=True)
class SidecarSettings:
    host: str
    port: int
    auth_key: str
    db_path: Path
    generation_model: str
    timeout_seconds: int
    lease_timeout_seconds: int
    refresh_interval_seconds: int
    max_account_concurrency: int


def _load_project_settings() -> dict[str, Any]:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _as_int(value: object, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def load_settings() -> SidecarSettings:
    section = _load_project_settings().get("chatgpt_pool")
    cfg = section if isinstance(section, dict) else {}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    auth_key = str(os.environ.get("CHATGPT_POOL_AUTH_KEY") or cfg.get("auth_key") or "").strip()
    if not auth_key:
        # Standalone launches without server.py can still run, but callers must
        # read the printed/generated key from their configured settings path.
        auth_key = "sk-local-" + secrets.token_urlsafe(24)
    timeout_seconds = _as_int(cfg.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS)
    lease_timeout_default = max(DEFAULT_LEASE_TIMEOUT_SECONDS, timeout_seconds + 300)
    lease_timeout_seconds = _as_int(cfg.get("lease_timeout_seconds"), lease_timeout_default, minimum=60)
    lease_timeout_seconds = max(lease_timeout_seconds, timeout_seconds + 60)
    return SidecarSettings(
        host=str(os.environ.get("CHATGPT_POOL_HOST") or cfg.get("host") or DEFAULT_HOST).strip() or DEFAULT_HOST,
        port=_as_int(os.environ.get("CHATGPT_POOL_PORT") or cfg.get("port"), DEFAULT_PORT),
        auth_key=auth_key,
        db_path=Path(os.environ.get("CHATGPT_POOL_DB") or cfg.get("db_path") or DEFAULT_DB_PATH).expanduser(),
        generation_model=str(cfg.get("generation_model") or DEFAULT_MODEL),
        timeout_seconds=timeout_seconds,
        lease_timeout_seconds=lease_timeout_seconds,
        refresh_interval_seconds=_as_int(cfg.get("refresh_interval_seconds"), 300),
        max_account_concurrency=_as_int(cfg.get("max_account_concurrency"), 1),
    )
