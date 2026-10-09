"""Managed Krea 2 transformer catalog and safe local checkpoint inspection.

The official VAE/text encoder remain shared component cache entries.  This store
owns only selectable transformer builds produced by the offline converter.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from .comfy_fp8 import (ComfyFP8Error, MAX_CHECKPOINT_BYTES, MAX_HEADER_BYTES,
                        inspect_comfy_scaled_fp8, read_safetensors_header)
from .contracts import (BUILDS, BUILTIN_MODEL_IDS, DEFAULT_MODEL_ID, EXPORT_FORMATS,
                        normalize_model_id)
from .environment import model_paths
from ..local_image.safetensors import estimate_bf16_bytes, validate_bf16_safetensors


SCHEMA_VERSION = 1
TRANSFORMER_FILENAME = "transformer.safetensors"
SUPPORTED_SOURCE_DTYPES = frozenset({"BF16", "F16", "F32"})


def _sha256(path, callback=None):
    digest = hashlib.sha256()
    total = path.stat().st_size
    done = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(chunk)
            done += len(chunk)
            if callback:
                callback(done, total)
    return digest.hexdigest()


def _clean_name(value, fallback="Krea 2 模型"):
    name = re.sub(r"[\x00-\x1f/\\]+", " ", str(value or ""))
    name = re.sub(r"\s+", " ", name).strip()
    return name[:120] or fallback


def _slug(value):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text[:64].strip("-") or "krea2-model")


class BaseModelStore:
    def __init__(self, assets_root, component):
        self.assets_root = Path(assets_root).resolve()
        self.component = Path(component).resolve()
        self.directory = self.assets_root / "base_models"
        self.staging = self.directory / ".staging"
        self.import_directory = self.assets_root.parent / "imports"

    @staticmethod
    def builtin_id(precision):
        return BUILTIN_MODEL_IDS[str(precision)]

    @staticmethod
    def _public(item):
        fields = ("id", "name", "label", "precision", "quantization", "group_size",
                  "file_size", "created_at", "verified", "ready", "builtin",
                  "source_name", "source_sha256", "source_format", "requantized",
                  "source_quantized_tensor_count", "output_sha256", "verification")
        return {key: item[key] for key in fields if key in item}

    def _builtin(self, precision, ready=None):
        build = BUILDS[precision]
        path = model_paths(self.component)[precision]
        if ready is None:
            try:
                ready = path.is_file() and path.stat().st_size == build["size"]
            except OSError:
                ready = False
        variant = "8-bit" if precision == "8bit" else "Mixed 4/8-bit"
        return {
            "id": BUILTIN_MODEL_IDS[precision],
            "name": "Krea 2 Turbo · Alis MLX",
            "label": f"Krea 2 Turbo · Alis MLX（{variant}）",
            "precision": precision,
            "quantization": variant,
            "group_size": 64,
            "file_size": build["size"],
            "verified": bool(ready),
            "ready": bool(ready),
            "builtin": True,
            "source_name": "krea/Krea-2-Turbo",
            "path": path,
        }

    def _read_manifest(self, folder):
        if folder.is_symlink() or not folder.is_dir():
            return None
        try:
            value = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
                return None
            model_id = normalize_model_id(value.get("id"))
            if model_id != folder.name or value.get("precision") not in EXPORT_FORMATS:
                return None
            transformer = folder / TRANSFORMER_FILENAME
            if transformer.is_symlink() or not transformer.is_file():
                return None
            stat = transformer.stat()
            if int(value.get("file_size") or -1) != stat.st_size:
                return None
            verification = value.get("verification") or {}
            if not isinstance(verification, dict) or verification.get("strict_reload") is not True:
                return None
            if value["precision"] == "bf16":
                count = value.get("source_tensor_count", 0)
                if (verification.get("strict_load") is not True or value.get("quantized_linear_count") != 0
                        or value.get("output_tensor_count") != count or value.get("group_size") is not None
                        or value.get("file_mtime_ns") != stat.st_mtime_ns):
                    return None
                validate_bf16_safetensors(transformer, count, metadata={"precision": "bf16"})
            return {
                **value,
                "id": model_id,
                "name": _clean_name(value.get("name")),
                "label": _clean_name(value.get("label") or value.get("name")),
                "ready": True,
                "verified": True,
                "builtin": False,
                "path": transformer.resolve(),
            }
        except (OSError, ValueError, TypeError):
            return None

    def _custom(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        result = []
        for folder in sorted(self.directory.iterdir(), key=lambda item: item.name.casefold()):
            if folder.name.startswith("."):
                continue
            item = self._read_manifest(folder)
            if item:
                result.append(item)
        return result

    def list(self, build_status=None):
        build_status = build_status or {}
        builtins = []
        for precision in BUILDS:
            status = build_status.get(precision) if isinstance(build_status, dict) else None
            ready = status.get("ready") if isinstance(status, dict) else None
            item = self._builtin(precision, ready)
            # The optional mixed build is not an installed model until ready.
            # Keep the default 8-bit entry for first-run preparation, and keep
            # mixed export/loading support for models actually installed later.
            if precision == "mixed-4-8" and not item["ready"]:
                continue
            builtins.append(item)
        custom = sorted(self._custom(), key=lambda item: (-int(item.get("created_at") or 0),
                                                          item.get("name", "")))
        return [self._public(item) for item in (*builtins, *custom)]

    def resolve(self, model_id):
        model_id = normalize_model_id(model_id or DEFAULT_MODEL_ID)
        for precision, builtin_id in BUILTIN_MODEL_IDS.items():
            if model_id == builtin_id:
                item = self._builtin(precision)
                if not item["ready"]:
                    raise RuntimeError(f"{item['label']} 尚未准备")
                return item
        folder = self.directory / model_id
        item = self._read_manifest(folder)
        if not item:
            raise ValueError("Base 权重模型不存在或尚未验证")
        return item

    def inspect_source(self, source_path):
        raw = str(source_path or "").strip()
        if not raw:
            raise ValueError("请选择或填写本地 .safetensors 模型路径")
        candidate = Path(raw).expanduser()
        relative_input = not candidate.is_absolute()
        if relative_input:
            candidate = self.import_directory / candidate
            normalized = candidate.resolve(strict=False)
            if not normalized.is_relative_to(self.import_directory.resolve(strict=False)):
                raise ValueError("相对模型路径必须位于模型导入目录内")
        if candidate.is_symlink():
            raise ValueError("模型来源不能是符号链接")
        try:
            path = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError("模型文件不存在") from exc
        if path.is_dir():
            raise ValueError("当前选择的是目录，请选择目录内具体的 .safetensors 文件")
        if not path.is_file():
            raise ValueError("模型路径不是可读取的普通文件")
        if path.suffix.lower() != ".safetensors":
            raise ValueError("源模型必须是 .safetensors 文件")
        checkpoint = read_safetensors_header(
            path,
            max_checkpoint_bytes=MAX_CHECKPOINT_BYTES,
            max_header_bytes=MAX_HEADER_BYTES,
        )
        tensors = checkpoint.tensors
        metadata = {
            str(key): str(value)[:512]
            for key, value in checkpoint.metadata.items()
        }
        keys = tuple(tensors)
        lower = tuple(key.lower() for key in keys)
        dtypes = sorted({item["dtype"].upper() for item in tensors.values()})
        unsupported_dtypes = sorted(set(dtypes) - SUPPORTED_SOURCE_DTYPES)
        lora_count = sum("lora_a.weight" in key or "lora_down.weight" in key for key in lower)
        quantized = any(key.endswith(".scales") or key.endswith(".biases") for key in keys)
        signatures = ("blocks.0.", "transformer.blocks.0.", "model.diffusion_model.blocks.0.",
                      "diffusion_model.blocks.0.", "base_model.model.blocks.0.")
        architecture_candidate = any(any(key.startswith(prefix) for key in keys)
                                     for prefix in signatures)
        comfy_fp8 = None
        comfy_fp8_error = ""
        try:
            comfy_fp8 = inspect_comfy_scaled_fp8(checkpoint)
        except ComfyFP8Error as exc:
            comfy_fp8_error = str(exc)
        if lora_count:
            kind, message = "lora", "检测到 LoRA/差分权重，不能作为 Base 模型转换"
        elif quantized:
            kind, message = "quantized", "检测到已量化权重，请使用原始 FP32/BF16/FP16 模型"
        elif comfy_fp8_error:
            kind, message = "unsupported", comfy_fp8_error
        elif comfy_fp8:
            kind = "comfy_scaled_fp8"
            message = "检测到 ComfyUI scaled-FP8 E4M3FN 完整权重，可解码后导出为所选精度"
        elif unsupported_dtypes:
            kind = "unsupported"
            message = ("检测到不支持的数据类型：" + " / ".join(unsupported_dtypes)
                       + "；仅支持 FP32/BF16/FP16 完整权重")
        elif architecture_candidate and len(keys) >= 100:
            kind, message = "candidate", "文件头符合 Krea 2 完整 Transformer 候选特征"
        else:
            kind, message = "unknown", "无法仅凭文件头确认兼容性；开始转换后将执行严格结构检查"
        name = next((_clean_name(metadata.get(key), "") for key in
                     ("model_name", "modelspec.title", "name", "title") if metadata.get(key)), "")
        if not name:
            name = _clean_name(path.stem)
        stat = path.stat()
        result = {
            "source_path": str(path),
            "source_name": path.name,
            "suggested_name": name,
            "file_size": stat.st_size,
            "tensor_count": len(tensors),
            "dtypes": dtypes,
            "kind": kind,
            "compatible_candidate": kind in {"candidate", "unknown", "comfy_scaled_fp8"},
            "message": message,
            "metadata": metadata,
            "estimated_outputs": {**{key: build["size"] for key, build in BUILDS.items()},
                                  "bf16": estimate_bf16_bytes(tensors)},
        }
        if comfy_fp8:
            result.update({
                "source_format": comfy_fp8["source_format"],
                "source_tensor_count": comfy_fp8["source_tensor_count"],
                "quantized_tensor_count": comfy_fp8["quantized_tensor_count"],
            })
        return result

    def list_imports(self):
        """List direct safetensors children without exposing server-side paths."""
        self.import_directory.mkdir(parents=True, exist_ok=True)
        result = []
        for path in sorted(self.import_directory.iterdir(), key=lambda item: item.name.casefold()):
            if path.name.startswith(".") or path.is_symlink() or path.suffix.lower() != ".safetensors":
                continue
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
            except OSError:
                continue
            result.append({"source_name": path.name, "file_size": stat.st_size})
        return result

    def publish(self, stage, *, name, precision, source_name, source_sha256,
                output_sha256, source_prefix, source_tensor_count,
                output_tensor_count, quantized_linear_count,
                source_format="float", source_quantized_tensor_count=0):
        stage = Path(stage).resolve()
        transformer = stage / TRANSFORMER_FILENAME
        if stage.parent != self.staging.resolve() or transformer.is_symlink() or not transformer.is_file():
            raise RuntimeError("转换暂存结果无效")
        precision = str(precision)
        if precision not in EXPORT_FORMATS:
            raise ValueError("未知输出精度")
        export = EXPORT_FORMATS[precision]
        source_tensor_count = int(source_tensor_count)
        source_quantized_tensor_count = int(source_quantized_tensor_count or 0)
        output_tensor_count = int(output_tensor_count)
        quantized_linear_count = int(quantized_linear_count)
        if (source_tensor_count <= 0 or output_tensor_count <= 0
                or quantized_linear_count != export["quantized_linear_count"]):
            raise RuntimeError("转换后的结构验证记录无效")
        if precision == "bf16":
            if output_tensor_count != source_tensor_count:
                raise RuntimeError("BF16 Transformer 张量数量发生变化")
            validate_bf16_safetensors(transformer, source_tensor_count, metadata={"precision": "bf16"})
        name = _clean_name(name)
        recipe = export["recipe"]
        variant = export["label"]
        model_id = normalize_model_id(
            f"{_slug(name)}-{source_sha256[:12]}-{precision}"[:128].rstrip("-"))
        final = self.directory / model_id
        if final.exists():
            existing = self._read_manifest(final)
            if (existing and existing.get("source_sha256") == source_sha256
                    and existing.get("precision") == precision):
                shutil.rmtree(stage, ignore_errors=True)
                return self._public(existing)
            raise RuntimeError("模型目录已存在且内容不同")
        stat = transformer.stat()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "id": model_id,
            "name": name,
            "label": f"{name}（{variant}）",
            "architecture": "krea2-single-stream-dit-v1",
            "precision": precision,
            "quantization": variant,
            "recipe": recipe,
            "group_size": export["group_size"],
            "file": TRANSFORMER_FILENAME,
            "file_size": stat.st_size,
            "file_mtime_ns": stat.st_mtime_ns,
            "created_at": int(time.time()),
            "source_name": Path(str(source_name)).name,
            "source_sha256": str(source_sha256),
            "source_format": str(source_format or "float"),
            "source_quantized_tensor_count": source_quantized_tensor_count,
            "requantized": precision != "bf16" and str(source_format or "").startswith("comfy-scaled-fp8"),
            "output_sha256": str(output_sha256),
            "source_prefix": str(source_prefix),
            "source_tensor_count": source_tensor_count,
            "output_tensor_count": output_tensor_count,
            "quantized_linear_count": quantized_linear_count,
            "verification": {"strict_load": True, "strict_reload": True},
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.directory.mkdir(parents=True, exist_ok=True)
        os.replace(stage, final)
        item = self._read_manifest(final)
        if not item:
            raise RuntimeError("转换后的模型清单验证失败")
        return self._public(item)

    def delete(self, model_id):
        model_id = normalize_model_id(model_id)
        if model_id in BUILTIN_MODEL_IDS.values():
            raise ValueError("内置模型不能从模型工具中删除")
        folder = self.directory / model_id
        item = self._read_manifest(folder)
        if not item:
            raise ValueError("Base 权重模型不存在")
        shutil.rmtree(folder)
        return self._public(item)

    def paths(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.import_directory.mkdir(parents=True, exist_ok=True)
        return {"base_model_directory": str(self.directory),
                "import_directory": str(self.import_directory)}


__all__ = ["BaseModelStore", "TRANSFORMER_FILENAME", "_sha256"]
