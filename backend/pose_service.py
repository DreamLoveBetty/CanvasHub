"""Pose Reference backend asset helpers."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from .app_config import BASE_DIR

ROOT = BASE_DIR
POSE_STATIC_DIR = Path(os.environ.get("POSE_STATIC_DIR") or (ROOT / "static" / "pose"))
MANNEQUIN_STATIC_DIR = Path(os.environ.get("POSE_MANNEQUIN_STATIC_DIR") or (POSE_STATIC_DIR / "mannequin"))
MANNEQUIN_DATA_DIR = Path(os.environ.get("POSE_MANNEQUIN_ASSET_DIR") or (ROOT / "data" / "pose-assets" / "mannequin"))


def _file_status(path: Path) -> dict:
    exists = path.exists()
    return {
        "path": str(path),
        "exists": exists,
        "size": path.stat().st_size if exists and path.is_file() else 0,
    }


def _blender_candidates() -> list[str]:
    candidates = []
    configured = str(os.environ.get("POSE_BLENDER_PATH") or "").strip()
    if configured:
        candidates.append(str(Path(configured).expanduser()) if configured.startswith("~") else configured)
    candidates.append("/Applications/Blender.app/Contents/MacOS/Blender")
    path_blender = shutil.which("blender")
    if path_blender:
        candidates.append(path_blender)
    seen = set()
    return [item for item in candidates if item and not (item in seen or seen.add(item))]


def _blender_app_info(candidate: str) -> dict | None:
    marker = "/Contents/MacOS/Blender"
    if marker not in candidate:
        return None
    app_root = Path(candidate.split(marker, 1)[0])
    executable = Path(candidate)
    info_path = app_root / "Contents" / "Info.plist"
    if not executable.exists() or not info_path.exists():
        return None
    version = ""
    try:
        with info_path.open("rb") as handle:
            info = plistlib.load(handle)
        version = str(info.get("CFBundleShortVersionString") or info.get("CFBundleVersion") or "")
    except Exception:
        version = ""
    return {
        "path": candidate,
        "exists": True,
        "ok": True,
        "version": f"Blender {version}" if version else "Blender.app",
        "error": "",
        "detection": "app_bundle",
    }


def _blender_status() -> dict:
    checked = []
    for candidate in _blender_candidates():
        path = Path(candidate)
        exists = path.exists() or bool(shutil.which(candidate))
        item = {
            "path": candidate,
            "exists": exists,
            "ok": False,
            "version": "",
            "error": "",
        }
        checked.append(item)
        if not exists:
            continue
        app_info = _blender_app_info(candidate)
        if app_info:
            item.update(app_info)
            return {
                "available": True,
                "path": candidate,
                "version": item["version"],
                "checked": checked,
                "env": {"POSE_BLENDER_PATH": str(os.environ.get("POSE_BLENDER_PATH") or "")},
            }
        try:
            result = subprocess.run(
                [candidate, "--version"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=12,
                check=False,
            )
        except Exception as exc:
            item["error"] = str(exc)
            continue
        output = (result.stdout or result.stderr or "").strip()
        item.update({
            "ok": result.returncode == 0,
            "version": output.splitlines()[0] if output else "",
            "error": "" if result.returncode == 0 else (output or f"exit {result.returncode}"),
        })
        if item["ok"]:
            return {
                "available": True,
                "path": candidate,
                "version": item["version"],
                "checked": checked,
                "env": {"POSE_BLENDER_PATH": str(os.environ.get("POSE_BLENDER_PATH") or "")},
            }
    return {
        "available": False,
        "path": "",
        "version": "",
        "checked": checked,
        "env": {"POSE_BLENDER_PATH": str(os.environ.get("POSE_BLENDER_PATH") or "")},
        "nextSteps": [
            "安装 Blender.app，或设置 POSE_BLENDER_PATH=/Applications/Blender.app/Contents/MacOS/Blender。",
            "Blender 只用于离线 Mixamo FBX -> GLB 转换；未安装时姿态参考仍可使用程序化低模人偶。"
        ],
    }


def _mannequin_assets_status() -> dict:
    expected = {
        "xbot": MANNEQUIN_STATIC_DIR / "xbot.glb",
        "ybot": MANNEQUIN_STATIC_DIR / "ybot.glb",
    }
    static_files = {name: _file_status(path) for name, path in expected.items()}
    data_files = {
        "xbot": _file_status(MANNEQUIN_DATA_DIR / "xbot.glb"),
        "ybot": _file_status(MANNEQUIN_DATA_DIR / "ybot.glb"),
    }
    runtime_keys = [
        key
        for key in sorted(static_files)
        if static_files.get(key, {}).get("exists")
    ]
    local_keys = [
        key
        for key in sorted(data_files)
        if data_files.get(key, {}).get("exists")
    ]
    return {
        "available": bool(runtime_keys),
        "mode": "glb" if runtime_keys else "procedural_fallback",
        "staticDir": str(MANNEQUIN_STATIC_DIR),
        "dataDir": str(MANNEQUIN_DATA_DIR),
        "files": static_files,
        "localFiles": data_files,
        "availableKeys": runtime_keys,
        "localAvailable": bool(local_keys),
        "localAvailableKeys": local_keys,
        "missing": [key for key in expected if key not in runtime_keys],
        "fallback": {
            "available": True,
            "mode": "procedural_mannequin",
            "message": "未放置 GLB 时，前端使用程序化低模代理人偶。"
        },
        "nextSteps": [] if runtime_keys else [
            f"将本地下载后的 xbot.glb / ybot.glb 放到 {MANNEQUIN_STATIC_DIR}；下载来源见 static/pose/mannequin/README.md。",
            "仅 data/pose-assets/mannequin 中有 GLB 不会让前端直接加载；运行时加载目录是 static/pose/mannequin。"
        ],
    }


def pose_assets_status() -> dict:
    blender = _blender_status()
    mannequin_assets = _mannequin_assets_status()
    return {
        "ok": True,
        "directorStage": {
            "ok": True,
            "available": True,
            "assetMode": mannequin_assets.get("mode") or "procedural_fallback",
            "blender": blender,
            "mannequinAssets": mannequin_assets,
            "message": (
                "姿态参考已就绪，使用 GLB 低模人偶。"
                if mannequin_assets.get("available")
                else "姿态参考已就绪，当前使用程序化低模人偶；可稍后用 Blender CLI 转换 Mixamo FBX。"
            ),
        },
    }
