"""Independent Qwen 2.1 VAE registry; no MLX imports or changes to Base pins.

Raw Diffusers and MFLUX exports are kept byte-for-byte. The worker's upstream
loader owns layout mapping. Selection is snapshotted on submission, never read
again by an already queued job.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading

from ..local_image.comfy_fp8 import read_safetensors_header
from ..local_image.downloads import sha256, verify
from .contracts import DEFAULT_MODEL_ID

BUILTIN = "builtin"
PIN = next(x for x in json.loads(Path(__file__).with_name("model_files.json").read_text())
           if x["rfilename"] == "vae/0.safetensors")
CONFIG_PIN = next(x for x in json.loads(Path(__file__).with_name("model_files.json").read_text())
                  if x["rfilename"] == "vae/config.json")


def native_shapes():
    return json.loads(Path(__file__).with_name("vae_schema.json").read_text())["shapes"]


def inspect_vae(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".safetensors":
        raise ValueError("请选择普通的本地 VAE .safetensors 文件")
    header = read_safetensors_header(path, max_checkpoint_bytes=3 * 1024**3, max_header_bytes=1024**2)
    shapes = native_shapes()
    if set(header.tensors) != set(shapes):
        raise ValueError("需要完整 Qwen-Image 2.1 RGBA VAE（238 个张量），不支持旧版 VAE 或 LoRA")
    native = any(k in header.metadata for k in ("mflux_version", "quantization_level"))
    # MFLUX exports stamp the whole model's quantization level (e.g. 8) on
    # the unquantized VAE too. Validate actual tensor dtypes/shapes instead.
    offsets = []
    for key, item in header.tensors.items():
        shape = item["shape"]
        expected = shapes[key]
        if not native:
            if key.endswith(".gamma"):
                if not shape or shape[0] != expected[0] or any(x != 1 for x in shape[1:]):
                    raise ValueError(f"VAE 归一化参数形状不匹配：{key}")
                expected = shape
            elif key.endswith(".weight") and len(expected) == 4:
                expected = [expected[0], expected[3], expected[1], expected[2]]
        if shape != expected:
            raise ValueError(f"VAE 张量布局不匹配：{key}；不可仅重命名或伪造 MFLUX 元数据")
        width = {"F32": 4, "F16": 2, "BF16": 2}.get(item["dtype"])
        start, end = item["data_offsets"]
        if not width or end - start != math.prod(shape) * width:
            raise ValueError(f"VAE 数据类型或张量字节数不匹配：{key}")
        offsets.append((start, end))
    cursor = 0
    for start, end in sorted(offsets):
        if start != cursor:
            raise ValueError("VAE 张量数据存在重叠或缺口")
        cursor = end
    if cursor != header.file_size - header.payload_offset:
        raise ValueError("VAE 张量数据不完整")
    return {"format": "mflux" if native else "diffusers", "file_size": header.file_size,
            "tensor_count": len(shapes), "dtypes": sorted({v["dtype"] for v in header.tensors.values()})}


def validate_snapshot(snapshot, *, checksum=False):
    """Validate a queued custom VAE again before even reusing a warm pipeline."""
    if not snapshot or snapshot.get("id") == BUILTIN:
        return
    for name, proof in snapshot["verified_files"].items():
        if name not in {"0.safetensors", "config.json"}:
            raise ValueError("VAE 校验清单无效")
        file = Path(snapshot["path"]) / name
        if file.is_symlink() or not file.is_file():
            raise ValueError("所选 VAE 文件已丢失；未回退到原版")
        stat = file.stat()
        if stat.st_size != proof["size"] or stat.st_mtime_ns != proof["mtime_ns"]:
            raise ValueError("所选 VAE 文件已修改，请重新导入；未回退到原版")
        if checksum and sha256(file) != proof["sha256"]:
            raise ValueError("所选 VAE 校验失败；未回退到原版")


class VaeStore:
    def __init__(self, assets):
        self.directory = Path(assets).resolve() / "vaes"
        self.import_directory = self.directory / "imports"
        self.shared = Path(assets).resolve() / "base_models" / DEFAULT_MODEL_ID
        self.selection_file = self.directory / "selection.json"
        self._lock = threading.RLock()

    @staticmethod
    def public(item):
        return {k: item[k] for k in ("id", "name", "format", "sha256", "file_size", "dtypes") if k in item}

    def selected_id(self):
        if not self.selection_file.exists():
            return BUILTIN
        try:
            return self._id(json.loads(self.selection_file.read_text())["id"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("VAE 选择记录无效，请重新选择；未回退到原版") from exc

    @staticmethod
    def _id(value):
        if value != BUILTIN and not re.fullmatch(r"[a-f0-9]{64}", str(value)):
            raise ValueError("无效的 VAE ID")
        return value

    def resolve(self, vae_id=None):
        with self._lock:
            vae_id = self._id(self.selected_id() if vae_id is None else vae_id)
            if vae_id == BUILTIN:
                return {"id": BUILTIN, "name": "原版 Heretic · MLX VAE", "format": "mflux",
                        "sha256": PIN["lfs"]["sha256"], "file_size": PIN["size"], "dtypes": ["F32"]}
            folder = self.directory / vae_id
            try:
                if folder.is_symlink():
                    raise ValueError("VAE 目录不可为符号链接")
                value = json.loads((folder / "manifest.json").read_text())
                if (value.get("schema_version") != 1 or value.get("id") != vae_id or value.get("sha256") != vae_id
                        or value.get("format") not in {"mflux", "diffusers"}
                        or set(value.get("verified_files", {})) != {"0.safetensors", "config.json"}
                        or value["verified_files"]["0.safetensors"].get("sha256") != vae_id):
                    raise ValueError("VAE 登记信息不完整")
                result = {**value, "path": str(folder)}
                validate_snapshot(result)
                return result
            except (OSError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"所选 VAE 不可用，请重新导入；未回退到原版：{exc}") from exc

    def status(self):
        self.import_directory.mkdir(parents=True, exist_ok=True)
        models, errors = [self.public(self.resolve(BUILTIN))], []
        for folder in sorted(self.directory.iterdir()):
            if re.fullmatch(r"[a-f0-9]{64}", folder.name):
                try:
                    models.append(self.public(self.resolve(folder.name)))
                except ValueError as exc:
                    errors.append(str(exc))
        try:
            selected = self.selected_id()
            self.resolve(selected)
        except ValueError as exc:
            selected = ""
            errors.append(str(exc))
        return {"models": models, "selected_id": selected, "errors": errors,
                "directory": str(self.directory), "import_directory": str(self.import_directory),
                "imports": [{"source_name": p.name, "file_size": p.stat().st_size}
                            for p in sorted(self.import_directory.iterdir())
                            if p.is_file() and not p.is_symlink() and p.suffix.lower() == ".safetensors"]}

    def import_file(self, source, name=""):
        if not isinstance(source, str) or not source.strip():
            raise ValueError("请选择 VAE 源文件")
        path = Path(source.strip()).expanduser()
        if not path.is_absolute():
            path = self.import_directory / path
            if not path.resolve().is_relative_to(self.import_directory.resolve()):
                raise ValueError("相对路径必须位于 VAE 导入目录")
        with self._lock:
            inspection = inspect_vae(path)
            config = self.shared / "vae/config.json"
            if not verify(config, size=CONFIG_PIN["size"], blob_id=CONFIG_PIN["blobId"]):
                raise ValueError("原版 Qwen 2.1 VAE 配置校验失败，请先恢复共享模型")
            self.directory.mkdir(parents=True, exist_ok=True)
            # Publish a verified private copy, never a mutable link to an import.
            with tempfile.TemporaryDirectory(prefix=".import-", dir=self.directory) as scratch:
                stage = Path(scratch) / "model"
                stage.mkdir()
                source_stat = path.stat()
                shutil.copyfile(path, stage / "0.safetensors")
                current_stat = path.stat()
                if (current_stat.st_size, current_stat.st_mtime_ns, current_stat.st_ino) != (source_stat.st_size, source_stat.st_mtime_ns, source_stat.st_ino):
                    raise ValueError("VAE 源文件在导入期间发生变化")
                if inspect_vae(stage / "0.safetensors") != inspection:
                    raise ValueError("VAE 源文件在导入期间发生变化")
                digest = sha256(stage / "0.safetensors")
                shutil.copyfile(config, stage / "config.json")
                if not verify(stage / "config.json", size=CONFIG_PIN["size"], blob_id=CONFIG_PIN["blobId"]):
                    raise ValueError("VAE 配置在导入期间发生变化")
                proofs = {p.name: {"size": p.stat().st_size, "mtime_ns": p.stat().st_mtime_ns,
                                    "sha256": sha256(p)} for p in stage.iterdir()}
                value = {"schema_version": 1, "id": digest, "sha256": digest, **inspection,
                         "name": re.sub(r"[\x00-\x1f/\\]", " ", str(name or path.stem)).strip()[:120] or "自定义 VAE",
                         "verified_files": proofs}
                (stage / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
                destination = self.directory / digest
                if not destination.exists():
                    os.replace(stage, destination)
                result = self.resolve(digest)
                validate_snapshot(result, checksum=True)
                return self.public(result)

    def select(self, vae_id):
        with self._lock:
            item = self.resolve(vae_id)
            validate_snapshot(item, checksum=True)
            self.directory.mkdir(parents=True, exist_ok=True)
            pending = self.selection_file.with_suffix(".json.tmp")
            pending.write_text(json.dumps({"id": item["id"]}) + "\n")
            os.replace(pending, self.selection_file)
            return self.public(item)
