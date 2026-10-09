"""Bounded local image uploads with opaque, expiring tokens."""
from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import uuid

from PIL import Image, UnidentifiedImageError


class ImageUploads:
    def __init__(self, directory, limit=32 * 1024**2):
        self.directory = Path(directory)
        self.limit = int(limit)
        self._records = {}
        self._lock = threading.RLock()

    def upload(self, content, filename="reference"):
        if not content or len(content) > self.limit:
            raise ValueError("参考图须小于 32 MB")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
                width, height, fmt = image.width, image.height, image.format
        except (ValueError, OSError, UnidentifiedImageError):
            raise ValueError("无法识别参考图") from None
        if not width or not height or width * height > 100_000_000:
            raise ValueError("参考图像素过大或尺寸无效")
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "AVIF": ".avif"}.get(fmt)
        if not suffix:
            raise ValueError("仅支持 PNG、JPEG、WebP 或 AVIF 参考图")
        self.directory.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        destination = self.directory / (token + suffix)
        with tempfile.NamedTemporaryFile(prefix=".upload-", dir=self.directory, delete=False) as stream:
            pending = Path(stream.name)
            stream.write(content)
        os.replace(pending, destination)
        with self._lock:
            now = time.time()
            for previous, (path, expires) in list(self._records.items()):
                if expires < now:
                    path.unlink(missing_ok=True)
                    self._records.pop(previous, None)
            self._records[token] = (destination, now + 3600)
        return {"ok": True, "upload_token": token, "width": width, "height": height,
                "filename": Path(str(filename or "reference")).name[:160]}

    def copy(self, token, directory, stem):
        with self._lock:
            record = self._records.get(str(token or ""))
            if not record or record[1] < time.time() or not record[0].is_file():
                raise ValueError("参考图已过期，请重新连接并上传")
            destination = Path(directory) / (stem + record[0].suffix)
            shutil.copyfile(record[0], destination)
            return str(destination.resolve())
