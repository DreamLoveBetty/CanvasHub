#!/usr/bin/env python3
"""Persist Pinterest Pins under SOURCE_IMAGE_DIR without indexing them as generated assets."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image

from .storage_paths import SOURCE_IMAGE_DIR
from .thumb_cache import thumb_url_for_media_url


PINTEREST_SOURCE_DIR = SOURCE_IMAGE_DIR / "pinterest"
DOWNLOAD_TIMEOUT_SECONDS = 60
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_PROMPT_BYTES = 256 * 1024
MAX_REDIRECTS = 5
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
PIL_FORMAT_EXTENSIONS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

_PIN_LOCKS: dict[str, threading.Lock] = {}
_PIN_LOCKS_GUARD = threading.Lock()
_RUNS: dict[str, dict[str, Any]] = {}
_RUNS_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_id(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", text):
        raise ValueError(f"Pinterest {label} 无效")
    return text


def _pin_directory(board_id: Any, pin_id: Any) -> Path:
    return PINTEREST_SOURCE_DIR / _safe_id(board_id, "图板 ID") / _safe_id(pin_id, "Pin ID")


def _existing_image(pin_dir: Path) -> Path | None:
    for extension in IMAGE_EXTENSIONS:
        candidate = pin_dir / f"image{extension}"
        if candidate.is_file():
            return candidate
    return None


def _prompt_sidecar(image_path: Path) -> Path:
    return image_path.with_suffix(".md")


def _relative_path(path: Path) -> str:
    return path.relative_to(SOURCE_IMAGE_DIR).as_posix()


def _source_image_url(relative_path: str) -> str:
    encoded = urllib.parse.quote(relative_path.replace("\\", "/"), safe="/")
    return f"/source_image/{encoded}"


def _prompt_sidecar_fields(image_path: Path) -> dict[str, Any]:
    empty = {
        "analyzed": False,
        "analysis_prompt": "",
        "analysis_prompt_relative_path": "",
        "analyzed_at": "",
    }
    prompt_path = _prompt_sidecar(image_path)
    if not prompt_path.is_file():
        return empty
    try:
        if prompt_path.stat().st_size > MAX_PROMPT_BYTES:
            return empty
        prompt = prompt_path.read_text(encoding="utf-8").strip()
        if not prompt:
            return empty
        analyzed_at = datetime.fromtimestamp(
            prompt_path.stat().st_mtime,
            timezone.utc,
        ).isoformat().replace("+00:00", "Z")
    except Exception:
        return empty
    return {
        "analyzed": True,
        "analysis_prompt": prompt,
        "analysis_prompt_relative_path": _relative_path(prompt_path),
        "analyzed_at": analyzed_at,
    }


def pinterest_cached_pin_fields(board_id: Any, pin_id: Any) -> dict[str, Any]:
    empty = {
        "local_cached": False,
        "local_image_url": "",
        "local_thumb_url": "",
        "local_relative_path": "",
        "local_downloaded_at": "",
        "local_file_size": 0,
        "analyzed": False,
        "analysis_prompt": "",
        "analysis_prompt_relative_path": "",
        "analyzed_at": "",
    }
    try:
        pin_dir = _pin_directory(board_id, pin_id)
    except ValueError:
        return empty
    image_path = _existing_image(pin_dir)
    metadata_path = pin_dir / "metadata.json"
    if not image_path or not metadata_path.is_file():
        return empty
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return empty
    if not isinstance(metadata, dict):
        return empty
    relative_path = _relative_path(image_path)
    image_url = _source_image_url(relative_path)
    return {
        "local_cached": True,
        "local_image_url": image_url,
        "local_thumb_url": thumb_url_for_media_url(image_url),
        "local_relative_path": relative_path,
        "local_downloaded_at": str(metadata.get("downloaded_at") or ""),
        "local_file_size": int(image_path.stat().st_size),
        **_prompt_sidecar_fields(image_path),
    }


def _local_profile(profile_url: Any) -> dict[str, str]:
    url = str(profile_url or "").strip()
    parsed = urllib.parse.urlparse(url)
    parts = [urllib.parse.unquote(item) for item in parsed.path.split("/") if item]
    username = parts[0] if parts else ""
    return {
        "username": username,
        "name": username,
        "url": url,
        "image_url": "",
    }


def _local_pin_from_directory(board_id: str, pin_dir: Path) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if not pin_dir.is_dir():
        return None
    try:
        pin_id = _safe_id(pin_dir.name, "Pin ID")
    except ValueError:
        return None
    metadata_path = pin_dir / "metadata.json"
    image_path = _existing_image(pin_dir)
    if not image_path or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(metadata, dict):
        return None
    pin = dict(metadata.get("pin") or {}) if isinstance(metadata.get("pin"), dict) else {}
    cached = pinterest_cached_pin_fields(board_id, pin_id)
    if not cached.get("local_cached"):
        return None
    board_name = str(metadata.get("board_name") or pin.get("board_name") or board_id).strip()
    board_url = str(metadata.get("board_url") or pin.get("board_url") or "").strip()
    remote_image_url = str(
        pin.get("image_url")
        or pin.get("display_image_url")
        or pin.get("thumb_url")
        or ""
    ).strip()
    pin.update({
        "id": f"pinterest_{pin_id}",
        "pin_id": pin_id,
        "title": str(pin.get("title") or "Pinterest Pin"),
        "provider": "pinterest",
        "provider_label": "Pinterest",
        "source_kind": "pinterest",
        "source_url": str(metadata.get("source_url") or pin.get("source_url") or ""),
        "board_id": board_id,
        "board_name": board_name,
        "board_url": board_url,
        "remote_image_url": remote_image_url,
        "image_url": str(cached.get("local_image_url") or ""),
        "display_image_url": str(cached.get("local_image_url") or ""),
        "thumb_url": str(cached.get("local_thumb_url") or cached.get("local_image_url") or ""),
        **cached,
    })
    board = {
        "id": board_id,
        "name": board_name,
        "url": board_url,
        "path": urllib.parse.urlparse(board_url).path if board_url else "",
        "description": "",
        "privacy": "local",
        "pin_count": 0,
        "cached_count": 0,
        "section_count": 0,
        "cover_url": str(cached.get("local_thumb_url") or cached.get("local_image_url") or ""),
    }
    return board, pin


def list_local_pinterest_library(
    profile_url: Any = "",
    board_id: Any = "",
    *,
    limit_per_board: int = 500,
) -> dict[str, Any]:
    """Rebuild the Pinterest library exclusively from synchronized local files."""
    safe_limit = max(1, min(5000, int(limit_per_board or 500)))
    requested_board_id = str(board_id or "").strip()
    boards: list[dict[str, Any]] = []
    pins_by_board: dict[str, list[dict[str, Any]]] = {}
    if PINTEREST_SOURCE_DIR.is_dir():
        for board_dir in sorted(PINTEREST_SOURCE_DIR.iterdir(), key=lambda path: path.name):
            if not board_dir.is_dir():
                continue
            try:
                clean_board_id = _safe_id(board_dir.name, "图板 ID")
            except ValueError:
                continue
            board: dict[str, Any] | None = None
            board_pins: list[dict[str, Any]] = []
            for pin_dir in board_dir.iterdir():
                local_item = _local_pin_from_directory(clean_board_id, pin_dir)
                if not local_item:
                    continue
                local_board, pin = local_item
                board = board or local_board
                board_pins.append(pin)
            if not board or not board_pins:
                continue
            board_pins.sort(
                key=lambda pin: (
                    str(pin.get("local_downloaded_at") or ""),
                    str(pin.get("pin_id") or ""),
                ),
                reverse=True,
            )
            board_pins = board_pins[:safe_limit]
            board["pin_count"] = len(board_pins)
            board["cached_count"] = len(board_pins)
            board["cover_url"] = str(
                board_pins[0].get("local_thumb_url")
                or board_pins[0].get("local_image_url")
                or ""
            )
            boards.append(board)
            pins_by_board[clean_board_id] = board_pins

    if requested_board_id:
        pins = list(pins_by_board.get(requested_board_id) or [])
    else:
        pins = [
            pin
            for board in boards
            for pin in pins_by_board.get(str(board.get("id") or ""), [])
        ]
    return {
        "profile": _local_profile(profile_url),
        "boards": boards,
        "pins": pins,
        "active_board_id": requested_board_id,
        "loaded_count": len(pins),
        "cached_count": len(pins),
        "total": len(pins),
        "fetched_at": _now_iso(),
        "source_mode": "local_cache",
        "discovery_mode": "local_cache",
        "local_only": True,
        "remote_checked": False,
        "partial": False,
        "warning": "",
    }


def _validate_image_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not (host == "pinimg.com" or host.endswith(".pinimg.com")):
        raise ValueError("Pinterest 图片地址无效")
    return url


def _download_candidates(pin: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("image_url", "display_image_url", "thumb_url"):
        value = str(pin.get(key) or "").strip()
        if not value or value in candidates:
            continue
        candidates.append(_validate_image_url(value))
    if not candidates:
        raise ValueError("Pinterest Pin 没有可下载的图片")
    return candidates


def _open_image_response(session: requests.Session, candidate: str):
    current_url = _validate_image_url(candidate)
    for redirect_count in range(MAX_REDIRECTS + 1):
        response = session.get(
            current_url,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
                "Referer": "https://www.pinterest.com/",
                "User-Agent": USER_AGENT,
            },
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )
        status_code = int(getattr(response, "status_code", 200) or 200)
        if status_code in REDIRECT_STATUS_CODES:
            location = str(response.headers.get("Location") or "").strip()
            close_response = getattr(response, "close", None)
            if callable(close_response):
                close_response()
            if not location:
                raise RuntimeError("Pinterest 图片重定向缺少目标地址")
            if redirect_count >= MAX_REDIRECTS:
                raise RuntimeError("Pinterest 图片重定向次数过多")
            current_url = _validate_image_url(urllib.parse.urljoin(current_url, location))
            continue
        try:
            response.raise_for_status()
            final_url = _validate_image_url(str(getattr(response, "url", "") or current_url))
        except Exception:
            close_response = getattr(response, "close", None)
            if callable(close_response):
                close_response()
            raise
        return response, final_url
    raise RuntimeError("Pinterest 图片重定向次数过多")


def _pin_lock(board_id: str, pin_id: str) -> threading.Lock:
    key = f"{board_id}:{pin_id}"
    with _PIN_LOCKS_GUARD:
        return _PIN_LOCKS.setdefault(key, threading.Lock())


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def save_pinterest_pin_prompt(
    board_id: Any,
    pin_id: Any,
    prompt: Any,
) -> dict[str, Any]:
    """Persist an analyzed prompt beside its cached Pinterest image."""
    clean_board_id = _safe_id(board_id, "图板 ID")
    clean_pin_id = _safe_id(pin_id, "Pin ID")
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("Pinterest 图片提示词不能为空")
    if "\x00" in clean_prompt:
        raise ValueError("Pinterest 图片提示词包含无效字符")
    encoded = clean_prompt.encode("utf-8")
    if len(encoded) > MAX_PROMPT_BYTES:
        raise ValueError("Pinterest 图片提示词超过 256 KB 限制")

    pin_dir = _pin_directory(clean_board_id, clean_pin_id)
    lock = _pin_lock(clean_board_id, clean_pin_id)
    with lock:
        image_path = _existing_image(pin_dir)
        metadata_path = pin_dir / "metadata.json"
        if not image_path or not metadata_path.is_file():
            raise ValueError("Pinterest 图片尚未同步到本地")
        prompt_path = _prompt_sidecar(image_path)
        _atomic_write_text(prompt_path, f"{clean_prompt}\n")
        fields = pinterest_cached_pin_fields(clean_board_id, clean_pin_id)
        if not fields.get("analyzed"):
            raise RuntimeError("Pinterest 图片提示词保存失败")
    return {
        "ok": True,
        "board_id": clean_board_id,
        "pin_id": clean_pin_id,
        **fields,
    }


def _download_image(pin_dir: Path, candidates: list[str]) -> tuple[Path, dict[str, Any]]:
    errors: list[str] = []
    for candidate in candidates:
        tmp_path = pin_dir / f".image.{uuid.uuid4().hex}.tmp"
        session = requests.Session()
        session.trust_env = False
        response = None
        digest = hashlib.sha256()
        total = 0
        try:
            response, final_url = _open_image_response(session, candidate)
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_IMAGE_BYTES:
                raise RuntimeError("图片超过 50 MB 限制")
            with open(tmp_path, "wb") as output:
                for chunk in response.iter_content(chunk_size=128 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise RuntimeError("图片超过 50 MB 限制")
                    digest.update(chunk)
                    output.write(chunk)
            if not total:
                raise RuntimeError("图片内容为空")
            with Image.open(tmp_path) as image:
                image.verify()
                image_format = str(image.format or "").upper()
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
            extension = (
                PIL_FORMAT_EXTENSIONS.get(image_format)
                or CONTENT_TYPE_EXTENSIONS.get(content_type)
                or ".jpg"
            )
            target = pin_dir / f"image{extension}"
            os.replace(tmp_path, target)
            for stale_extension in IMAGE_EXTENSIONS:
                stale = pin_dir / f"image{stale_extension}"
                if stale != target:
                    stale.unlink(missing_ok=True)
            return target, {
                "remote_url": candidate,
                "final_url": final_url,
                "content_type": content_type,
                "format": image_format,
                "bytes": total,
                "sha256": digest.hexdigest(),
            }
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            errors.append(str(exc))
        finally:
            close_response = getattr(response, "close", None)
            if callable(close_response):
                close_response()
            session.close()
    message = errors[-1] if errors else "未知下载错误"
    raise RuntimeError(f"Pinterest 图片下载失败：{message}")


def download_pinterest_pin(
    board: dict[str, Any],
    pin: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    board_id = _safe_id(board.get("id") or pin.get("board_id"), "图板 ID")
    pin_id = _safe_id(pin.get("pin_id") or str(pin.get("id") or "").removeprefix("pinterest_"), "Pin ID")
    pin_dir = _pin_directory(board_id, pin_id)
    lock = _pin_lock(board_id, pin_id)
    with lock:
        cached = pinterest_cached_pin_fields(board_id, pin_id)
        if cached["local_cached"] and not force:
            return {"ok": True, "downloaded": False, "already_cached": True, **cached}

        pin_dir.mkdir(parents=True, exist_ok=True)
        image_path, download = _download_image(pin_dir, _download_candidates(pin))
        clean_pin = {
            key: value
            for key, value in pin.items()
            if not str(key).startswith("local_")
        }
        metadata = {
            "schema_version": 1,
            "provider": "pinterest",
            "board_id": board_id,
            "board_name": str(board.get("name") or pin.get("board_name") or ""),
            "board_url": str(board.get("url") or pin.get("board_url") or ""),
            "pin_id": pin_id,
            "source_url": str(pin.get("source_url") or ""),
            "downloaded_at": _now_iso(),
            "image_file": image_path.name,
            "image_relative_path": _relative_path(image_path),
            "download": download,
            "pin": clean_pin,
        }
        _atomic_write_json(pin_dir / "metadata.json", metadata)
        cached = pinterest_cached_pin_fields(board_id, pin_id)
        return {"ok": True, "downloaded": True, "already_cached": False, **cached}


def _public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in run.items()
        if not str(key).startswith("_")
    }


def _update_run(run_id: str, **values: Any) -> dict[str, Any]:
    with _RUNS_LOCK:
        run = _RUNS.get(run_id)
        if not run:
            raise ValueError("Pinterest 图板下载任务不存在")
        run.update(values)
        run["updated_at"] = _now_iso()
        total = max(0, int(run.get("total") or 0))
        synced = max(
            0,
            int(run.get("downloaded") or 0) + int(run.get("already_cached") or 0),
        )
        run["synced"] = synced
        if total:
            run["progress_percent"] = min(100, int(synced * 100 / total))
        else:
            run["progress_percent"] = 100 if run.get("status") == "completed" else 0
        return _public_run(run)


def _cleanup_runs() -> None:
    cutoff = time.time() - 24 * 60 * 60
    with _RUNS_LOCK:
        stale_ids = [
            run_id
            for run_id, run in _RUNS.items()
            if float(run.get("_created_epoch") or 0) < cutoff and run.get("status") != "running"
        ]
        for run_id in stale_ids:
            _RUNS.pop(run_id, None)


def _partition_cached_pins(
    board_id: str,
    pins: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    pending_pins: list[dict[str, Any]] = []
    already_cached = 0
    for pin in pins:
        pin_id = pin.get("pin_id") or str(pin.get("id") or "").removeprefix("pinterest_")
        if pinterest_cached_pin_fields(board_id, pin_id).get("local_cached"):
            already_cached += 1
        else:
            pending_pins.append(dict(pin))
    return pending_pins, already_cached


def _run_board_download(run_id: str, board: dict[str, Any], pins: list[dict[str, Any]]) -> None:
    errors: list[dict[str, str]] = []
    with _RUNS_LOCK:
        processed_offset = int((_RUNS.get(run_id) or {}).get("processed") or 0)
    for index, pin in enumerate(pins, start=1):
        pin_id = str(pin.get("pin_id") or "").strip()
        _update_run(run_id, current_pin_id=pin_id, current_title=str(pin.get("title") or "Pinterest Pin"))
        try:
            result = download_pinterest_pin(board, pin)
            with _RUNS_LOCK:
                run = _RUNS[run_id]
                if result.get("downloaded"):
                    run["downloaded"] = int(run.get("downloaded") or 0) + 1
                else:
                    run["already_cached"] = int(run.get("already_cached") or 0) + 1
        except Exception as exc:
            errors.append({"pin_id": pin_id, "error": str(exc)})
            with _RUNS_LOCK:
                run = _RUNS[run_id]
                run["failed"] = int(run.get("failed") or 0) + 1
        _update_run(run_id, processed=processed_offset + index, errors=errors[-20:])

    with _RUNS_LOCK:
        failed = int(_RUNS[run_id].get("failed") or 0)
        downloaded = int(_RUNS[run_id].get("downloaded") or 0)
        already_cached = int(_RUNS[run_id].get("already_cached") or 0)
    status = "partial" if failed and downloaded + already_cached else ("failed" if failed else "completed")
    _update_run(
        run_id,
        status=status,
        phase=status,
        finished_at=_now_iso(),
        current_pin_id="",
        current_title="",
        message=(
            f"新同步 {downloaded} 张，已有本地 {already_cached} 张，失败 {failed} 张"
            if failed
            else f"新同步 {downloaded} 张，已有本地 {already_cached} 张"
        ),
    )


def _run_board_discovery_and_download(
    run_id: str,
    expected_board_id: str,
    discover: Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]],
) -> None:
    try:
        board, pins = discover()
        if not isinstance(board, dict):
            raise ValueError("Pinterest 图板发现结果无效")
        board_id = _safe_id(board.get("id"), "图板 ID")
        if board_id != expected_board_id:
            raise ValueError("Pinterest 图板发现结果不匹配")
        clean_pins = [dict(pin) for pin in pins if isinstance(pin, dict)]
        pending_pins, already_cached = _partition_cached_pins(board_id, clean_pins)
        _update_run(
            run_id,
            board_name=str(board.get("name") or ""),
            phase="downloading",
            total=len(clean_pins),
            processed=already_cached,
            downloaded=0,
            already_cached=already_cached,
            failed=0,
            current_pin_id="",
            current_title="",
            message="已发现 Pinterest 图板，准备同步",
            errors=[],
        )
        _run_board_download(run_id, board, pending_pins)
    except Exception as exc:
        _update_run(
            run_id,
            status="failed",
            phase="failed",
            finished_at=_now_iso(),
            current_pin_id="",
            current_title="",
            message=f"Pinterest 图板发现失败：{exc}",
            errors=[{"pin_id": "", "error": str(exc)}],
        )


def start_pinterest_board_download(
    board: dict[str, Any],
    pins: list[dict[str, Any]],
) -> dict[str, Any]:
    _cleanup_runs()
    board_id = _safe_id(board.get("id"), "图板 ID")
    if not pins:
        raise ValueError("Pinterest 图板没有可下载的 Pin")
    pending_pins, already_cached = _partition_cached_pins(board_id, pins)
    with _RUNS_LOCK:
        existing = next(
            (
                run for run in _RUNS.values()
                if run.get("board_id") == board_id and run.get("status") == "running"
            ),
            None,
        )
        if existing:
            return {"ok": True, "started": False, "run": _public_run(existing)}
        run_id = uuid.uuid4().hex
        now = _now_iso()
        run = {
            "run_id": run_id,
            "board_id": board_id,
            "board_name": str(board.get("name") or ""),
            "status": "running",
            "phase": "downloading",
            "started_at": now,
            "updated_at": now,
            "finished_at": "",
            "total": len(pins),
            "processed": already_cached,
            "downloaded": 0,
            "already_cached": already_cached,
            "synced": already_cached,
            "failed": 0,
            "progress_percent": int(already_cached * 100 / len(pins)),
            "current_pin_id": "",
            "current_title": "",
            "message": "准备同步 Pinterest 图板",
            "errors": [],
            "_created_epoch": time.time(),
        }
        _RUNS[run_id] = run
        public_run = _public_run(run)
    thread = threading.Thread(
        target=_run_board_download,
        args=(run_id, dict(board), pending_pins),
        name=f"pinterest-board-download-{board_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _RUNS_LOCK:
            _RUNS.pop(run_id, None)
        raise
    return {"ok": True, "started": True, "run": public_run}


def start_pinterest_board_sync(
    board_id: Any,
    discover: Callable[[], tuple[dict[str, Any], list[dict[str, Any]]]],
) -> dict[str, Any]:
    """Create a pollable run immediately and perform remote discovery in its worker."""
    _cleanup_runs()
    clean_board_id = _safe_id(board_id, "图板 ID")
    if not callable(discover):
        raise ValueError("Pinterest 图板发现器无效")
    with _RUNS_LOCK:
        existing = next(
            (
                run for run in _RUNS.values()
                if run.get("board_id") == clean_board_id and run.get("status") == "running"
            ),
            None,
        )
        if existing:
            return {"ok": True, "started": False, "run": _public_run(existing)}
        run_id = uuid.uuid4().hex
        now = _now_iso()
        run = {
            "run_id": run_id,
            "board_id": clean_board_id,
            "board_name": "",
            "status": "running",
            "phase": "discovering",
            "started_at": now,
            "updated_at": now,
            "finished_at": "",
            "total": 0,
            "processed": 0,
            "downloaded": 0,
            "already_cached": 0,
            "synced": 0,
            "failed": 0,
            "progress_percent": 0,
            "current_pin_id": "",
            "current_title": "",
            "message": "正在发现 Pinterest 图板内容",
            "errors": [],
            "_created_epoch": time.time(),
        }
        _RUNS[run_id] = run
        public_run = _public_run(run)
    thread = threading.Thread(
        target=_run_board_discovery_and_download,
        args=(run_id, clean_board_id, discover),
        name=f"pinterest-board-sync-{clean_board_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:
        with _RUNS_LOCK:
            _RUNS.pop(run_id, None)
        raise
    return {"ok": True, "started": True, "run": public_run}


def get_pinterest_board_download(run_id: Any) -> dict[str, Any] | None:
    clean_id = str(run_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", clean_id):
        return None
    with _RUNS_LOCK:
        run = _RUNS.get(clean_id)
        return _public_run(run) if run else None
