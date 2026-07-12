"""GitHub Release update status shared by source, Docker, and desktop builds."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .version import APP_VERSION

GITHUB_REPOSITORY = "DreamLoveBetty/CanvasHub"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases/latest"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
UPDATE_CACHE_TTL_SECONDS = 15 * 60
UPDATE_REQUEST_TIMEOUT_SECONDS = 6

_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "status": None,
    "last_success": None,
}


def _current_version() -> str:
    return str(os.environ.get("CANVASHUB_APP_VERSION") or APP_VERSION).strip().lstrip("vV")


def _deployment_type() -> str:
    explicit = str(os.environ.get("CANVASHUB_DEPLOYMENT") or "").strip().lower()
    if explicit in {"electron", "docker", "source"}:
        return explicit
    if str(os.environ.get("CANVASHUB_DATA_DIR") or "").strip():
        return "electron"
    if Path("/.dockerenv").exists() or str(os.environ.get("CONTAINER") or "").strip():
        return "docker"
    return "source"


def _version_parts(value: str) -> tuple[int, ...]:
    normalized = str(value or "").strip().lstrip("vV")
    match = re.match(r"^(\d+(?:\.\d+)*)", normalized)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def _is_newer_version(latest: str, current: str) -> bool:
    latest_parts = _version_parts(latest)
    current_parts = _version_parts(current)
    if not latest_parts or not current_parts:
        return False
    width = max(len(latest_parts), len(current_parts))
    return latest_parts + (0,) * (width - len(latest_parts)) > current_parts + (0,) * (width - len(current_parts))


def _base_status() -> dict[str, Any]:
    return {
        "current_version": _current_version(),
        "latest_version": "",
        "update_available": False,
        "deployment": _deployment_type(),
        "release_name": "",
        "release_date": "",
        "release_url": RELEASES_URL,
        "checked_at": 0,
        "stale": True,
        "check_error": "",
    }


def _fetch_latest_release() -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"CanvasHub/{_current_version()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))

    latest_version = str(payload.get("tag_name") or "").strip().lstrip("vV")
    if not _version_parts(latest_version):
        raise ValueError("GitHub Release 缺少有效版本号")

    current_version = _current_version()
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "update_available": _is_newer_version(latest_version, current_version),
        "deployment": _deployment_type(),
        "release_name": str(payload.get("name") or payload.get("tag_name") or "").strip(),
        "release_date": str(payload.get("published_at") or "").strip(),
        "release_url": str(payload.get("html_url") or RELEASES_URL).strip(),
        "checked_at": int(time.time()),
        "stale": False,
        "check_error": "",
    }


def _error_message(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"GitHub Release 查询失败（HTTP {error.code}）"
    if isinstance(error, urllib.error.URLError):
        return f"GitHub Release 连接失败：{error.reason}"
    return str(error) or error.__class__.__name__


def get_app_update_status() -> dict[str, Any]:
    """Return a cached update result; network failures degrade to stale data."""
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get("status")
        if isinstance(cached, dict) and now < float(_CACHE.get("expires_at") or 0):
            result = dict(cached)
            result["current_version"] = _current_version()
            result["deployment"] = _deployment_type()
            result["update_available"] = _is_newer_version(
                str(result.get("latest_version") or ""),
                str(result.get("current_version") or ""),
            )
            return result

        try:
            status = _fetch_latest_release()
            _CACHE["last_success"] = dict(status)
        except Exception as error:
            previous = _CACHE.get("last_success")
            status = dict(previous) if isinstance(previous, dict) else _base_status()
            status.update({
                "current_version": _current_version(),
                "deployment": _deployment_type(),
                "stale": True,
                "check_error": _error_message(error),
            })
            status["update_available"] = _is_newer_version(
                str(status.get("latest_version") or ""),
                str(status.get("current_version") or ""),
            )

        _CACHE["status"] = dict(status)
        _CACHE["expires_at"] = time.monotonic() + UPDATE_CACHE_TTL_SECONDS
        return dict(status)
