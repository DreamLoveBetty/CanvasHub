#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backend storage for desktop layout-editor drafts."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .app_config import APP_DATA_DIR
from .storage_paths import IMAGE_ARCHIVE_DIR


DRAFT_ROOT = IMAGE_ARCHIVE_DIR / "_layout_drafts"
DB_PATH = APP_DATA_DIR / "layout_drafts.db"
VALID_DRAFT_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def init_layout_draft_store() -> None:
    DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS layout_drafts (
                draft_id TEXT PRIMARY KEY,
                title TEXT,
                node_id TEXT,
                project_json_path TEXT,
                preview_file TEXT,
                export_file TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active'
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_layout_drafts_updated ON layout_drafts(updated_at)")
        conn.commit()


def _now() -> int:
    return int(time.time())


def _new_draft_id() -> str:
    return f"layout_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _validate_draft_id(draft_id: str) -> str:
    clean = str(draft_id or "").strip()
    if not VALID_DRAFT_ID.match(clean):
        raise ValueError("草稿 ID 非法")
    return clean


def draft_dir(draft_id: str) -> Path:
    clean = _validate_draft_id(draft_id)
    path = (DRAFT_ROOT / clean).resolve()
    root = DRAFT_ROOT.resolve()
    if path != root and root in path.parents:
        return path
    raise ValueError("草稿路径非法")


def assets_dir(draft_id: str) -> Path:
    path = draft_dir(draft_id) / "assets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_filename(name: str, fallback_ext: str = ".png") -> str:
    stem = Path(os.path.basename(str(name or ""))).stem
    suffix = Path(os.path.basename(str(name or ""))).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")[:48]
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        suffix = fallback_ext
    return f"{stem or 'asset'}{suffix}"


def _decode_data_uri(data: str) -> tuple[bytes, str, str]:
    if not data:
        raise ValueError("缺少图片数据")
    mime_type = "image/png"
    payload = data
    if "," in data:
        header, payload = data.split(",", 1)
        if ";base64" not in header:
            raise ValueError("仅支持 base64 data URI")
        if header.startswith("data:"):
            mime_type = header[5:].split(";", 1)[0] or mime_type
    raw = base64.b64decode(payload)
    extension = mimetypes.guess_extension(mime_type) or ".png"
    if extension == ".jpe":
        extension = ".jpg"
    if extension not in (".png", ".jpg", ".jpeg", ".webp"):
        extension = ".png"
    return raw, mime_type, extension


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _write_data_uri(path: Path, data_url: str) -> tuple[str, str]:
    raw, mime_type, extension = _decode_data_uri(data_url)
    if path.suffix.lower() != extension:
        path = path.with_suffix(extension)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, path)
    return str(path), mime_type


def _row_to_meta(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    draft_id = item["draft_id"]
    updated_at = item.get("updated_at") or _now()
    preview_url = f"/api/layout/drafts/{draft_id}/preview?v={updated_at}" if item.get("preview_file") else ""
    export_url = f"/api/layout/drafts/{draft_id}/export?v={updated_at}" if item.get("export_file") else preview_url
    return {
        "draft_id": draft_id,
        "title": item.get("title") or "排版工作区",
        "node_id": item.get("node_id") or "",
        "created_at": item.get("created_at") or updated_at,
        "updated_at": updated_at,
        "version": item.get("version") or 1,
        "status": item.get("status") or "active",
        "preview_url": preview_url,
        "export_url": export_url,
    }


def _get_row(draft_id: str) -> sqlite3.Row | None:
    clean = _validate_draft_id(draft_id)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM layout_drafts WHERE draft_id=?", (clean,)).fetchone()


def list_drafts(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    init_layout_draft_store()
    safe_limit = max(1, min(int(limit or 50), 100))
    safe_offset = max(0, int(offset or 0))
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM layout_drafts
            WHERE status != 'deleted'
            ORDER BY updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (safe_limit, safe_offset),
        ).fetchall()
    return [_row_to_meta(row) for row in rows]


def create_draft(title: str = "", node_id: str = "", project: Any | None = None,
                 preview_data_url: str = "", export_data_url: str = "") -> dict[str, Any]:
    init_layout_draft_store()
    draft_id = _new_draft_id()
    now = _now()
    folder = draft_dir(draft_id)
    folder.mkdir(parents=True, exist_ok=True)
    project_path = folder / "project.json"
    _atomic_write_json(project_path, project or {})

    preview_file = ""
    export_file = ""
    if preview_data_url:
        preview_file, _ = _write_data_uri(folder / "preview.png", preview_data_url)
    if export_data_url:
        export_file, _ = _write_data_uri(folder / "export.png", export_data_url)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO layout_drafts (
                draft_id, title, node_id, project_json_path, preview_file, export_file,
                created_at, updated_at, version, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                title or "排版工作区",
                node_id or "",
                str(project_path),
                preview_file,
                export_file,
                now,
                now,
                1,
                "active",
            ),
        )
        conn.commit()

    return load_draft(draft_id)


def update_draft(draft_id: str, title: str | None = None, node_id: str | None = None,
                 project: Any | None = None, preview_data_url: str = "",
                 export_data_url: str = "") -> dict[str, Any]:
    init_layout_draft_store()
    clean = _validate_draft_id(draft_id)
    row = _get_row(clean)
    if not row:
        raise FileNotFoundError("草稿不存在")

    folder = draft_dir(clean)
    folder.mkdir(parents=True, exist_ok=True)
    now = _now()
    values: dict[str, Any] = {"updated_at": now}

    if title is not None:
        values["title"] = title or "排版工作区"
    if node_id is not None:
        values["node_id"] = node_id or ""
    if project is not None:
        project_path = Path(row["project_json_path"] or folder / "project.json")
        _atomic_write_json(project_path, project)
        values["project_json_path"] = str(project_path)
    if preview_data_url:
        preview_file, _ = _write_data_uri(folder / "preview.png", preview_data_url)
        values["preview_file"] = preview_file
    if export_data_url:
        export_file, _ = _write_data_uri(folder / "export.png", export_data_url)
        values["export_file"] = export_file

    assignments = ", ".join(f"{key}=?" for key in values)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            f"UPDATE layout_drafts SET {assignments} WHERE draft_id=?",
            [*values.values(), clean],
        )
        conn.commit()

    return load_draft(clean)


def load_draft(draft_id: str) -> dict[str, Any]:
    init_layout_draft_store()
    row = _get_row(draft_id)
    if not row:
        raise FileNotFoundError("草稿不存在")

    project = {}
    project_path = row["project_json_path"]
    if project_path and Path(project_path).exists():
        with open(project_path, "r", encoding="utf-8") as f:
            project = json.load(f)

    meta = _row_to_meta(row)
    meta["project"] = project
    return meta


def save_asset(draft_id: str, filename: str, data_url: str) -> dict[str, Any]:
    init_layout_draft_store()
    clean = _validate_draft_id(draft_id)
    if not _get_row(clean):
        raise FileNotFoundError("草稿不存在")

    raw, mime_type, extension = _decode_data_uri(data_url)
    name = _safe_filename(filename, extension)
    target = assets_dir(clean) / name
    if target.exists():
        target = target.with_name(f"{target.stem}_{uuid.uuid4().hex[:6]}{target.suffix}")
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(raw)
    os.replace(tmp, target)

    update_draft(clean)
    return {
        "draft_id": clean,
        "filename": target.name,
        "mime_type": mime_type,
        "asset_url": f"/api/layout/drafts/{clean}/assets/{urllib_quote(target.name)}",
    }


def get_file(draft_id: str, kind: str, asset_name: str = "") -> Path:
    row = _get_row(draft_id)
    if not row:
        raise FileNotFoundError("草稿不存在")

    if kind == "preview":
        path = Path(row["preview_file"] or "")
    elif kind == "export":
        path = Path(row["export_file"] or row["preview_file"] or "")
    elif kind == "asset":
        name = os.path.basename(str(asset_name or ""))
        path = assets_dir(draft_id) / name
    else:
        raise FileNotFoundError("文件类型不存在")

    if not path or not path.exists() or not path.is_file():
        raise FileNotFoundError("文件不存在")
    return path


def urllib_quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
