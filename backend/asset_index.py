#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lightweight image asset index for the desktop gallery."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
import urllib.parse
from pathlib import Path
from typing import Any

from PIL import Image

from .app_config import APP_DATA_DIR
from .database import DB_PATH as TASKS_DB_PATH
from .database import get_all_tasks
from .image_resolution import infer_resolution_label, normalize_resolution_label
from .storage_paths import IMAGE_ARCHIVE_DIR, archive_scan_roots
from .thumb_cache import thumb_url_for_media_url


DB_PATH = APP_DATA_DIR / "assets.db"
HISTORY_FILE = APP_DATA_DIR / "history.jsonl"
TAG_SPLIT_RE = re.compile(r"[,，;；\n]+")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
SIDECAR_PARAM_KEYS = {
    "image_file",
    "ratio",
    "aspect_ratio",
    "aspectRatio",
    "resolution",
    "requested_resolution",
    "actual_resolution",
    "actual_resolutions",
    "effective_resolution",
    "resolution_mismatch",
    "image_size",
    "size",
    "requested_size",
    "actual_size",
    "actual_width",
    "actual_height",
    "actual_megapixels",
    "quality",
    "moderation",
    "image_count",
    "main_model",
    "reasoning_effort",
    "prompt_mode",
    "revised_prompt_available",
    "revised_prompt",
    "generated_at",
    "model",
    "modelAlias",
    "sampler",
    "steps",
    "cfg",
    "seed",
}
IMAGE_INFO_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}

# ---------------------------------------------------------------------------
# 持久化文件元数据缓存（sidecar 解析结果 + PIL 尺寸），按 (mtime_ns, size) 指纹命中，
# 让重启后的冷构建不再逐文件读 sidecar / 解码图片。
# ---------------------------------------------------------------------------
_FILE_META_LOCK = threading.RLock()
_FILE_META_ROWS: dict[str, tuple[int, int, str]] | None = None  # path -> (mtime_ns, size, payload_json)
_FILE_META_PENDING: dict[str, tuple[int, int, str]] = {}
_FILE_META_SEEN: set[str] = set()  # 本轮构建触达过的路径，flush 时据此清理消失文件的行

# ---------------------------------------------------------------------------
# 成品索引缓存：构建一次（含血缘装饰），后续请求只做过滤/排序/切片。
# 失效条件：归档目录/任务库指纹变化、显式失效钩子（资产元数据变更）、TTL 兜底。
# ---------------------------------------------------------------------------
_INDEX_LOCK = threading.RLock()
_INDEX_CACHE: dict[str, Any] | None = None  # {"fingerprint", "built_at", "variants": {"all"|"missing": {...}}}
_INDEX_TTL_SECONDS = 60

# 图库列表瘦身投影保留的字段。原则：网格卡片渲染、客户端搜索、同步 dragstart 载荷、
# 候选集快照、套用参数等**同步**流程所需字段必须保留（prompt / params / 基础元信息）；
# 只砍真正的大头：revised_prompt 三份拷贝 + 血缘装饰快照数组（预览打开时走 detail 接口补全）。
CARD_PROJECTION_FIELDS = (
    "id", "asset_id", "taskId", "task_id", "file",
    "archiveRelPath", "archive_rel_path",
    "imageUrl", "imagePath", "thumbUrl", "title",
    "prompt", "note", "stale",
    "mainModel", "reasoningEffort",
    "requestedResolution", "requested_resolution",
    "actualResolution", "actual_resolution", "resolution",
    "resolutionMismatch", "resolution_mismatch",
    "type", "provider", "providerLabel", "sourceKind", "assetSource",
    "hasTaskRecord", "has_task_record", "missingArchive", "missing_archive",
    "status", "createdAt", "updatedAt", "index", "total",
    "favorite", "hidden", "tags", "rating",
    "derivedCount", "relatedCount",
    "referenceAssetIds", "reference_asset_ids", "sourceTaskIds", "source_task_ids",
    "width", "height", "imageWidth", "imageHeight",
    "aspectRatio", "aspect_ratio", "orientation", "dimensions",
    "fileSizeBytes", "file_size_bytes", "fileSizeLabel", "file_size_label",
    "format", "megapixels",
)

# 瘦身版 params 中剔除的重字段（列表场景用不到，详情接口仍返回完整版）
CARD_PARAMS_DROP_KEYS = {"revised_prompt"}

# 瘦身版 referenceAssets 保留 id 引用 + 无 id 引用的识别字段（imageUrl/missing/deleted），
# 保证前端 normalizeLineageAsset 的过滤条件下"源 N"角标计数与全量模式一致
CARD_REFERENCE_KEYS = ("id", "asset_id", "taskId", "task_id", "index", "imageUrl", "image_url", "missing", "deleted")


def invalidate_asset_index_cache() -> None:
    """资产可见状态发生变化（收藏/隐藏/标签/删除恢复等）后调用，强制下次重建索引。"""
    global _INDEX_CACHE
    with _INDEX_LOCK:
        _INDEX_CACHE = None


def _stat_fingerprint(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return (int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (0, 0)


def _index_fingerprint() -> tuple:
    """轻量指纹：任务库 + 旧历史文件 + 各归档根目录及其一级子目录的 mtime。
    捕捉新增/删除/任务完成；就地编辑等深层变化由 TTL 兜底。"""
    parts: list[Any] = [
        _stat_fingerprint(Path(TASKS_DB_PATH)),
        _stat_fingerprint(HISTORY_FILE),
    ]
    for root_key, root in archive_scan_roots():
        parts.append((root_key, _stat_fingerprint(root)))
        try:
            children = sorted(
                (child.name, int(child.stat().st_mtime_ns))
                for child in root.iterdir()
                if child.is_dir()
            )
        except OSError:
            children = []
        parts.append(tuple(children))
    return tuple(parts)


def init_asset_store() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_meta (
                asset_id TEXT PRIMARY KEY,
                favorite INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0,
                tags_json TEXT DEFAULT '[]',
                rating INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_meta_favorite ON asset_meta(favorite)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_meta_hidden ON asset_meta(hidden)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_sets (
                set_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                tags_json TEXT DEFAULT '[]',
                asset_ids_json TEXT DEFAULT '[]',
                asset_snapshots_json TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active',
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_sets_status ON asset_sets(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_sets_updated ON asset_sets(updated_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS asset_delete_journal (
                batch_id TEXT PRIMARY KEY,
                payload_json TEXT DEFAULT '{}',
                created_at INTEGER,
                restored INTEGER DEFAULT 0,
                restored_at INTEGER DEFAULT 0
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_delete_journal_created ON asset_delete_journal(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_asset_delete_journal_restored ON asset_delete_journal(restored)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_meta_cache (
                path TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                payload_json TEXT DEFAULT '{}',
                updated_at INTEGER
            )
            """
        )
        conn.commit()


def _file_meta_rows() -> dict[str, tuple[int, int, str]]:
    """一次性读入 file_meta_cache 全表（进程内驻留），供构建循环做 O(1) 命中。"""
    global _FILE_META_ROWS
    with _FILE_META_LOCK:
        if _FILE_META_ROWS is None:
            rows: dict[str, tuple[int, int, str]] = {}
            try:
                with sqlite3.connect(DB_PATH) as conn:
                    for path, mtime_ns, size_bytes, payload_json in conn.execute(
                        "SELECT path, mtime_ns, size_bytes, payload_json FROM file_meta_cache"
                    ):
                        rows[str(path)] = (int(mtime_ns), int(size_bytes), str(payload_json or "{}"))
            except Exception:
                rows = {}
            _FILE_META_ROWS = rows
        return _FILE_META_ROWS


def _file_meta_get(path: Path, fingerprint: tuple[int, int]) -> dict[str, Any] | None:
    key = str(path)
    row = _file_meta_rows().get(key)
    if not row or (row[0], row[1]) != fingerprint:
        return None
    _FILE_META_SEEN.add(key)
    try:
        payload = json.loads(row[2])
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _file_meta_put(path: Path, fingerprint: tuple[int, int], payload: dict[str, Any]) -> None:
    try:
        payload_json = json.dumps(payload, ensure_ascii=False)
    except Exception:
        return
    key = str(path)
    with _FILE_META_LOCK:
        _file_meta_rows()[key] = (fingerprint[0], fingerprint[1], payload_json)
        _FILE_META_PENDING[key] = (fingerprint[0], fingerprint[1], payload_json)
        _FILE_META_SEEN.add(key)


def _flush_file_meta_cache() -> None:
    """构建结束后把新解析的文件元数据批量落库，并清理本轮未触达（已消失）的行。"""
    with _FILE_META_LOCK:
        pending = list(_FILE_META_PENDING.items())
        _FILE_META_PENDING.clear()
        seen = set(_FILE_META_SEEN)
        _FILE_META_SEEN.clear()
        rows = _file_meta_rows()
        # 只有本轮确实触达过文件时才做清理，避免异常空构建误删全表
        stale = [key for key in rows if key not in seen] if seen else []
        for key in stale:
            rows.pop(key, None)
    if not pending and not stale:
        return
    now = _now()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            if pending:
                conn.executemany(
                    """
                    INSERT INTO file_meta_cache (path, mtime_ns, size_bytes, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        mtime_ns=excluded.mtime_ns,
                        size_bytes=excluded.size_bytes,
                        payload_json=excluded.payload_json,
                        updated_at=excluded.updated_at
                    """,
                    [(key, row[0], row[1], row[2], now) for key, row in pending],
                )
            if stale:
                conn.executemany(
                    "DELETE FROM file_meta_cache WHERE path = ?",
                    [(key,) for key in stale],
                )
            conn.commit()
    except Exception as exc:
        print(f"⚠️ file_meta_cache 落库失败（不影响本次响应）：{exc}")


def _now() -> int:
    return int(time.time())


def _decode_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return _decode_tags(parsed)
        except Exception:
            pass
        parts = TAG_SPLIT_RE.split(raw)
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        return []

    tags: list[str] = []
    seen: set[str] = set()
    for item in parts:
        tag = str(item or "").strip().lstrip("#")[:24]
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)
    return tags[:12]


def _decode_json_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _coerce_sidecar_value(key: str, value: str) -> Any:
    clean = str(value or "").strip()
    if key in {"resolution_mismatch"}:
        return clean.lower() in {"1", "true", "yes", "y", "是"}
    if key in {"image_count", "generated_at", "steps", "seed", "actual_width", "actual_height"}:
        try:
            return int(clean)
        except Exception:
            return clean
    if key in {"cfg", "actual_megapixels"}:
        try:
            return float(clean)
        except Exception:
            return clean
    return clean


def _merge_params(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if value in (None, ""):
            continue
        merged[key] = value
    return merged


def _format_file_size(size: int) -> str:
    try:
        value = float(size)
    except Exception:
        return ""
    units = ["B", "KB", "MB", "GB"]
    unit = units[0]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            break
        value /= 1024
    if unit == "B":
        return f"{int(value)} B"
    return f"{value:.1f} {unit}"


def _ratio_label(width: int, height: int) -> str:
    if not width or not height:
        return ""
    ratio = width / height
    known = [
        ("1:1", 1),
        ("16:9", 16 / 9),
        ("9:16", 9 / 16),
        ("4:3", 4 / 3),
        ("3:4", 3 / 4),
        ("3:2", 3 / 2),
        ("2:3", 2 / 3),
        ("4:5", 4 / 5),
        ("5:4", 5 / 4),
        ("21:9", 21 / 9),
        ("9:21", 9 / 21),
    ]
    label, diff = min(known, key=lambda item: abs(item[1] - ratio))
    if diff <= 0.035:
        return label
    from math import gcd
    divisor = gcd(width, height) or 1
    return f"{width // divisor}:{height // divisor}"


def _resolution_label(width: int, height: int) -> str:
    return infer_resolution_label(width, height)


def _image_file_meta(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except Exception:
        return {}
    cache_key = str(path)
    fingerprint = (int(stat.st_mtime), int(stat.st_size))
    cached = IMAGE_INFO_CACHE.get(cache_key)
    if cached and cached[0] == fingerprint:
        return dict(cached[1])

    # 进程内未命中时先查持久化缓存，重启后的冷构建可跳过 PIL 解码
    ns_fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
    persisted = _file_meta_get(path, ns_fingerprint)
    if isinstance(persisted, dict) and persisted.get("kind") == "image_meta":
        stored = persisted.get("meta")
        if isinstance(stored, dict) and stored:
            IMAGE_INFO_CACHE[cache_key] = (fingerprint, dict(stored))
            return dict(stored)

    meta: dict[str, Any] = {
        "fileSizeBytes": int(stat.st_size),
        "file_size_bytes": int(stat.st_size),
        "fileSizeLabel": _format_file_size(int(stat.st_size)),
        "file_size_label": _format_file_size(int(stat.st_size)),
        "format": path.suffix.lower().lstrip(".").upper(),
    }
    try:
        with Image.open(path) as img:
            width, height = img.size
            img_format = (img.format or meta["format"]).upper()
        ratio = _ratio_label(int(width), int(height))
        resolution = _resolution_label(int(width), int(height))
        meta.update({
            "width": int(width),
            "height": int(height),
            "imageWidth": int(width),
            "imageHeight": int(height),
            "dimensions": f"{int(width)} × {int(height)}",
            "aspectRatio": ratio,
            "aspect_ratio": ratio,
            "orientation": "square" if abs(width - height) / max(width, height) <= 0.02 else ("landscape" if width > height else "portrait"),
            "megapixels": round((int(width) * int(height)) / 1_000_000, 2),
            "format": img_format,
        })
        if resolution:
            meta["resolution"] = resolution
    except Exception:
        pass

    IMAGE_INFO_CACHE[cache_key] = (fingerprint, dict(meta))
    # 只有 PIL 成功解析出尺寸才持久化，避免瞬时打开失败被永久缓存成"无尺寸"
    if "width" in meta:
        _file_meta_put(path, ns_fingerprint, {"kind": "image_meta", "meta": meta})
    return meta


def _load_meta() -> dict[str, dict[str, Any]]:
    init_asset_store()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM asset_meta").fetchall()
    meta: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["favorite"] = bool(item.get("favorite"))
        item["hidden"] = bool(item.get("hidden"))
        item["tags"] = _decode_tags(item.get("tags_json"))
        meta[item["asset_id"]] = item
    return meta


def _asset_id(task_id: str, file_name: str, index: int, image_url: str = "") -> str:
    source = f"{task_id}|{index}|{file_name}|{image_url}"
    digest = hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()[:20]
    return f"asset_{digest}"


def _archive_asset_id(rel_path: str) -> str:
    digest = hashlib.sha1(f"archive|{rel_path}".encode("utf-8", errors="ignore")).hexdigest()[:20]
    return f"asset_archive_{digest}"


def _provider_group(item: dict[str, Any]) -> str:
    raw = str(item.get("type") or "").lower()
    if raw.startswith("gpt") or "gpt" in raw:
        return "gpt"
    if raw.startswith("comfy") or "comfy" in raw:
        return "comfy"
    if "layout" in raw:
        return "layout"
    return "google"


def _provider_label(provider: str) -> str:
    return {
        "gpt": "GPT",
        "google": "Google",
        "comfy": "Comfy",
        "layout": "排版",
    }.get(provider, provider or "资产")


def _result_files(item: dict[str, Any]) -> list[str]:
    files = item.get("result_files") or item.get("output_files") or []
    if isinstance(files, str):
        try:
            parsed = json.loads(files)
            files = parsed if isinstance(parsed, list) else []
        except Exception:
            files = []
    if not files:
        primary = item.get("result_file") or item.get("output_file") or ""
        files = [primary] if primary else []
    return [str(file).strip() for file in files if str(file or "").strip()]


def _image_url(provider: str, file_name: str) -> str:
    if not file_name:
        return ""
    if provider == "gpt":
        return f"/gpt_outputs/{file_name}"
    return f"/image/{file_name}"


# 低于该边长的 sidecar 不做 420px 缩略图源：400px 的 gpt sidecar 通过，旧版 300px google sidecar 回退原图
_SIDECAR_THUMB_MIN_SIDE = 360
# 原图 mtime 比 sidecar 晚超过该秒数视为"被就地编辑过"，放弃 sidecar；容差覆盖归档搬运的写入延迟
_SIDECAR_FRESHNESS_TOLERANCE = 60


def _sidecar_thumb_source(provider: str, file_name: str, original_path: Path | None = None) -> str:
    """Return the pre-generated small thumbnail URL for this file if one is usable."""
    name = Path(str(file_name or "")).name
    if not name:
        return ""
    if provider == "gpt":
        candidate = APP_DATA_DIR / "gpt_outputs" / f"{Path(name).stem}_thumb.png"
        default_original = APP_DATA_DIR / "gpt_outputs" / name
        url = f"/gpt_outputs/{candidate.name}"
    else:
        candidate = APP_DATA_DIR / "google_outputs" / f"thumb_{name}"
        default_original = APP_DATA_DIR / "google_outputs" / name
        url = f"/google_outputs/{candidate.name}"
    try:
        candidate_stat = candidate.stat()
    except OSError:
        return ""
    # 原图被就地编辑（明显比 sidecar 新）时放弃 sidecar，避免缩略图永远停留在生成时的内容
    original = original_path if original_path is not None else default_original
    try:
        if original.is_file() and original.stat().st_mtime > candidate_stat.st_mtime + _SIDECAR_FRESHNESS_TOLERANCE:
            return ""
    except OSError:
        pass
    # 尺寸门槛：过小的旧版 sidecar 不足以喂 420px 请求（_image_file_meta 只读文件头且带缓存）
    meta = _image_file_meta(candidate)
    max_side = max(int(meta.get("width") or 0), int(meta.get("height") or 0))
    if max_side < _SIDECAR_THUMB_MIN_SIDE:
        return ""
    return url


def _thumb_url(provider: str, file_name: str, image_url: str, original_path: Path | None = None) -> str:
    # 优先用生成时写好的 400px sidecar 做 WebP 转码源，冷生成从全尺寸解码降到小图解码
    sidecar = _sidecar_thumb_source(provider, file_name, original_path)
    return thumb_url_for_media_url(sidecar or image_url)


def _archive_image_files() -> list[tuple[Path, str, str]]:
    files: list[tuple[Path, str, str]] = []
    for root_key, root in archive_scan_roots():
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                rel_path = path.relative_to(root).as_posix()
            except Exception:
                continue
            files.append((path, root_key, rel_path))
    files.sort(key=lambda item: (int(item[0].stat().st_mtime), item[0].as_posix()), reverse=True)
    return files


def _archive_public_rel_path(root_key: str, rel_path: str) -> str:
    clean = str(rel_path or "").strip().lstrip("/\\")
    if root_key and root_key != "main":
        return f"{root_key}/{clean}"
    return clean


def _archive_image_url(root_key: str, rel_path: str) -> str:
    return f"/archive_image/{urllib.parse.quote(_archive_public_rel_path(root_key, rel_path), safe='/')}"


def _infer_archive_provider(path: Path, template: dict[str, Any] | None = None) -> str:
    if template and template.get("provider"):
        return str(template.get("provider") or "google")
    rel_parts: set[str] = set()
    for _, root in archive_scan_roots():
        try:
            rel_parts = {part.lower() for part in path.relative_to(root).parts[:-1]}
            break
        except Exception:
            continue
    name = path.name.lower()
    if "_layout_drafts" in rel_parts or name.startswith(("layout_", "export")):
        return "layout"
    if name.startswith(("gpt_", "gpt-edit", "gpt_edit", "gpt-image")):
        return "gpt"
    return "google"


def _read_archive_sidecar(path: Path) -> tuple[str, dict[str, Any]]:
    """带持久化缓存的 sidecar 读取：指纹命中时跳过文件读取与正则解析。"""
    txt_path = path.with_suffix(".txt")
    try:
        stat = txt_path.stat()
    except OSError:
        return "", {}
    fingerprint = (int(stat.st_mtime_ns), int(stat.st_size))
    cached = _file_meta_get(txt_path, fingerprint)
    if isinstance(cached, dict) and cached.get("kind") == "sidecar":
        params = cached.get("params")
        return str(cached.get("prompt") or ""), dict(params) if isinstance(params, dict) else {}
    result = _read_archive_sidecar_uncached(path)
    if result is None:
        # 瞬时读取失败（如 iCloud 未就绪 / fd 耗尽）：不落缓存，下次构建重试
        return "", {}
    prompt, params = result
    _file_meta_put(txt_path, fingerprint, {"kind": "sidecar", "prompt": prompt, "params": params})
    return prompt, params


def _read_archive_sidecar_uncached(path: Path) -> tuple[str, dict[str, Any]] | None:
    """返回 (prompt, params)；文件存在但读取失败时返回 None（调用方不缓存）。"""
    txt_path = path.with_suffix(".txt")
    if not txt_path.exists():
        return "", {}
    try:
        text = txt_path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not text:
        return "", {}

    params: dict[str, Any] = {}
    prompt = text
    if "[user_prompt]" in text:
        header, prompt_part = text.split("[user_prompt]", 1)
        prompt = re.split(r"\n\[[a-zA-Z0-9_ -]+\]\s*\n?", prompt_part, maxsplit=1)[0].strip()
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key in SIDECAR_PARAM_KEYS and value:
                params[key] = _coerce_sidecar_value(key, value)
        revised_match = re.search(
            r"\[revised_prompt\]\s*(.*?)(?=\n\[[a-zA-Z0-9_ -]+\]\s*|\Z)",
            text,
            re.S,
        )
        if revised_match:
            params["revised_prompt"] = revised_match.group(1).strip()[:20000]
    else:
        lines = text.splitlines()
        parsed_until = 0
        for index, line in enumerate(lines[:24]):
            clean = line.strip()
            if not clean:
                parsed_until = index + 1
                if params:
                    break
                continue
            if ":" not in clean:
                break
            key, value = clean.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key not in SIDECAR_PARAM_KEYS:
                break
            if value:
                params[key] = _coerce_sidecar_value(key, value)
            parsed_until = index + 1
        if params and parsed_until < len(lines):
            prompt = "\n".join(lines[parsed_until:]).strip() or text
    return prompt[:20000], params


def _lineage_from_params(params: dict[str, Any]) -> dict[str, Any]:
    raw = params.get("lineage") if isinstance(params, dict) and isinstance(params.get("lineage"), dict) else {}
    refs_raw = raw.get("reference_assets") or raw.get("referenceAssets") or []
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(refs_raw, list):
        for index, ref in enumerate(refs_raw[:16]):
            if not isinstance(ref, dict):
                continue
            asset_id = str(ref.get("asset_id") or ref.get("assetId") or ref.get("id") or "").strip()
            task_id = str(ref.get("task_id") or ref.get("taskId") or "").strip()
            image_url = str(ref.get("image_url") or ref.get("imageUrl") or ref.get("imagePath") or ref.get("url") or "").strip()
            source_node_id = str(ref.get("source_node_id") or ref.get("sourceNodeId") or "").strip()
            if image_url.startswith(("data:", "blob:")):
                image_url = ""
            if not asset_id and not task_id and not image_url and not source_node_id:
                continue
            key = asset_id or (f"{task_id}:{image_url}" if task_id or image_url else "") or source_node_id
            if key in seen:
                continue
            seen.add(key)
            refs.append({
                "asset_id": asset_id,
                "id": asset_id,
                "task_id": task_id,
                "taskId": task_id,
                "image_url": image_url,
                "imageUrl": image_url,
                "title": str(ref.get("title") or ref.get("name") or ref.get("file") or f"参考图 {index + 1}")[:160],
                "prompt": str(ref.get("prompt") or "")[:500],
                "file": str(ref.get("file") or "")[:180],
                "source": str(ref.get("source") or "")[:48],
                "source_node_id": source_node_id,
                "sourceNodeId": source_node_id,
                "index": int(ref.get("index") if str(ref.get("index", "")).isdigit() else index),
            })
    asset_ids = []
    task_ids = []
    for ref in refs:
        if ref.get("asset_id") and ref["asset_id"] not in asset_ids:
            asset_ids.append(ref["asset_id"])
        if ref.get("task_id") and ref["task_id"] not in task_ids:
            task_ids.append(ref["task_id"])
    return {
        "reference_assets": refs,
        "referenceAssets": refs,
        "reference_asset_ids": asset_ids,
        "referenceAssetIds": asset_ids,
        "source_task_ids": task_ids,
        "sourceTaskIds": task_ids,
    }


def _asset_lineage_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": asset.get("id") or asset.get("asset_id") or "",
        "asset_id": asset.get("asset_id") or asset.get("id") or "",
        "taskId": asset.get("taskId") or "",
        "task_id": asset.get("taskId") or "",
        "file": asset.get("file") or "",
        "imageUrl": asset.get("imageUrl") or "",
        "image_url": asset.get("imageUrl") or "",
        "thumbUrl": asset.get("thumbUrl") or asset.get("imageUrl") or "",
        "title": asset.get("title") or "图片资产",
        "provider": asset.get("provider") or "",
        "providerLabel": asset.get("providerLabel") or "",
        "createdAt": asset.get("createdAt") or 0,
        "index": asset.get("index") or 0,
        "total": asset.get("total") or 1,
    }


def _decorate_lineage(assets: list[dict[str, Any]]) -> None:
    by_id = {
        str(asset.get("id") or asset.get("asset_id")): asset
        for asset in assets
        if asset.get("id") or asset.get("asset_id")
    }
    children: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        for source_id in asset.get("referenceAssetIds") or []:
            source_id = str(source_id or "").strip()
            if not source_id or source_id == asset.get("id"):
                continue
            children.setdefault(source_id, []).append(_asset_lineage_snapshot(asset))

    for asset in assets:
        resolved_refs = []
        for ref in asset.get("referenceAssets") or []:
            ref_id = str(ref.get("asset_id") or ref.get("id") or "").strip()
            if ref_id and ref_id in by_id:
                merged = {**ref, **_asset_lineage_snapshot(by_id[ref_id])}
            else:
                merged = dict(ref)
                if ref_id:
                    merged.update({
                        "missing": True,
                        "deleted": True,
                        "title": merged.get("title") or "来源已删除",
                        "imageUrl": merged.get("imageUrl") or merged.get("image_url") or "",
                        "thumbUrl": merged.get("thumbUrl") or merged.get("thumb_url") or "",
                    })
            resolved_refs.append(merged)
        child_assets = sorted(
            children.get(str(asset.get("id") or asset.get("asset_id")), []),
            key=lambda item: int(item.get("createdAt") or 0),
            reverse=True,
        )
        related_map: dict[str, dict[str, Any]] = {}
        for source_id in asset.get("referenceAssetIds") or []:
            for child in children.get(str(source_id or "").strip(), []):
                child_id = str(child.get("id") or child.get("asset_id") or "")
                if not child_id or child_id == asset.get("id"):
                    continue
                related_map[child_id] = child
        related_assets = sorted(
            related_map.values(),
            key=lambda item: int(item.get("createdAt") or 0),
            reverse=True,
        )
        asset["lineage"] = {
            **(asset.get("lineage") or {}),
            "reference_assets": resolved_refs,
            "referenceAssets": resolved_refs,
            "derived_assets": child_assets[:12],
            "derivedAssets": child_assets[:12],
            "derived_count": len(child_assets),
            "derivedCount": len(child_assets),
            "related_assets": related_assets[:12],
            "relatedAssets": related_assets[:12],
            "related_count": len(related_assets),
            "relatedCount": len(related_assets),
        }
        asset["referenceAssets"] = resolved_refs
        asset["derivedAssets"] = child_assets[:12]
        asset["derivedCount"] = len(child_assets)
        asset["relatedAssets"] = related_assets[:12]
        asset["relatedCount"] = len(related_assets)


def _prompt_title(prompt: str, limit: int = 34) -> str:
    text = " ".join(str(prompt or "").split())
    if not text:
        return "图片资产"
    return text if len(text) <= limit else f"{text[:limit]}..."


def _set_title(name: str, assets: list[dict[str, Any]]) -> str:
    title = " ".join(str(name or "").split())[:60]
    if title:
        return title
    first_prompt = str((assets[0] if assets else {}).get("prompt") or "")
    return _prompt_title(first_prompt, 24) if first_prompt else "未命名候选集"


def _asset_set_id() -> str:
    return f"set_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _clean_asset_snapshot(asset: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(asset, dict):
        return {}
    asset_id = str(asset.get("asset_id") or asset.get("id") or "").strip()
    if not asset_id:
        return {}
    allowed = (
        "id",
        "asset_id",
        "taskId",
        "task_id",
        "file",
        "imageUrl",
        "imagePath",
        "image_path",
        "thumbUrl",
        "thumb_url",
        "title",
        "prompt",
        "type",
        "provider",
        "providerLabel",
        "provider_label",
        "resolution",
        "requestedResolution",
        "requested_resolution",
        "actualResolution",
        "actual_resolution",
        "resolutionMismatch",
        "resolution_mismatch",
        "width",
        "height",
        "dimensions",
        "megapixels",
        "status",
        "createdAt",
        "created_at",
        "updatedAt",
        "updated_at",
        "params",
        "index",
        "total",
        "favorite",
        "hidden",
        "tags",
        "rating",
        "note",
        "lineage",
        "referenceAssets",
        "referenceAssetIds",
        "derivedAssets",
        "derivedCount",
        "relatedAssets",
        "relatedCount",
    )
    snapshot = {key: asset.get(key) for key in allowed if key in asset}
    snapshot["id"] = asset_id
    snapshot["asset_id"] = asset_id
    snapshot["tags"] = _decode_tags(snapshot.get("tags"))
    return snapshot


def _asset_map_for_sets() -> dict[str, dict[str, Any]]:
    # 与其他调用方一致的 5000 上限；命中成品索引缓存后这只是一次切片
    data = list_assets(limit=5000, offset=0, include_hidden=True)
    return {
        str(asset.get("id") or asset.get("asset_id")): asset
        for asset in data.get("assets", [])
        if asset.get("id") or asset.get("asset_id")
    }


def _row_to_set(row: sqlite3.Row, asset_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    item = dict(row)
    asset_ids = [str(value) for value in _decode_json_list(item.get("asset_ids_json")) if str(value or "").strip()]
    snapshots = [
        _clean_asset_snapshot(snapshot)
        for snapshot in _decode_json_list(item.get("asset_snapshots_json"))
        if isinstance(snapshot, dict)
    ]
    snapshot_map = {snapshot["asset_id"]: snapshot for snapshot in snapshots if snapshot.get("asset_id")}
    current_assets = asset_map if asset_map is not None else _asset_map_for_sets()

    assets: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        asset = current_assets.get(asset_id) or snapshot_map.get(asset_id)
        if asset:
            assets.append(asset)

    return {
        "id": item.get("set_id"),
        "set_id": item.get("set_id"),
        "name": item.get("name") or "未命名候选集",
        "tags": _decode_tags(item.get("tags_json")),
        "asset_ids": asset_ids,
        "assetIds": asset_ids,
        "assets": assets,
        "count": len(asset_ids),
        "status": item.get("status") or "active",
        "created_at": item.get("created_at") or 0,
        "createdAt": item.get("created_at") or 0,
        "updated_at": item.get("updated_at") or item.get("created_at") or 0,
        "updatedAt": item.get("updated_at") or item.get("created_at") or 0,
    }


def _load_old_history(limit: int) -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except Exception:
                    continue
                timestamp = raw.get("timestamp") or raw.get("created_at") or 0
                items.append({
                    "task_id": f"old_{timestamp}_{len(items)}",
                    "status": "success" if raw.get("status") == "success" else raw.get("status", "failed"),
                    "prompt": raw.get("prompt", ""),
                    "params": raw.get("params", {}),
                    "output_file": raw.get("output_file"),
                    "result_file": raw.get("output_file"),
                    "created_at": timestamp,
                    "timestamp": timestamp,
                    "updated_at": raw.get("updated_at") or timestamp,
                    "type": raw.get("type", "google-gen"),
                    "is_old": True,
                })
    except Exception:
        return []
    items.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    return items[:limit]


def _task_assets(item: dict[str, Any], meta_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    provider = _provider_group(item)
    provider_label = _provider_label(provider)
    prompt = str(item.get("prompt") or "")
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    lineage = _lineage_from_params(params)
    requested_resolution = (
        normalize_resolution_label(params.get("requested_resolution"))
        or normalize_resolution_label(params.get("resolution"))
        or normalize_resolution_label(params.get("image_size"))
        or normalize_resolution_label(params.get("size"))
    )
    actual_resolution = (
        normalize_resolution_label(params.get("actual_resolution"))
        or normalize_resolution_label(params.get("effective_resolution"))
    )
    files = _result_files(item)
    paths = item.get("image_paths") if isinstance(item.get("image_paths"), list) else []
    task_id = str(item.get("task_id") or item.get("id") or "")
    created_at = int(item.get("created_at") or item.get("timestamp") or 0)
    total = max(len(files), len(paths))
    assets: list[dict[str, Any]] = []
    for index in range(total):
        file_name = files[index] if index < len(files) else (files[0] if files else "")
        image_url = paths[index] if index < len(paths) else _image_url(provider, file_name)
        if not image_url:
            continue
        asset_id = _asset_id(task_id, file_name, index, image_url)
        meta = meta_map.get(asset_id, {})
        tags = _decode_tags(meta.get("tags"))
        title = _prompt_title(prompt)
        if total > 1:
            title = f"{title} · {index + 1}/{total}"
        assets.append({
            "id": asset_id,
            "asset_id": asset_id,
            "taskId": task_id,
            "file": file_name,
            "imageUrl": image_url,
            "imagePath": image_url,
            "thumbUrl": _thumb_url(provider, file_name, image_url),
            "title": title,
            "prompt": prompt,
            "revisedPrompt": params.get("revised_prompt") or "",
            "revised_prompt": params.get("revised_prompt") or "",
            "mainModel": params.get("main_model") or "",
            "reasoningEffort": params.get("reasoning_effort") or "",
            "requestedResolution": requested_resolution,
            "requested_resolution": requested_resolution,
            "actualResolution": actual_resolution,
            "actual_resolution": actual_resolution,
            "resolution": actual_resolution or requested_resolution,
            "resolutionMismatch": bool(params.get("resolution_mismatch")),
            "resolution_mismatch": bool(params.get("resolution_mismatch")),
            "type": item.get("type") or "",
            "provider": provider,
            "providerLabel": provider_label,
            "status": item.get("status") or "",
            "createdAt": created_at,
            "updatedAt": item.get("updated_at") or created_at,
            "params": params,
            "lineage": lineage,
            "referenceAssets": lineage.get("referenceAssets") or [],
            "referenceAssetIds": lineage.get("referenceAssetIds") or [],
            "sourceTaskIds": lineage.get("sourceTaskIds") or [],
            "derivedAssets": [],
            "derivedCount": 0,
            "relatedAssets": [],
            "relatedCount": 0,
            "index": index,
            "total": total,
            "favorite": bool(meta.get("favorite")),
            "hidden": bool(meta.get("hidden")),
            "tags": tags,
            "rating": int(meta.get("rating") or 0),
            "note": meta.get("note") or "",
        })
    return assets


def _archive_asset_from_path(
    path: Path,
    root_key: str,
    rel_path: str,
    meta_map: dict[str, dict[str, Any]],
    template: dict[str, Any] | None = None,
    preserve_template_id: bool = False,
) -> dict[str, Any]:
    sidecar_prompt, sidecar_params = _read_archive_sidecar(path)
    provider = _infer_archive_provider(path, template)
    provider_label = _provider_label(provider)
    file_name = path.name
    public_rel_path = _archive_public_rel_path(root_key, rel_path)
    image_url = _archive_image_url(root_key, rel_path)
    has_task_record = bool(template)
    asset_id = str(template.get("id") or template.get("asset_id")) if template and preserve_template_id else _archive_asset_id(public_rel_path)
    meta = meta_map.get(asset_id, {})
    tags = _decode_tags(meta.get("tags"))
    prompt = str((template or {}).get("prompt") or sidecar_prompt or "")
    template_params = (template or {}).get("params") if isinstance((template or {}).get("params"), dict) else {}
    image_meta = _image_file_meta(path)
    params = _merge_params(sidecar_params, template_params)
    requested_resolution = (
        normalize_resolution_label(params.get("requested_resolution"))
        or normalize_resolution_label(params.get("resolution"))
        or normalize_resolution_label(params.get("image_size"))
        or normalize_resolution_label(params.get("size"))
    )
    if requested_resolution:
        params.setdefault("requested_resolution", requested_resolution)
    if image_meta:
        for param_key, meta_key in (
            ("width", "width"),
            ("height", "height"),
            ("aspect_ratio", "aspectRatio"),
            ("dimensions", "dimensions"),
            ("format", "format"),
        ):
            value = image_meta.get(meta_key)
            if value not in (None, ""):
                params.setdefault(param_key, value)
        actual_resolution = normalize_resolution_label(image_meta.get("resolution"))
        if actual_resolution:
            params.setdefault("actual_resolution", actual_resolution)
            params.setdefault("effective_resolution", actual_resolution)
            if requested_resolution:
                params.setdefault("resolution_mismatch", actual_resolution != requested_resolution)
    lineage = (template or {}).get("lineage") if isinstance((template or {}).get("lineage"), dict) else _lineage_from_params(params)
    try:
        created_at = int(path.stat().st_mtime)
    except Exception:
        created_at = int(time.time())
    try:
        generated_at = int(params.get("generated_at") or 0)
        if generated_at > 0 and not template:
            created_at = generated_at
    except Exception:
        pass

    asset = {
        "id": asset_id,
        "asset_id": asset_id,
        "taskId": (template or {}).get("taskId") or f"archive:{hashlib.sha1(public_rel_path.encode('utf-8')).hexdigest()[:12]}",
        "task_id": (template or {}).get("taskId") or f"archive:{hashlib.sha1(public_rel_path.encode('utf-8')).hexdigest()[:12]}",
        "file": file_name,
        "archiveRelPath": public_rel_path,
        "archive_rel_path": public_rel_path,
        "imageUrl": image_url,
        "imagePath": image_url,
        "thumbUrl": _thumb_url(provider, file_name, image_url, original_path=path),
        "title": (template or {}).get("title") or _prompt_title(prompt or path.stem),
        "prompt": prompt,
        "revisedPrompt": params.get("revised_prompt") or "",
        "revised_prompt": params.get("revised_prompt") or "",
        "mainModel": params.get("main_model") or "",
        "reasoningEffort": params.get("reasoning_effort") or "",
        "requestedResolution": params.get("requested_resolution") or requested_resolution,
        "requested_resolution": params.get("requested_resolution") or requested_resolution,
        "actualResolution": params.get("actual_resolution") or "",
        "actual_resolution": params.get("actual_resolution") or "",
        "resolutionMismatch": bool(params.get("resolution_mismatch")),
        "resolution_mismatch": bool(params.get("resolution_mismatch")),
        "type": (template or {}).get("type") or f"{provider}-archive",
        "provider": provider,
        "providerLabel": provider_label,
        "sourceKind": "history" if has_task_record else "archive",
        "assetSource": "history" if has_task_record else "archive",
        "hasTaskRecord": has_task_record,
        "has_task_record": has_task_record,
        "missingArchive": False,
        "missing_archive": False,
        "status": (template or {}).get("status") or "archived",
        "createdAt": int((template or {}).get("createdAt") or created_at),
        "updatedAt": int((template or {}).get("updatedAt") or created_at),
        "params": params,
        "lineage": lineage,
        "referenceAssets": lineage.get("referenceAssets") or [],
        "referenceAssetIds": lineage.get("referenceAssetIds") or [],
        "sourceTaskIds": lineage.get("sourceTaskIds") or [],
        "derivedAssets": [],
        "derivedCount": 0,
        "relatedAssets": [],
        "relatedCount": 0,
        "index": int((template or {}).get("index") or 0),
        "total": int((template or {}).get("total") or 1),
        "favorite": bool(meta.get("favorite")),
        "hidden": bool(meta.get("hidden")),
        "tags": tags,
        "rating": int(meta.get("rating") or 0),
        "note": meta.get("note") or "",
    }
    asset.update(image_meta)
    if asset.get("actualResolution"):
        asset["resolution"] = asset.get("actualResolution")
    elif image_meta.get("resolution"):
        asset["actualResolution"] = image_meta.get("resolution")
        asset["actual_resolution"] = image_meta.get("resolution")
    return asset


def _history_missing_asset_from_template(template: dict[str, Any], meta_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    file_name = str(template.get("file") or "").strip()
    provider = str(template.get("provider") or _provider_group(template) or "google")
    project_root = APP_DATA_DIR
    local_url = ""
    thumb_url = ""
    if provider == "gpt":
        candidate = project_root / "gpt_outputs" / file_name
        if candidate.exists():
            local_url = f"/gpt_outputs/{file_name}"
        thumb_candidate = project_root / "gpt_outputs" / f"{Path(file_name).stem}_thumb.png"
        if thumb_candidate.exists():
            thumb_url = f"/gpt_outputs/{thumb_candidate.name}"
    else:
        candidate = project_root / "google_outputs" / file_name
        if candidate.exists():
            local_url = f"/google_outputs/{file_name}"
        thumb_candidate = project_root / "google_outputs" / f"thumb_{file_name}"
        if thumb_candidate.exists():
            thumb_url = f"/google_outputs/{thumb_candidate.name}"

    asset_id = f"asset_missing_{hashlib.sha1((str(template.get('taskId') or '') + '|' + file_name).encode('utf-8', errors='ignore')).hexdigest()[:20]}"
    meta = meta_map.get(asset_id, {})
    lineage = template.get("lineage") if isinstance(template.get("lineage"), dict) else {}
    asset = {
        **template,
        "id": asset_id,
        "asset_id": asset_id,
        "imageUrl": local_url,
        "imagePath": local_url,
        "thumbUrl": thumb_url_for_media_url(thumb_url or local_url) if (thumb_url or local_url) else "",
        "sourceKind": "missing_history",
        "assetSource": "missing_history",
        "hasTaskRecord": True,
        "has_task_record": True,
        "missingArchive": True,
        "missing_archive": True,
        "status": template.get("status") or "missing_archive",
        "lineage": lineage,
        "favorite": bool(meta.get("favorite")),
        "hidden": bool(meta.get("hidden")),
        "tags": _decode_tags(meta.get("tags")),
        "rating": int(meta.get("rating") or 0),
        "note": meta.get("note") or "",
    }
    if not asset.get("title"):
        asset["title"] = _prompt_title(asset.get("prompt") or file_name)
    return asset


def _matches_query(asset: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    params = asset.get("params") if isinstance(asset.get("params"), dict) else {}
    haystack = " ".join([
        str(asset.get("prompt") or ""),
        str(asset.get("file") or ""),
        str(asset.get("taskId") or asset.get("task_id") or ""),
        str(asset.get("archiveRelPath") or asset.get("archive_rel_path") or ""),
        str(asset.get("title") or ""),
        str(asset.get("providerLabel") or ""),
        str(asset.get("dimensions") or ""),
        str(asset.get("aspectRatio") or asset.get("aspect_ratio") or ""),
        str(asset.get("orientation") or ""),
        _orientation_label(str(asset.get("orientation") or "")),
        str(asset.get("format") or ""),
        str(asset.get("fileSizeLabel") or asset.get("file_size_label") or ""),
        str(params.get("actual_resolution") or params.get("effective_resolution") or asset.get("actualResolution") or asset.get("actual_resolution") or asset.get("resolution") or ""),
        str(params.get("requested_resolution") or params.get("resolution") or params.get("image_size") or params.get("size") or asset.get("requestedResolution") or asset.get("requested_resolution") or ""),
        str(params.get("ratio") or params.get("aspect_ratio") or params.get("aspectRatio") or ""),
        str(params.get("format") or ""),
        " ".join(asset.get("tags") or []),
        " ".join(str(ref.get("title") or ref.get("asset_id") or "") for ref in asset.get("referenceAssets") or []),
        " ".join(str(child.get("title") or child.get("asset_id") or "") for child in asset.get("derivedAssets") or []),
        " ".join(str(item.get("title") or item.get("asset_id") or "") for item in asset.get("relatedAssets") or []),
    ]).lower()
    return query.lower() in haystack


def _asset_ratio(asset: dict[str, Any]) -> str:
    params = asset.get("params") if isinstance(asset.get("params"), dict) else {}
    return str(
        params.get("ratio")
        or params.get("aspect_ratio")
        or params.get("aspectRatio")
        or asset.get("aspectRatio")
        or asset.get("aspect_ratio")
        or ""
    ).strip().lower()


def _asset_resolution(asset: dict[str, Any]) -> str:
    params = asset.get("params") if isinstance(asset.get("params"), dict) else {}
    return normalize_resolution_label(
        params.get("actual_resolution")
        or params.get("effective_resolution")
        or asset.get("actualResolution")
        or asset.get("actual_resolution")
        or asset.get("resolution")
        or params.get("requested_resolution")
        or params.get("resolution")
        or params.get("image_size")
        or params.get("size")
        or ""
    )


def _asset_format(asset: dict[str, Any]) -> str:
    raw = str(asset.get("format") or "").strip().lower()
    if raw:
        return "jpg" if raw == "jpeg" else raw
    suffix = Path(str(asset.get("file") or "")).suffix.lower().lstrip(".")
    return "jpg" if suffix == "jpeg" else suffix


def _orientation_label(value: str) -> str:
    return {
        "landscape": "横图",
        "portrait": "竖图",
        "square": "方图",
    }.get(str(value or "").strip().lower(), "")


def _build_index_variants() -> dict[str, dict[str, Any]]:
    """一次性构建两种视图变体（全量 / 仅缺档历史），含血缘装饰。

    与旧版逐请求构建逻辑完全一致；missing 变体使用全新对象，
    避免与 all 变体共享 dict 被二次装饰互相污染。
    """
    meta_map = _load_meta()
    tasks = get_all_tasks(limit=10000, offset=0)
    tasks.extend(_load_old_history(10000))

    task_assets: list[dict[str, Any]] = []
    for task in tasks:
        task_assets.extend(_task_assets(task, meta_map))

    templates_by_file: dict[str, list[dict[str, Any]]] = {}
    for asset in task_assets:
        file_name = str(asset.get("file") or "").strip()
        if not file_name:
            continue
        templates_by_file.setdefault(file_name, []).append(asset)
    for templates in templates_by_file.values():
        templates.sort(key=lambda item: int(item.get("createdAt") or 0), reverse=True)

    archive_files = _archive_image_files()
    archive_name_counts: dict[str, int] = {}
    for path, _, _ in archive_files:
        archive_name_counts[path.name] = archive_name_counts.get(path.name, 0) + 1
    archive_names = set(archive_name_counts.keys())

    used_template_ids: set[str] = set()
    assets: list[dict[str, Any]] = []
    for path, root_key, rel_path in archive_files:
        templates = templates_by_file.get(path.name) or []
        template = templates[0] if templates else None
        preserve_template_id = False
        if template and archive_name_counts.get(path.name, 0) == 1:
            template_id = str(template.get("id") or template.get("asset_id") or "")
            if template_id and template_id not in used_template_ids:
                preserve_template_id = True
                used_template_ids.add(template_id)
        assets.append(_archive_asset_from_path(path, root_key, rel_path, meta_map, template, preserve_template_id))

    def _missing_assets() -> list[dict[str, Any]]:
        return [
            _history_missing_asset_from_template(asset, meta_map)
            for asset in task_assets
            if str(asset.get("file") or "").strip() and str(asset.get("file") or "").strip() not in archive_names
        ]

    history_missing_assets = _missing_assets()
    displayable_history_fallback_assets = [
        asset
        for asset in history_missing_assets
        if str(asset.get("imageUrl") or asset.get("thumbUrl") or "").strip()
    ]
    if displayable_history_fallback_assets:
        assets.extend(displayable_history_fallback_assets)

    linked_count = sum(1 for asset in assets if asset.get("hasTaskRecord"))
    orphan_count = len(assets) - linked_count
    metadata_count = sum(1 for asset in assets if asset.get("width") and asset.get("height"))
    stats = {
        "obsidian_image_count": len(archive_files),
        "archive_image_count": len(archive_files),
        "gallery_asset_count": len(assets),
        "indexed_asset_count": len(assets),
        "task_record_image_count": linked_count,
        "linked_asset_count": linked_count,
        "orphan_asset_count": orphan_count,
        "archive_only_count": orphan_count,
        "history_result_count": len(task_assets),
        "history_missing_count": len(history_missing_assets),
        "history_missing_archive_count": len(history_missing_assets),
        "metadata_image_count": metadata_count,
    }

    _decorate_lineage(assets)

    missing_variant_assets = _missing_assets()
    _decorate_lineage(missing_variant_assets)

    _flush_file_meta_cache()
    return {
        "all": {"assets": assets, "stats": stats},
        "missing": {"assets": missing_variant_assets, "stats": stats},
    }


def _get_index_variants() -> dict[str, dict[str, Any]]:
    """指纹 + TTL 双条件命中成品索引缓存；未命中则在锁内重建（并发请求只建一次）。"""
    global _INDEX_CACHE
    fingerprint = _index_fingerprint()
    with _INDEX_LOCK:
        cache = _INDEX_CACHE
        if (
            cache
            and cache["fingerprint"] == fingerprint
            and time.monotonic() - cache["built_at"] < _INDEX_TTL_SECONDS
        ):
            return cache["variants"]
        variants = _build_index_variants()
        _INDEX_CACHE = {
            "fingerprint": fingerprint,
            "built_at": time.monotonic(),
            "variants": variants,
        }
        return variants


def _asset_card_projection(asset: dict[str, Any]) -> dict[str, Any]:
    """图库网格卡片的瘦身投影（新建 dict，绝不改写缓存中的共享对象）。

    砍掉 revisedPrompt/revised_prompt、params.revised_prompt、
    lineage 装饰快照（derivedAssets/relatedAssets/referenceAssets 全量快照）。
    """
    card = {key: asset[key] for key in CARD_PROJECTION_FIELDS if key in asset}
    params = asset.get("params")
    if isinstance(params, dict):
        card["params"] = {key: value for key, value in params.items() if key not in CARD_PARAMS_DROP_KEYS}
    refs = asset.get("referenceAssets")
    if isinstance(refs, list) and refs:
        slim_refs = [
            {key: ref[key] for key in CARD_REFERENCE_KEYS if key in ref}
            for ref in refs
            if isinstance(ref, dict)
        ]
        card["referenceAssets"] = slim_refs
        card["reference_assets"] = slim_refs
    card["fieldsMode"] = "card"
    card["fields_mode"] = "card"
    return card


def list_assets(
    limit: int = 200,
    offset: int = 0,
    query: str = "",
    provider: str = "all",
    tag: str = "",
    favorite: bool = False,
    hidden: bool = False,
    include_hidden: bool = False,
    source: str = "all",
    ratio: str = "",
    orientation: str = "",
    file_format: str = "",
    resolution: str = "",
    fields: str = "",
) -> dict[str, Any]:
    init_asset_store()
    safe_limit = max(1, min(int(limit or 200), 5000))
    safe_offset = max(0, int(offset or 0))

    source_filter = str(source or "all").strip().lower()
    variants = _get_index_variants()
    variant_key = "missing" if source_filter in ("missing_history", "history_missing", "missing") else "all"
    variant = variants[variant_key]
    assets = variant["assets"]
    stats = variant["stats"]

    tag_filter = str(tag or "").strip().lstrip("#").lower()
    provider_filter = str(provider or "all").strip().lower()
    ratio_filter = str(ratio or "").strip().lower()
    orientation_filter = str(orientation or "").strip().lower()
    format_filter = str(file_format or "").strip().lower()
    if format_filter == "jpeg":
        format_filter = "jpg"
    resolution_filter = str(resolution or "").strip().lower()
    filtered = []
    for asset in assets:
        if not include_hidden and not hidden and asset.get("hidden"):
            continue
        if hidden and not asset.get("hidden"):
            continue
        if favorite and not asset.get("favorite"):
            continue
        if provider_filter not in ("", "all") and asset.get("provider") != provider_filter:
            continue
        if source_filter in ("linked", "history", "task", "task_record") and not asset.get("hasTaskRecord"):
            continue
        if source_filter in ("orphan", "archive", "archive_only") and asset.get("hasTaskRecord"):
            continue
        if ratio_filter and _asset_ratio(asset) != ratio_filter:
            continue
        if orientation_filter and str(asset.get("orientation") or "").lower() != orientation_filter:
            continue
        if format_filter and _asset_format(asset) != format_filter:
            continue
        if resolution_filter and _asset_resolution(asset) != resolution_filter:
            continue
        if tag_filter and tag_filter not in [str(item).lower() for item in asset.get("tags") or []]:
            continue
        if not _matches_query(asset, query):
            continue
        filtered.append(asset)

    filtered.sort(key=lambda item: (int(item.get("createdAt") or 0), item.get("taskId") or "", -int(item.get("index") or 0)), reverse=True)
    page = filtered[safe_offset:safe_offset + safe_limit]
    projection = str(fields or "").strip().lower()
    if projection in ("card", "list", "slim"):
        page = [_asset_card_projection(asset) for asset in page]
    known_tags = sorted({
        tag
        for item in assets
        if include_hidden or not item.get("hidden")
        for tag in (item.get("tags") or [])
    }, key=lambda value: value.lower())
    return {
        "assets": page,
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "tags": known_tags,
        "stats": stats,
    }


def get_asset(asset_id: str) -> dict[str, Any] | None:
    clean_id = str(asset_id or "").strip()
    if not clean_id:
        return None
    init_asset_store()
    variants = _get_index_variants()
    for variant_key in ("all", "missing"):
        for asset in variants[variant_key]["assets"]:
            if str(asset.get("id") or asset.get("asset_id") or "") == clean_id:
                # 返回深拷贝，避免调用方改写缓存中的共享对象
                return copy.deepcopy(asset)
    return None


def update_asset_meta(
    asset_id: str,
    favorite: bool | None = None,
    hidden: bool | None = None,
    tags: Any | None = None,
    rating: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    clean_id = str(asset_id or "").strip()
    if not clean_id:
        raise ValueError("缺少 asset_id")

    init_asset_store()
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}
    if favorite is not None:
        updates["favorite"] = 1 if bool(favorite) else 0
    if hidden is not None:
        updates["hidden"] = 1 if bool(hidden) else 0
    if tags is not None:
        updates["tags_json"] = json.dumps(_decode_tags(tags), ensure_ascii=False)
    if rating is not None:
        updates["rating"] = max(0, min(5, int(rating or 0)))
    if note is not None:
        updates["note"] = str(note or "")[:1000]

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO asset_meta (asset_id, favorite, hidden, tags_json, rating, note, created_at, updated_at)
            VALUES (?, 0, 0, '[]', 0, '', ?, ?)
            ON CONFLICT(asset_id) DO NOTHING
            """,
            (clean_id, now, now),
        )
        assignments = ", ".join(f"{key}=?" for key in updates)
        conn.execute(
            f"UPDATE asset_meta SET {assignments} WHERE asset_id=?",
            [*updates.values(), clean_id],
        )
        conn.commit()

    # 元数据变更立即失效成品索引，前端紧随其后的刷新会拿到新状态
    invalidate_asset_index_cache()

    meta = _load_meta().get(clean_id, {})
    return {
        "asset_id": clean_id,
        "id": clean_id,
        "favorite": bool(meta.get("favorite")),
        "hidden": bool(meta.get("hidden")),
        "tags": _decode_tags(meta.get("tags")),
        "rating": int(meta.get("rating") or 0),
        "note": meta.get("note") or "",
        "updated_at": meta.get("updated_at") or now,
    }


def remove_asset_from_sets(asset_id: str) -> int:
    clean_id = str(asset_id or "").strip()
    if not clean_id:
        return 0
    init_asset_store()
    now = _now()
    changed = 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT set_id, asset_ids_json, asset_snapshots_json FROM asset_sets WHERE COALESCE(status, 'active') != 'deleted'"
        ).fetchall()
        for row in rows:
            ids = [str(value) for value in _decode_json_list(row["asset_ids_json"]) if str(value or "").strip()]
            snapshots = [
                snapshot
                for snapshot in _decode_json_list(row["asset_snapshots_json"])
                if isinstance(snapshot, dict)
            ]
            if clean_id not in ids and not any(str(item.get("asset_id") or item.get("id") or "") == clean_id for item in snapshots):
                continue
            next_ids = [item for item in ids if item != clean_id]
            next_snapshots = [
                item for item in snapshots
                if str(item.get("asset_id") or item.get("id") or "") != clean_id
            ]
            if not next_ids:
                conn.execute(
                    "UPDATE asset_sets SET status='deleted', updated_at=? WHERE set_id=?",
                    (now, row["set_id"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE asset_sets
                    SET asset_ids_json=?, asset_snapshots_json=?, updated_at=?
                    WHERE set_id=?
                    """,
                    (
                        json.dumps(next_ids, ensure_ascii=False),
                        json.dumps(next_snapshots, ensure_ascii=False),
                        now,
                        row["set_id"],
                    ),
                )
            changed += 1
        conn.commit()
    return changed


def snapshot_sets_for_asset(asset_id: str) -> list[dict[str, Any]]:
    clean_id = str(asset_id or "").strip()
    if not clean_id:
        return []
    init_asset_store()
    snapshots: list[dict[str, Any]] = []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM asset_sets
            WHERE COALESCE(status, 'active') != 'deleted'
            """
        ).fetchall()
    for row in rows:
        item = dict(row)
        ids = [str(value or "").strip() for value in _decode_json_list(item.get("asset_ids_json")) if str(value or "").strip()]
        snapshots_json = [
            snapshot
            for snapshot in _decode_json_list(item.get("asset_snapshots_json"))
            if isinstance(snapshot, dict)
        ]
        has_asset = clean_id in ids or any(str(snapshot.get("asset_id") or snapshot.get("id") or "").strip() == clean_id for snapshot in snapshots_json)
        if has_asset:
            snapshots.append(item)
    return snapshots


def restore_asset_set_snapshots(snapshots: list[dict[str, Any]]) -> int:
    if not isinstance(snapshots, list) or not snapshots:
        return 0
    init_asset_store()
    restored = 0
    now = _now()
    with sqlite3.connect(DB_PATH) as conn:
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            set_id = str(snapshot.get("set_id") or "").strip()
            if not set_id:
                continue
            conn.execute(
                """
                INSERT INTO asset_sets
                    (set_id, name, tags_json, asset_ids_json, asset_snapshots_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(set_id) DO UPDATE SET
                    name=excluded.name,
                    tags_json=excluded.tags_json,
                    asset_ids_json=excluded.asset_ids_json,
                    asset_snapshots_json=excluded.asset_snapshots_json,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (
                    set_id,
                    snapshot.get("name") or "未命名候选集",
                    snapshot.get("tags_json") or "[]",
                    snapshot.get("asset_ids_json") or "[]",
                    snapshot.get("asset_snapshots_json") or "[]",
                    snapshot.get("status") or "active",
                    int(snapshot.get("created_at") or now),
                    now,
                ),
            )
            restored += 1
        conn.commit()
    return restored


def cleanup_asset_sets(valid_asset_ids: set[str], delete_empty: bool = True) -> dict[str, int]:
    """Remove missing asset references from sets and optionally delete empty sets."""
    valid_ids = {str(value or "").strip() for value in (valid_asset_ids or set()) if str(value or "").strip()}
    init_asset_store()
    now = _now()
    updated_sets = 0
    deleted_empty_sets = 0
    removed_refs = 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT set_id, asset_ids_json, asset_snapshots_json
            FROM asset_sets
            WHERE COALESCE(status, 'active') != 'deleted'
            """
        ).fetchall()
        for row in rows:
            raw_ids = [str(value or "").strip() for value in _decode_json_list(row["asset_ids_json"])]
            raw_ids = [value for value in raw_ids if value]
            snapshots = [
                snapshot
                for snapshot in _decode_json_list(row["asset_snapshots_json"])
                if isinstance(snapshot, dict)
            ]
            next_ids = [asset_id for asset_id in raw_ids if asset_id in valid_ids]
            next_snapshots = [
                snapshot
                for snapshot in snapshots
                if str(snapshot.get("asset_id") or snapshot.get("id") or "").strip() in valid_ids
            ]
            removed_here = max(0, len(raw_ids) - len(next_ids))
            removed_snapshots = max(0, len(snapshots) - len(next_snapshots))
            if not removed_here and not removed_snapshots:
                continue
            removed_refs += max(removed_here, removed_snapshots)
            if not next_ids and delete_empty:
                conn.execute(
                    "UPDATE asset_sets SET status='deleted', updated_at=? WHERE set_id=?",
                    (now, row["set_id"]),
                )
                deleted_empty_sets += 1
            else:
                conn.execute(
                    """
                    UPDATE asset_sets
                    SET asset_ids_json=?, asset_snapshots_json=?, updated_at=?
                    WHERE set_id=?
                    """,
                    (
                        json.dumps(next_ids, ensure_ascii=False),
                        json.dumps(next_snapshots, ensure_ascii=False, default=str),
                        now,
                        row["set_id"],
                    ),
                )
                updated_sets += 1
        conn.commit()
    return {
        "updated_sets": updated_sets,
        "deleted_empty_sets": deleted_empty_sets,
        "removed_refs": removed_refs,
    }


def record_delete_batch(payload: dict[str, Any]) -> dict[str, Any]:
    init_asset_store()
    now = _now()
    batch_id = str(payload.get("batch_id") or f"delete_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
    clean_payload = dict(payload or {})
    clean_payload["batch_id"] = batch_id
    clean_payload.setdefault("created_at", now)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO asset_delete_journal
                (batch_id, payload_json, created_at, restored, restored_at)
            VALUES (?, ?, ?, 0, 0)
            """,
            (
                batch_id,
                json.dumps(clean_payload, ensure_ascii=False, default=str),
                int(clean_payload.get("created_at") or now),
            ),
        )
        conn.commit()
    return clean_payload


def get_delete_batch(batch_id: str) -> dict[str, Any] | None:
    clean_id = str(batch_id or "").strip()
    if not clean_id:
        return None
    init_asset_store()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM asset_delete_journal WHERE batch_id=?",
            (clean_id,),
        ).fetchone()
    if not row:
        return None
    payload = {}
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["batch_id"] = clean_id
    payload["created_at"] = payload.get("created_at") or row["created_at"] or 0
    payload["restored"] = bool(row["restored"])
    payload["restored_at"] = row["restored_at"] or 0
    return payload


def mark_delete_batch_restored(batch_id: str) -> dict[str, Any]:
    clean_id = str(batch_id or "").strip()
    if not clean_id:
        raise ValueError("缺少删除批次 ID")
    init_asset_store()
    now = _now()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "UPDATE asset_delete_journal SET restored=1, restored_at=? WHERE batch_id=?",
            (now, clean_id),
        )
        conn.commit()
    if cursor.rowcount <= 0:
        raise ValueError("删除记录不存在")
    return {"batch_id": clean_id, "restored": True, "restored_at": now}


def _normalize_asset_set_payload(asset_ids: Any, assets: Any, max_items: int = 120) -> tuple[list[str], list[dict[str, Any]]]:
    clean_assets = [
        snapshot
        for snapshot in (_clean_asset_snapshot(item) for item in _decode_json_list(assets))
        if snapshot.get("asset_id")
    ]
    snapshot_by_id = {snapshot["asset_id"]: snapshot for snapshot in clean_assets}

    ids: list[str] = []
    seen: set[str] = set()
    for raw_id in _decode_json_list(asset_ids):
        asset_id = str(raw_id or "").strip()
        if not asset_id or asset_id in seen:
            continue
        seen.add(asset_id)
        ids.append(asset_id)
        if len(ids) >= max_items:
            break

    for snapshot in clean_assets:
        asset_id = snapshot["asset_id"]
        if asset_id in seen:
            continue
        seen.add(asset_id)
        ids.append(asset_id)
        if len(ids) >= max_items:
            break

    current_assets = _asset_map_for_sets()
    snapshots = [
        _clean_asset_snapshot(current_assets.get(asset_id) or snapshot_by_id.get(asset_id) or {"id": asset_id})
        for asset_id in ids
    ]
    snapshots = [snapshot for snapshot in snapshots if snapshot.get("asset_id")]
    return ids, snapshots


def list_asset_sets(
    limit: int = 80,
    offset: int = 0,
    query: str = "",
    tag: str = "",
) -> dict[str, Any]:
    init_asset_store()
    safe_limit = max(1, min(int(limit or 80), 300))
    safe_offset = max(0, int(offset or 0))
    tag_filter = str(tag or "").strip().lstrip("#").lower()
    search = str(query or "").strip().lower()

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM asset_sets
            WHERE COALESCE(status, 'active') != 'deleted'
            ORDER BY updated_at DESC, created_at DESC
            """
        ).fetchall()

    if not rows:
        # 没有候选集时直接返回，跳过 _asset_map_for_sets() 的全量资产扫描
        return {
            "sets": [],
            "total": 0,
            "limit": safe_limit,
            "offset": safe_offset,
            "tags": [],
        }

    asset_map = _asset_map_for_sets()
    sets = [_row_to_set(row, asset_map) for row in rows]
    filtered: list[dict[str, Any]] = []
    for item in sets:
        tags = _decode_tags(item.get("tags"))
        asset_tags = [
            tag
            for asset in item.get("assets") or []
            for tag in _decode_tags(asset.get("tags"))
        ]
        all_tags = tags + asset_tags
        if tag_filter and tag_filter not in [tag.lower() for tag in all_tags]:
            continue
        if search:
            haystack = " ".join([
                str(item.get("name") or ""),
                " ".join(all_tags),
                " ".join(str(asset.get("title") or "") for asset in item.get("assets") or []),
                " ".join(str(asset.get("prompt") or "") for asset in item.get("assets") or []),
                " ".join(str(asset.get("file") or "") for asset in item.get("assets") or []),
                " ".join(str(asset.get("providerLabel") or "") for asset in item.get("assets") or []),
            ]).lower()
            if search not in haystack:
                continue
        filtered.append(item)

    page = filtered[safe_offset:safe_offset + safe_limit]
    known_tags = sorted({
        tag
        for item in sets
        for tag in _decode_tags(item.get("tags"))
    }, key=lambda value: value.lower())
    return {
        "sets": page,
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "tags": known_tags,
    }


def create_asset_set(name: str, asset_ids: Any, tags: Any | None = None, assets: Any | None = None) -> dict[str, Any]:
    init_asset_store()
    ids, snapshots = _normalize_asset_set_payload(asset_ids, assets)
    if not ids:
        raise ValueError("候选集至少需要 1 张图片")

    now = _now()
    set_id = _asset_set_id()
    title = _set_title(name, snapshots)
    clean_tags = _decode_tags(tags)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO asset_sets
                (set_id, name, tags_json, asset_ids_json, asset_snapshots_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                set_id,
                title,
                json.dumps(clean_tags, ensure_ascii=False),
                json.dumps(ids, ensure_ascii=False),
                json.dumps(snapshots, ensure_ascii=False, default=str),
                now,
                now,
            ),
        )
        conn.commit()

    return get_asset_set(set_id)


def get_asset_set(set_id: str) -> dict[str, Any]:
    clean_id = str(set_id or "").strip()
    if not clean_id:
        raise ValueError("缺少候选集 ID")
    init_asset_store()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT *
            FROM asset_sets
            WHERE set_id=? AND COALESCE(status, 'active') != 'deleted'
            """,
            (clean_id,),
        ).fetchone()
    if not row:
        raise ValueError("候选集不存在")
    return _row_to_set(row)


def update_asset_set(
    set_id: str,
    name: str | None = None,
    asset_ids: Any | None = None,
    tags: Any | None = None,
    assets: Any | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    clean_id = str(set_id or "").strip()
    if not clean_id:
        raise ValueError("缺少候选集 ID")
    init_asset_store()
    now = _now()
    updates: dict[str, Any] = {"updated_at": now}
    if name is not None:
        updates["name"] = _set_title(name, _decode_json_list(assets))
    if tags is not None:
        updates["tags_json"] = json.dumps(_decode_tags(tags), ensure_ascii=False)
    if asset_ids is not None or assets is not None:
        ids, snapshots = _normalize_asset_set_payload(asset_ids, assets)
        if not ids:
            raise ValueError("候选集至少需要 1 张图片")
        updates["asset_ids_json"] = json.dumps(ids, ensure_ascii=False)
        updates["asset_snapshots_json"] = json.dumps(snapshots, ensure_ascii=False, default=str)
    if status is not None:
        clean_status = str(status or "active").strip().lower()
        updates["status"] = clean_status if clean_status in ("active", "archived", "deleted") else "active"

    with sqlite3.connect(DB_PATH) as conn:
        assignments = ", ".join(f"{key}=?" for key in updates)
        cursor = conn.execute(
            f"UPDATE asset_sets SET {assignments} WHERE set_id=?",
            [*updates.values(), clean_id],
        )
        conn.commit()
    if cursor.rowcount <= 0:
        raise ValueError("候选集不存在")
    if updates.get("status") == "deleted":
        return {
            "id": clean_id,
            "set_id": clean_id,
            "status": "deleted",
            "updated_at": now,
            "updatedAt": now,
        }
    return get_asset_set(clean_id)


def delete_asset_set(set_id: str) -> dict[str, Any]:
    return update_asset_set(set_id, status="deleted")
