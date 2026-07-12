"""Download and activate optional desktop runtime components."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import threading
import time
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from .app_config import APP_DATA_DIR, load_app_settings
from .version import APP_VERSION


COMPONENT_NAME = "upscale"
COMPONENT_ROOT = Path(
    os.environ.get("CANVASHUB_UPSCALE_COMPONENT_DIR")
    or APP_DATA_DIR / "components" / COMPONENT_NAME
).expanduser()
DOWNLOAD_ROOT = APP_DATA_DIR / "downloads"
CURRENT_DIR = COMPONENT_ROOT / "current"
STATE_LOCK = threading.RLock()
STATE: dict[str, Any] = {
    "status": "idle",
    "progress": 0.0,
    "bytes_received": 0,
    "total_bytes": 0,
    "message": "",
    "error": "",
    "started_at": 0,
    "finished_at": 0,
}
USER_AGENT = f"CanvasHub-Desktop/{APP_VERSION}"


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    system_key = {"darwin": "darwin", "windows": "windows", "linux": "linux"}.get(system, system)
    arch_key = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
    return f"{system_key}-{arch_key}"


def _manifest_source() -> str:
    settings = load_app_settings()
    section = settings.get("desktop_components") if isinstance(settings.get("desktop_components"), dict) else {}
    return str(
        os.environ.get("CANVASHUB_UPSCALE_MANIFEST_URL")
        or section.get("upscale_manifest_url")
        or ""
    ).strip()


def _read_json_source(source: str) -> dict[str, Any]:
    if not source:
        raise RuntimeError("高清放大组件下载源尚未配置")
    if source.startswith(("http://", "https://")):
        request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    else:
        local_path = Path(source.removeprefix("file://")).expanduser()
        payload = local_path.read_bytes()
    data = json.loads(payload.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("高清放大组件清单格式错误")
    return data


def _resolve_manifest_entry(manifest: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if int(manifest.get("schema_version") or 0) != 1:
        raise RuntimeError("不支持的高清放大组件清单版本")
    if str(manifest.get("component") or "") != COMPONENT_NAME:
        raise RuntimeError("高清放大组件清单名称不匹配")
    platform_key = _platform_key()
    platforms = manifest.get("platforms") if isinstance(manifest.get("platforms"), dict) else {}
    entry = platforms.get(platform_key)
    if not isinstance(entry, dict):
        raise RuntimeError(f"高清放大组件暂不支持当前平台：{platform_key}")
    required = ("url", "sha256", "worker", "model_dir")
    if any(not str(entry.get(key) or "").strip() for key in required):
        raise RuntimeError("高清放大组件清单缺少必要字段")
    version = str(manifest.get("version") or "").strip()
    if not version:
        raise RuntimeError("高清放大组件清单缺少版本号")
    return version, entry


def _installed_metadata() -> dict[str, Any]:
    path = CURRENT_DIR / "installed.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def resolve_upscale_worker() -> Path | None:
    override = str(os.environ.get("CANVASHUB_UPSCALE_WORKER") or "").strip()
    if override:
        path = Path(override).expanduser()
        return path if path.is_file() else None
    metadata = _installed_metadata()
    relative = str(metadata.get("worker") or "").strip()
    if not relative:
        return None
    path = (CURRENT_DIR / relative).resolve()
    try:
        path.relative_to(CURRENT_DIR.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def get_upscale_component_status() -> dict[str, Any]:
    metadata = _installed_metadata()
    worker = resolve_upscale_worker()
    with STATE_LOCK:
        transient = dict(STATE)
    return {
        "component": COMPONENT_NAME,
        "platform": _platform_key(),
        "configured": bool(_manifest_source()),
        "installed": bool(metadata and worker),
        "version": str(metadata.get("version") or ""),
        "worker_path": str(worker or ""),
        "component_dir": str(CURRENT_DIR),
        **transient,
    }


def _update_state(**patch: Any) -> None:
    with STATE_LOCK:
        STATE.update(patch)


def _download_file(url: str, destination: Path, expected_size: int = 0) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not url.startswith(("http://", "https://", "file://")):
        source = Path(url).expanduser()
        total = expected_size or source.stat().st_size
        received = 0
        with source.open("rb") as input_file, destination.open("wb") as output:
            while True:
                chunk = input_file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                _update_state(
                    status="downloading",
                    bytes_received=received,
                    total_bytes=total,
                    progress=(received / total) if total else 0.0,
                    message="正在下载高清放大组件...",
                )
        return
    existing = destination.stat().st_size if destination.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        partial = int(getattr(response, "status", None) or 200) == 206 and existing > 0
        mode = "ab" if partial else "wb"
        received = existing if partial else 0
        content_length = int(response.headers.get("Content-Length") or 0)
        total = expected_size or (received + content_length)
        with destination.open(mode) as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                _update_state(
                    status="downloading",
                    bytes_received=received,
                    total_bytes=total,
                    progress=(received / total) if total else 0.0,
                    message="正在下载高清放大组件...",
                )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("高清放大组件压缩包包含非法路径")
        bundle.extractall(destination)


def _activate_component(version: str, entry: dict[str, Any], staging_dir: Path) -> None:
    worker_relative = Path(str(entry["worker"]))
    model_relative = Path(str(entry["model_dir"]))
    worker = staging_dir / worker_relative
    model_dir = staging_dir / model_relative
    if not worker.is_file() or not model_dir.is_dir() or not any(model_dir.glob("*.pth")):
        raise RuntimeError("高清放大组件缺少 Worker 或模型权重")
    if os.name != "nt":
        worker.chmod(worker.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    metadata = {
        "component": COMPONENT_NAME,
        "version": version,
        "platform": _platform_key(),
        "worker": worker_relative.as_posix(),
        "model_dir": model_relative.as_posix(),
        "installed_at": int(time.time()),
    }
    (staging_dir / "installed.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    previous = COMPONENT_ROOT / ".previous"
    shutil.rmtree(previous, ignore_errors=True)
    if CURRENT_DIR.exists():
        CURRENT_DIR.rename(previous)
    try:
        staging_dir.rename(CURRENT_DIR)
    except Exception:
        if previous.exists() and not CURRENT_DIR.exists():
            previous.rename(CURRENT_DIR)
        raise
    shutil.rmtree(previous, ignore_errors=True)


def _install_worker(force: bool) -> None:
    started_at = int(time.time())
    _update_state(
        status="checking",
        progress=0.0,
        bytes_received=0,
        total_bytes=0,
        message="正在检查高清放大组件...",
        error="",
        started_at=started_at,
        finished_at=0,
    )
    staging_dir: Path | None = None
    try:
        manifest_source = _manifest_source()
        manifest = _read_json_source(manifest_source)
        version, entry = _resolve_manifest_entry(manifest)
        entry = dict(entry)
        archive_url = str(entry["url"])
        if not archive_url.startswith(("http://", "https://", "file://")):
            if manifest_source.startswith(("http://", "https://")):
                archive_url = urllib.parse.urljoin(manifest_source, archive_url)
            else:
                archive_url = str((Path(manifest_source).expanduser().parent / archive_url).resolve())
        entry["url"] = archive_url
        installed = _installed_metadata()
        if not force and installed.get("version") == version and resolve_upscale_worker():
            _update_state(status="ready", progress=1.0, message="高清放大组件已安装", finished_at=int(time.time()))
            return

        COMPONENT_ROOT.mkdir(parents=True, exist_ok=True)
        DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        archive = DOWNLOAD_ROOT / f"upscale-{version}-{_platform_key()}.zip.part"
        _download_file(str(entry["url"]), archive, int(entry.get("size") or 0))
        _update_state(status="verifying", progress=1.0, message="正在校验高清放大组件...")
        actual_sha = _sha256(archive)
        if actual_sha.lower() != str(entry["sha256"]).strip().lower():
            archive.unlink(missing_ok=True)
            raise RuntimeError("高清放大组件 SHA256 校验失败")

        staging_dir = COMPONENT_ROOT / f".staging-{version}-{int(time.time())}"
        shutil.rmtree(staging_dir, ignore_errors=True)
        _update_state(status="installing", progress=1.0, message="正在安装高清放大组件...")
        _safe_extract_zip(archive, staging_dir)
        _activate_component(version, entry, staging_dir)
        staging_dir = None
        archive.unlink(missing_ok=True)
        _update_state(status="ready", progress=1.0, message="高清放大组件安装完成", finished_at=int(time.time()))
    except Exception as exc:
        if staging_dir:
            shutil.rmtree(staging_dir, ignore_errors=True)
        _update_state(status="failed", error=str(exc), message="高清放大组件安装失败", finished_at=int(time.time()))


def start_upscale_component_install(force: bool = False) -> dict[str, Any]:
    with STATE_LOCK:
        if STATE.get("status") in {"checking", "downloading", "verifying", "installing"}:
            return get_upscale_component_status()
        STATE["status"] = "queued"
        STATE["error"] = ""
    thread = threading.Thread(target=_install_worker, args=(bool(force),), name="upscale-component-install", daemon=True)
    thread.start()
    return get_upscale_component_status()


def remove_upscale_component() -> dict[str, Any]:
    with STATE_LOCK:
        if STATE.get("status") in {"checking", "downloading", "verifying", "installing"}:
            raise RuntimeError("高清放大组件正在安装，暂时不能移除")
    shutil.rmtree(CURRENT_DIR, ignore_errors=True)
    _update_state(status="idle", progress=0.0, message="", error="", finished_at=int(time.time()))
    return get_upscale_component_status()
