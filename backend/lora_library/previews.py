"""Bounded raster preview copies, isolated from generated asset archives."""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import time
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 32_000_000


class Previews:
    def __init__(self, root, repository):
        self.root, self.repository = Path(root), repository

    def path(self, preview_id, *, thumb=False):
        if not re.fullmatch(r"[a-f0-9]{32}", str(preview_id)):
            raise ValueError("预览 ID 无效")
        # The directory is derived from a stored record, never from client paths.
        item = next((p for r in self.repository.records().values() for p in r["previews"]
                     if p["id"] == preview_id), None)
        if item is None:
            raise ValueError("预览不存在或缓存已清理")
        directory = "cache" if item["kind"] == "remote" else "images"
        path = self.root / directory / (preview_id + (".thumb.webp" if thumb else ".webp"))
        if not path.is_file() or path.is_symlink():
            raise ValueError("预览文件不存在")
        return path

    def add(self, asset_id, content, *, kind="manual", source_url="", caption=""):
        self.repository.get(asset_id)
        if not content or len(content) > MAX_BYTES:
            raise ValueError("示例图须为 16 MB 以内的图片")
        if kind not in {"manual", "local", "remote"}:
            raise ValueError("预览来源无效")
        if len(self.repository.get(asset_id)["previews"]) >= 24:
            raise ValueError("每个 LoRA 最多保留 24 张示例图")
        try:
            with Image.open(io.BytesIO(content)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise ValueError("示例图支持 PNG、JPEG、WebP、GIF 首帧")
                if original.width * original.height > MAX_PIXELS:
                    raise ValueError("示例图像素过大")
                picture = ImageOps.exif_transpose(original).convert("RGB")
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("无法读取示例图") from exc
        preview_id = uuid.uuid4().hex
        directory = self.root / ("cache" if kind == "remote" else "images")
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        try:
            for suffix, size in ((".webp", 2048), (".thumb.webp", 384)):
                target = directory / (preview_id + suffix)
                temporary = target.with_suffix(".pending")
                paths.extend((target, temporary))
                resized = picture.copy()
                resized.thumbnail((size, size), Image.Resampling.LANCZOS)
                resized.save(temporary, format="WEBP", quality=88)
                os.replace(temporary, target)
            item = {"id": preview_id, "asset_id": asset_id, "kind": kind,
                    "source_url": source_url, "caption": str(caption)[:300], "created_at": time.time()}
            self.repository.add_preview(item)
            return item
        except Exception:
            for path in paths:
                path.unlink(missing_ok=True)
            raise

    def delete(self, asset_id, preview_id):
        record = self.repository.get(asset_id)
        item = next((p for p in record["previews"] if p["id"] == preview_id), None)
        if not item:
            raise ValueError("该预览不属于此 LoRA")
        for thumb in (False, True):
            try:
                self.path(preview_id, thumb=thumb).unlink(missing_ok=True)
            except ValueError:
                pass
        self.repository.drop_preview(preview_id)

    def clear_cache(self):
        count = 0
        for record in self.repository.records().values():
            for item in record["previews"]:
                if item["kind"] == "remote":
                    self.delete(record["asset_id"], item["id"])
                    count += 1
        return count
