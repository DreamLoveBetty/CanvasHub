"""Shared Qwen text-encoder variant: replacement record, swap and rollback. No MLX.

The pinned 8-bit Heretic encoder ships inside the shared Base directory. A
verified BF16 build of the same encoder may replace it in place: the 8-bit
directory moves to a hidden backup and `.text-encoder.json` proves the
replacement. Readiness then checks this record instead of the 8-bit pins; a
corrupt record or a changed file fails closed and never triggers a download.
Every Base links `text_encoder` to the shared path, so one swap covers all.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time

RECORD = ".text-encoder.json"
BACKUP = ".text_encoder-8bit-backup"
STAGING = ".text_encoder-staging"
RETIRED = ".text_encoder-retired"
INDEX = "text_encoder/model.safetensors.index.json"
BUILTIN = {"id": "heretic-8bit", "precision": "8bit", "label": "Heretic · MLX 8-bit"}


def read(shared):
    """Return the verified replacement record, None for the pinned 8-bit encoder."""
    path = Path(shared) / RECORD
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink():
        raise ValueError("文本编码器替换记录不能是符号链接")
    value = json.loads(path.read_text())
    files = value.get("verified_files") if isinstance(value, dict) else None
    if (value.get("schema_version") != 1 or value.get("precision") != "bf16"
            or not isinstance(value.get("id"), str) or not isinstance(files, dict)
            or INDEX not in files or "text_encoder/config.json" not in files):
        raise ValueError("文本编码器替换记录无效")
    for name, proof in files.items():
        parts = Path(name).parts
        if (not isinstance(name, str) or len(parts) != 2 or parts[0] != "text_encoder"
                or not isinstance(proof, dict)):
            raise ValueError("文本编码器替换记录路径无效")
        file = Path(shared) / name
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"替换版文本编码器缺少 {name}")
        stat = file.stat()
        if stat.st_size != proof.get("size") or stat.st_mtime_ns != proof.get("mtime_ns"):
            raise ValueError(f"替换版文本编码器 {name} 已变化")
    return value


def public(shared):
    value = read(shared)
    if value is None:
        return dict(BUILTIN)
    return {"id": value["id"], "precision": value["precision"], "label": value.get("label") or value["id"]}


def signature(model_path):
    """Worker cache key: a swapped encoder must reload an already warm pipeline."""
    index = (Path(model_path) / INDEX).resolve(strict=True)
    stat = index.stat()
    return (str(index), stat.st_mtime_ns, stat.st_size)


def _write_record(shared, value):
    pending = Path(shared) / (RECORD + ".tmp")
    with pending.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(Path(shared) / RECORD)


def activate(shared, staging, *, identity, checksums):
    """Swap a fully staged encoder in; the 8-bit directory is kept as backup.

    `staging` must be `shared/STAGING`, so both renames stay on one volume.
    """
    shared, staging = Path(shared), Path(staging)
    current, backup = shared / "text_encoder", shared / BACKUP
    if staging != shared / STAGING or staging.is_symlink() or not staging.is_dir():
        raise RuntimeError("文本编码器暂存目录无效")
    if read(shared) is not None:
        raise RuntimeError("已安装替换版文本编码器，请先还原")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError("8-bit 文本编码器备份已存在，保留现场")
    if current.is_symlink() or not current.is_dir():
        raise RuntimeError("共享文本编码器目录无效，保留现场")
    files = {}
    for file in sorted(staging.iterdir()):
        if file.is_symlink() or not file.is_file():
            raise RuntimeError("文本编码器暂存目录含非常规文件")
        stat = file.stat()
        name = "text_encoder/" + file.name
        files[name] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                       **({"sha256": checksums[name]} if name in checksums else {})}
    os.rename(current, backup)
    try:
        os.rename(staging, current)
    except OSError:
        os.rename(backup, current)
        raise
    _write_record(shared, {"schema_version": 1, **identity, "precision": "bf16",
                           "installed_at": int(time.time()), "backup": BACKUP, "verified_files": files})
    return public(shared)


def restore(shared):
    """Return to the pinned 8-bit encoder from its backup; removes the BF16 copy."""
    shared = Path(shared)
    current, backup, retired = shared / "text_encoder", shared / BACKUP, shared / RETIRED
    if backup.is_symlink() or not backup.is_dir():
        raise RuntimeError("没有可还原的 8-bit 文本编码器备份")
    if retired.exists() or retired.is_symlink():
        raise RuntimeError("上次还原的残留目录仍在，保留现场")
    # Drop the proof first: an interrupted restore fails closed, never half-trusted.
    (shared / RECORD).unlink(missing_ok=True)
    os.rename(current, retired)
    try:
        os.rename(backup, current)
    except OSError:
        os.rename(retired, current)
        raise
    shutil.rmtree(retired)
    return public(shared)
