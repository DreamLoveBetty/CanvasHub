"""Locate the machine's activated Topaz Video model directory.

The detached video runtime keeps binaries and model weights in CanvasHub's
component directory, but Topaz' conventional FFmpeg filter also requires the
current machine license context.  We reference that context in place; it is
never copied into project data, returned by an API, or written to logs.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys


ENV_LICENSE_DIR = "CANVASHUB_TOPAZ_VIDEO_LICENSE_DIR"
MAC_APP_MODELS = Path("/Applications/Topaz Video.app/Contents/Resources/models")


def _usable(root: Path) -> bool:
    license_file = root / "license.lic"
    return (root.is_dir() and not root.is_symlink()
            and license_file.is_file() and not license_file.is_symlink()
            and license_file.stat().st_size > 0)


def resolve_license_dir(explicit: Path | str | None = None) -> Path | None:
    """Return a license-bearing model directory without reading its contents."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    configured = os.environ.get(ENV_LICENSE_DIR, "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    if sys.platform == "darwin":
        candidates.append(MAC_APP_MODELS)
    for candidate in candidates:
        try:
            root = candidate.resolve(strict=True)
            if _usable(root):
                return root
        except OSError:
            continue
    return None

