"""Resumable immutable-file downloader, independent of inference domains."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import time

import requests


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path, *, size, sha256_value="", blob_id=""):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size != int(size):
        return False
    if sha256_value:
        return sha256(path) == sha256_value
    if blob_id:
        digest = hashlib.sha1(f"blob {size}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
                digest.update(chunk)
        return digest.hexdigest() == blob_id
    raise ValueError("下载必须提供固定文件校验值")


def download(url, path, *, size, sha256_value="", blob_id="", progress=None,
             headers=None, attempts=6):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if verify(path, size=size, sha256_value=sha256_value, blob_id=blob_id):
            return path
        raise RuntimeError(f"{path.name} 校验失败，保留文件供检查")
    pending = path.with_name(path.name + ".part")
    if pending.is_symlink():
        raise RuntimeError("下载断点文件不能是符号链接")
    for attempt in range(int(attempts)):
        position = pending.stat().st_size if pending.exists() else 0
        if position > size:
            raise RuntimeError("下载断点文件大小异常，保留现场")
        if position == size:
            break
        request_headers = dict(headers or {})
        if position:
            request_headers["Range"] = f"bytes={position}-"
        try:
            with requests.get(url, headers=request_headers, stream=True,
                              timeout=(30, 90)) as response:
                response.raise_for_status()
                resumed = bool(position and response.status_code == 206)
                if resumed and not response.headers.get("Content-Range", "").startswith(f"bytes {position}-"):
                    raise RuntimeError("模型下载断点响应不匹配")
                if not resumed:
                    position = 0
                reported = 0.0
                with pending.open("ab" if resumed else "wb") as stream:
                    for chunk in response.iter_content(4 * 1024**2):
                        if not chunk:
                            continue
                        stream.write(chunk)
                        position += len(chunk)
                        if position > size:
                            raise RuntimeError("模型下载大小超过固定版本清单")
                        if progress and time.monotonic() - reported > 2:
                            progress(position, size)
                            reported = time.monotonic()
            if position == size:
                break
        except requests.RequestException:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(15, 1 + 2 * attempt))
    if not verify(pending, size=size, sha256_value=sha256_value, blob_id=blob_id):
        raise RuntimeError(f"{path.name} 下载不完整或固定版本校验失败，保留断点文件")
    os.replace(pending, path)
    if progress:
        progress(size, size)
    return path
