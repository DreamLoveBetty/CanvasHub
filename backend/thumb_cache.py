#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""On-demand WebP thumbnail cache for gallery media."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Callable

from PIL import Image

from .app_config import APP_DATA_DIR, BASE_DIR


FRONTEND_ROOT = BASE_DIR / "frontend"
THUMB_CACHE_ROOT = APP_DATA_DIR / "cache" / "thumb"
THUMB_MAX_SIDE = 420
THUMB_QUALITY = 76
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


Resolver = Callable[[str], Path | None]


def thumb_url_for_media_url(url: str, *, size: int = THUMB_MAX_SIDE) -> str:
    """Return the public cache endpoint for an existing same-origin media URL."""
    raw = str(url or "").strip()
    if not raw or raw.startswith(("data:", "blob:")) or re.match(r"^https?://", raw, re.I):
        return raw
    parsed = urllib.parse.urlparse(raw)
    clean_path = parsed.path or raw
    if not clean_path.startswith("/"):
        clean_path = "/" + clean_path.lstrip("/")
    encoded = urllib.parse.quote(clean_path, safe="")
    safe_size = max(96, min(1024, int(size or THUMB_MAX_SIDE)))
    return f"/thumb/{encoded}.webp?w={safe_size}"


def parse_thumb_request(path: str) -> str:
    """Decode `/thumb/<quoted-original>.webp` into the original media path."""
    raw = urllib.parse.unquote(str(path or "")[len("/thumb/"):])
    if raw.lower().endswith(".webp"):
        raw = raw[:-5]
    if not raw.startswith("/"):
        raw = "/" + raw.lstrip("/")
    return raw


def _safe_int(value: str | int | None, default: int) -> int:
    try:
        number = int(value or default)
    except Exception:
        number = default
    return max(96, min(1024, number))


def _file_signature(source: Path) -> str:
    stat = source.stat()
    return f"{source.resolve()}|{int(stat.st_mtime_ns)}|{int(stat.st_size)}"


def thumb_cache_path(source: Path, *, size: int = THUMB_MAX_SIDE) -> Path:
    safe_size = _safe_int(size, THUMB_MAX_SIDE)
    digest = hashlib.sha256(f"{_file_signature(source)}|w={safe_size}|webp".encode("utf-8", errors="ignore")).hexdigest()
    return THUMB_CACHE_ROOT / digest[:2] / f"{digest}.webp"


def resolve_media_path(media_path: str, resolvers: dict[str, Resolver]) -> Path | None:
    """Resolve an already-authenticated media URL path to a local image file."""
    parsed = urllib.parse.urlparse(str(media_path or ""))
    path = urllib.parse.unquote(parsed.path or "").replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    if path.startswith("/archive_image/"):
        return resolvers["archive"](path[len("/archive_image/"):])
    if path.startswith("/source_image/"):
        return resolvers["source"](path[len("/source_image/"):])
    if path.startswith("/image/"):
        return resolvers["image"](Path(path).name)
    if path.startswith("/google_outputs/"):
        candidate = (APP_DATA_DIR / "google_outputs" / Path(path).name).resolve()
        root = (APP_DATA_DIR / "google_outputs").resolve()
    elif path.startswith("/gpt_outputs/"):
        candidate = (APP_DATA_DIR / "gpt_outputs" / Path(path).name).resolve()
        root = (APP_DATA_DIR / "gpt_outputs").resolve()
    else:
        return None
    try:
        candidate.relative_to(root)
    except Exception:
        return None
    return candidate if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS else None


def ensure_webp_thumbnail(source: Path, *, size: int = THUMB_MAX_SIDE) -> Path:
    """Create or reuse a cached WebP thumbnail for a local image file."""
    source = Path(source).expanduser()
    if not source.is_file() or source.suffix.lower() not in IMAGE_EXTENSIONS:
        raise FileNotFoundError(str(source))

    safe_size = _safe_int(size, THUMB_MAX_SIDE)
    cache_path = thumb_cache_path(source, size=safe_size)
    if cache_path.is_file():
        return cache_path

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        frame = image.copy()
        frame.thumbnail((safe_size, safe_size), Image.LANCZOS)
        if frame.mode not in ("RGB", "RGBA"):
            frame = frame.convert("RGBA" if "A" in frame.getbands() else "RGB")
        with tempfile.NamedTemporaryFile(dir=str(cache_path.parent), suffix=".webp", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            frame.save(tmp_path, "WEBP", quality=THUMB_QUALITY, method=5)
            os.replace(tmp_path, cache_path)
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    return cache_path
