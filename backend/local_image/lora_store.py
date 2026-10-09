"""Architecture-neutral LoRA library in one directly scannable folder."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile
import threading
import time

MAX_LORA_UPLOAD = 2 * 1024**3

def normalize_asset_id(value):
    value = str(value or "").removeprefix("sha256:").strip().lower()
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("LoRA 资产 ID 无效")
    return value


class LoRAStore:
    def __init__(self, root, *, label="LoRA", allow_peft_default=False):
        self.label = str(label)
        self.allow_peft_default = bool(allow_peft_default)
        self.root = Path(root)
        self.directory = self.root / "loras"
        self.index_path = self.directory / "index.json"
        self._lock = threading.RLock()
        self._scan_errors = []

    def _index(self):
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, value):
        self.directory.mkdir(parents=True, exist_ok=True)
        pending = self.index_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(pending, self.index_path)

    @staticmethod
    def _label(filename):
        return (re.sub(r"[\x00-\x1f/\\]+", " ", Path(str(filename)).stem).strip()[:120]
                or "LoRA")

    @staticmethod
    def _digest(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(4 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _public(item):
        return {key: item[key] for key in (
            "asset_id", "name", "file_size", "created_at", "tensor_count", "adapter_count"
        ) if key in item}

    @staticmethod
    def _storage_name(asset_id, item):
        name = str(item.get("_file") or f"{asset_id}.safetensors")
        if Path(name).name != name or Path(name).suffix.lower() != ".safetensors":
            return ""
        return name

    def _scan(self):
        """Reconcile the index with .safetensors files copied into the library."""
        self.directory.mkdir(parents=True, exist_ok=True)
        previous = self._index()
        cached_by_name = {}
        for raw_asset_id, raw_item in previous.items():
            if not isinstance(raw_item, dict):
                continue
            try:
                asset_id = normalize_asset_id(raw_asset_id)
            except ValueError:
                continue
            name = self._storage_name(asset_id, raw_item)
            if name:
                cached_by_name[name] = (asset_id, raw_item)

        reconciled = {}
        errors = []
        try:
            paths = sorted(self.directory.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            paths = []
        for path in paths:
            if path.name.startswith(".") or path.suffix.lower() != ".safetensors":
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                stat = path.stat()
                if stat.st_size <= 8 or stat.st_size > MAX_LORA_UPLOAD:
                    raise ValueError("LoRA 文件须小于 2 GB")
                cached = cached_by_name.get(path.name)
                if (cached and int(cached[1].get("file_size") or -1) == stat.st_size
                        and int(cached[1].get("_modified_ns") or -1) == stat.st_mtime_ns
                        and int(cached[1].get("_changed_ns") or -1) == stat.st_ctime_ns):
                    asset_id, item = cached[0], dict(cached[1])
                else:
                    info = self._inspect(path)
                    asset_id = self._digest(path)
                    old = previous.get(asset_id) if isinstance(previous.get(asset_id), dict) else {}
                    same_file = self._storage_name(asset_id, old) == path.name if old else False
                    item = {
                        "asset_id": asset_id,
                        "name": old.get("name") if same_file and old.get("name") else self._label(path.name),
                        "file_size": stat.st_size,
                        "created_at": old.get("created_at") or int(
                            getattr(stat, "st_birthtime", stat.st_mtime)),
                        **info,
                    }
                item.update({"asset_id": asset_id, "file_size": stat.st_size,
                             "_file": path.name, "_modified_ns": stat.st_mtime_ns,
                             "_changed_ns": stat.st_ctime_ns})
                current = reconciled.get(asset_id)
                # Identical files are one logical asset. Prefer the historical
                # content-addressed filename when both forms are present.
                if current and current.get("_file") == f"{asset_id}.safetensors":
                    continue
                reconciled[asset_id] = item
            except (OSError, ValueError) as exc:
                errors.append({"name": path.name, "error": str(exc)})

        self._scan_errors = errors
        if reconciled != previous:
            self._write(reconciled)
        return reconciled

    def scan_errors(self):
        with self._lock:
            return [dict(item) for item in self._scan_errors]

    def _inspect(self, path):
        size = path.stat().st_size
        with path.open("rb") as stream:
            raw = stream.read(8)
            if len(raw) != 8:
                raise ValueError("LoRA 文件头不完整")
            header_size = struct.unpack("<Q", raw)[0]
            if header_size < 2 or header_size > min(64 * 1024 * 1024, size - 8):
                raise ValueError("LoRA safetensors 文件头无效")
            try:
                header = json.loads(stream.read(header_size))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError("LoRA safetensors 元数据无效") from exc
        if not isinstance(header, dict):
            raise ValueError("LoRA safetensors 元数据必须为对象")
        payload_size = size - 8 - header_size
        keys = []
        a_targets, b_targets = set(), set()
        for key, value in header.items():
            if key == "__metadata__":
                continue
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ValueError("LoRA safetensors 张量元数据无效")
            dtype, shape, offsets = value.get("dtype"), value.get("shape"), value.get("data_offsets")
            if (not isinstance(dtype, str) or not isinstance(shape, list)
                    or any(isinstance(dim, bool) or not isinstance(dim, int) or dim < 0 for dim in shape)
                    or not isinstance(offsets, list) or len(offsets) != 2
                    or any(isinstance(offset, bool) or not isinstance(offset, int) for offset in offsets)
                    or offsets[0] < 0 or offsets[0] > offsets[1] or offsets[1] > payload_size):
                raise ValueError("LoRA safetensors 张量范围无效")
            keys.append(key)
            if self.allow_peft_default:
                key = key.replace(".lora_A.default.weight", ".lora_A.weight").replace(
                    ".lora_B.default.weight", ".lora_B.weight")
            matched = False
            for suffix, bucket in ((".lora_A.weight", a_targets),
                                   (".lora_down.weight", a_targets),
                                   (".lora_B.weight", b_targets),
                                   (".lora_up.weight", b_targets)):
                if key.endswith(suffix):
                    target = key[:-len(suffix)]
                    if not target or target in bucket or any(dim == 0 for dim in shape):
                        raise ValueError("LoRA safetensors 包含重复或空张量")
                    bucket.add(target)
                    matched = True
                    break
            if not matched and not key.endswith(".alpha"):
                raise ValueError(f"文件包含 {self.label} 不支持的张量")
        if not a_targets or a_targets != b_targets:
            raise ValueError(f"文件不是可识别的 {self.label}（A/B 张量不完整）")
        return {"tensor_count": len(keys), "adapter_count": len(a_targets)}

    def import_stream(self, stream, size, filename):
        if size <= 8 or size > MAX_LORA_UPLOAD:
            raise ValueError("LoRA 文件须小于 2 GB")
        if Path(str(filename or "")).suffix.lower() != ".safetensors":
            raise ValueError("LoRA 仅支持 .safetensors 文件")
        label = self._label(filename)
        self.directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(prefix=".import-", suffix=".safetensors", dir=self.directory,
                                         delete=False) as target:
            temp = Path(target.name)
            remaining = size
            while remaining:
                chunk = stream.read(min(4 * 1024 * 1024, remaining))
                if not chunk:
                    temp.unlink(missing_ok=True)
                    raise ValueError("LoRA 上传不完整")
                target.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        try:
            info = self._inspect(temp)
            asset_id = digest.hexdigest()
            destination = self.directory / f"{asset_id}.safetensors"
            with self._lock:
                if destination.exists():
                    temp.unlink(missing_ok=True)
                else:
                    os.replace(temp, destination)
                index = self._index()
                previous = index.get(asset_id) if isinstance(index.get(asset_id), dict) else {}
                stat = destination.stat()
                index[asset_id] = {"asset_id": asset_id, "name": label,
                                   "file_size": stat.st_size,
                                   "created_at": previous.get("created_at") or int(time.time()), **info,
                                   "_file": destination.name, "_modified_ns": stat.st_mtime_ns,
                                   "_changed_ns": stat.st_ctime_ns}
                self._write(index)
                return self._public(index[asset_id])
        finally:
            temp.unlink(missing_ok=True)

    def list(self):
        with self._lock:
            result = [self._public(item) for item in self._scan().values()]
            return sorted(result, key=lambda item: (-int(item.get("created_at") or 0), item.get("name", "")))

    def resolve(self, asset_id):
        asset_id = normalize_asset_id(asset_id)
        with self._lock:
            item = self._scan().get(asset_id)
            path = self.directory / self._storage_name(asset_id, item or {})
            if not isinstance(item, dict) or not path.is_file() or path.is_symlink():
                raise ValueError("LoRA 资产不存在，请检查 LoRA 目录")
            return path.resolve(), self._public(item)

    def library_snapshot(self):
        """Backend-only metadata port: one scan, paths never sent over HTTP."""
        with self._lock:
            index = self._scan()
            return {"loras": [{**self._public(item),
                              "_path": self.directory / self._storage_name(identity, item)}
                             for identity, item in index.items()],
                    "scan_errors": [dict(item) for item in self._scan_errors]}

    def delete(self, asset_id):
        asset_id = normalize_asset_id(asset_id)
        with self._lock:
            index = self._scan()
            item = index.pop(asset_id, None)
            if not isinstance(item, dict):
                raise ValueError("LoRA 资产不存在")
            (self.directory / self._storage_name(asset_id, item)).unlink(missing_ok=True)
            self._write(index)
            return self._public(item)
