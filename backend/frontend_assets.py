"""Select source or prebuilt web resources without changing runtime data paths."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath


def load_frontend_assets(project_root: Path) -> tuple[Path, Path, frozenset[str]]:
    """Default to sources; use built resources only when explicitly selected/packaged.

    Both layouts keep sibling frontend/ and static/ directories. No build tool is
    invoked at runtime, and a stray dist/ directory never changes source startup.
    """
    override = str(os.environ.get("CANVASHUB_FRONTEND_DIR") or "").strip()
    frontend = Path(override).expanduser() if override else project_root / "frontend"
    if not frontend.is_absolute():
        frontend = project_root / frontend
    frontend = frontend.resolve()
    manifest_path = frontend / "asset-manifest.json"
    if override:
        for page in ("desktop.html", "index.html"):
            if not (frontend / page).is_file():
                raise RuntimeError(f"CANVASHUB_FRONTEND_DIR is missing {page}: {frontend}")
    if not manifest_path.exists():
        return frontend, project_root / "static", frozenset()

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1:
            raise ValueError("unsupported manifest version")
        files = manifest["files"]
        immutable = manifest["immutable_paths"]
        if not isinstance(files, dict) or not isinstance(immutable, list):
            raise ValueError("invalid resource inventory")
        if not {"frontend/desktop.html", "frontend/index.html"}.issubset(files):
            raise ValueError("missing HTML entrypoints in manifest")
        for relative in files:
            parts = PurePosixPath(relative).parts
            if (not parts or parts[0] not in {"frontend", "static"} or ".." in parts
                    or "\\" in relative or PurePosixPath(relative).as_posix() != relative):
                raise ValueError("invalid resource path")
            file = frontend.joinpath(*parts[1:]) if parts[0] == "frontend" else frontend.parent.joinpath(*parts)
            expected_root = frontend if parts[0] == "frontend" else frontend.parent / "static"
            if not file.resolve().is_relative_to(expected_root.resolve()):
                raise ValueError("resource symlink escapes build directory")
            if not file.is_file():
                raise ValueError(f"missing resource: {relative}")
        for url in immutable:
            if not isinstance(url, str) or not url.startswith("/") or "frontend" + url not in files:
                raise ValueError("invalid immutable resource URL")
        static = frontend.parent / "static"
        if not static.is_dir():
            raise ValueError("missing sibling static resource directory")
        return frontend, static, frozenset(immutable)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeError(f"Incomplete frontend build at {frontend}: {error}") from error
