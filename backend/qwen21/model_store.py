"""Qwen Base discovery, strict import inspection and atomic publication."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import time

from ..local_image.comfy_fp8 import inspect_comfy_scaled_fp8, read_safetensors_header
from ..local_image.safetensors import estimate_bf16_bytes, validate_bf16_safetensors
from .contracts import DEFAULT_MODEL_ID, EXPORT_FORMATS, MODEL_REPO, MODEL_REVISION, normalize_model_id
from .weight_schema import expected_shapes, match_header

MODEL_BYTES = 17_799_746_851
TRANSFORMER_BYTES = 7_655_273_899
BUILTIN_FILES = json.loads(Path(__file__).with_name("model_files.json").read_text())
OUTPUT_BYTES = {"8bit": TRANSFORMER_BYTES,
                "bf16": estimate_bf16_bytes({key: {"shape": shape} for key, shape in expected_shapes().items()})}


def clean_name(value):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f/\\]+", " ", str(value or ""))).strip()[:120] or "Qwen 2.1 模型"


def shared_model_file(name):
    """Pinned shared components plus the architecture config used by conversion."""
    return not name.startswith("transformer/") or name == "transformer/config.json"


class BaseModelStore:
    def __init__(self, assets_root, component):
        self.assets_root = Path(assets_root).resolve()
        self.component = Path(component).resolve()
        self.directory = self.assets_root / "base_models"
        self.staging = self.directory / ".staging"
        self.import_directory = self.assets_root.parent / "imports"

    @property
    def shared(self):
        return self.directory / DEFAULT_MODEL_ID

    def _selection(self):
        path = self.directory / ".selection.json"
        if not path.exists() and not path.is_symlink():
            return {"schema_version": 1, "builtin_transformer_removed": False,
                    "default_model_id": DEFAULT_MODEL_ID}
        try:
            if path.is_symlink():
                raise ValueError("selection is a symlink")
            value = json.loads(path.read_text())
            if (value.get("schema_version") != 1 or value.get("builtin_transformer_removed") is not True
                    or normalize_model_id(value.get("default_model_id")) == DEFAULT_MODEL_ID):
                raise ValueError("invalid selection")
            return value
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            # Never restore a removed multi-GB checkpoint after a corrupt receipt.
            raise RuntimeError("Qwen Base 选择记录无效，请检查 .selection.json") from exc

    @property
    def builtin_removed(self):
        return self._selection()["builtin_transformer_removed"]

    def selection(self):
        value = self._selection()
        return {"default_model_id": value["default_model_id"],
                "model_replacements": {DEFAULT_MODEL_ID: value["default_model_id"]}
                if value["builtin_transformer_removed"] else {}}

    def _write_selection(self, model_id):
        path = self.directory / ".selection.json"
        pending = self.directory / ".selection.json.tmp"
        with pending.open("w") as stream:
            json.dump({"schema_version": 1, "builtin_transformer_removed": True,
                       "default_model_id": model_id}, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        pending.replace(path)

    @staticmethod
    def _public(item):
        keys = ("id", "name", "label", "precision", "quantization", "group_size", "ready", "verified", "builtin", "file_size",
                "created_at", "reference_capable", "source_name", "source_format", "requantized", "verification")
        return {key: item[key] for key in keys if key in item}

    def _read(self, folder, *, shared_only=False):
        if folder.is_symlink() or not folder.is_dir():
            return None
        try:
            receipt = folder / ".shared-manifest.json"
            if not shared_only or not receipt.exists():
                receipt = folder / "manifest.json"
            value = json.loads(receipt.read_text())
            if (not isinstance(value, dict) or value.get("schema_version") != 1
                    or value.get("architecture") != "qwen-image-2.1"
                    or normalize_model_id(value.get("id")) != folder.name or value.get("precision") not in EXPORT_FORMATS):
                return None
            if shared_only and not value.get("builtin"):
                return None
            files = value.get("verified_files") or {}
            if not isinstance(files, dict) or not files:
                return None
            for name, proof in files.items():
                if (not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts
                        or not isinstance(proof, dict)):
                    return None
                if shared_only and not shared_model_file(name):
                    continue
                file = folder / name
                if file.is_symlink() or not file.is_file():
                    return None
                stat = file.stat()
                if stat.st_size != proof.get("size") or stat.st_mtime_ns != proof.get("mtime_ns"):
                    return None
            if value.get("builtin"):
                if (value.get("id") != DEFAULT_MODEL_ID or value.get("repo_revision") != MODEL_REVISION
                        or value.get("precision") != "8bit"):
                    return None
                if value.get("shared_only") and not shared_only:
                    return None
                # Full bases and shared components have separate pinned receipts;
                # deleting the builtin Transformer must not invalidate custom bases.
                expected = BUILTIN_FILES
                if value.get("shared_only"):
                    expected = [item for item in expected if shared_model_file(item["rfilename"])]
                if set(files) != {item["rfilename"] for item in expected}:
                    return None
                if any(files[item["rfilename"]].get("size") != item["size"] or
                       files[item["rfilename"]].get("sha256", "") != (item.get("lfs") or {}).get("sha256", "")
                       or files[item["rfilename"]].get("blob_id") != item.get("blobId") for item in expected):
                    return None
                ready = True
            else:
                proof = value.get("verification") or {}
                if not (proof.get("strict_load") is True and proof.get("strict_reload") is True
                        and value.get("quantized_linear_count") == EXPORT_FORMATS[value["precision"]]["quantized_linear_count"]
                        and "transformer/0.safetensors" in files):
                    return None
                if value["precision"] == "bf16":
                    if (value.get("source_tensor_count") != 297 or value.get("output_tensor_count") != 297
                            or value.get("group_size") is not None):
                        return None
                    validate_bf16_safetensors(folder / "transformer/0.safetensors", 297,
                                             metadata={"precision": "bf16", "quantization_level": "None"})
                ready = self._read(self.shared, shared_only=True) is not None
                for name in ("vae", "text_encoder", "processor"):
                    link = folder / name
                    if not link.is_symlink() or link.resolve() != (self.shared / name).resolve():
                        return None
            name = clean_name(value.get("name"))
            label = f"{name}（BF16）" if value["precision"] == "bf16" else name
            return {**value, "name": name, "label": label,
                    "ready": ready, "verified": True, "path": folder.resolve()}
        except (OSError, TypeError, ValueError, RecursionError):
            return None

    def list(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        builtin = self._read(self.shared) or {
            "id": DEFAULT_MODEL_ID, "name": "Qwen-Image-2.1-Heretic-mlx-8bit",
            "label": "Qwen-Image-2.1-Heretic-mlx-8bit", "builtin": True, "precision": "8bit",
            "ready": False, "verified": False, "reference_capable": True, "file_size": MODEL_BYTES}
        custom = [item for folder in sorted(self.directory.iterdir())
                  if not folder.name.startswith(".") and folder.name != DEFAULT_MODEL_ID
                  for item in [self._read(folder)] if item]
        return [self._public(item) for item in ([*custom] if self.builtin_removed else [builtin, *custom])]

    def resolve(self, model_id):
        model_id = normalize_model_id(model_id or self.selection()["default_model_id"])
        if model_id == DEFAULT_MODEL_ID and self.builtin_removed:
            raise ValueError("该 8-bit Base 已删除，请选择现有 Base 模型")
        item = self._read(self.directory / model_id)
        if not item:
            raise ValueError("Base 模型尚未准备或校验未通过")
        if not item["ready"]:
            raise RuntimeError("Qwen 共享文本/视觉编码器与 VAE 尚未准备")
        return item

    def paths(self):
        for directory in (self.directory, self.staging, self.import_directory):
            directory.mkdir(parents=True, exist_ok=True)
        return {"base_model_directory": str(self.directory), "import_directory": str(self.import_directory),
                "lora_directory": str(self.assets_root / "loras")}

    def list_imports(self):
        self.import_directory.mkdir(parents=True, exist_ok=True)
        return [{"source_name": file.name, "file_size": file.stat().st_size}
                for file in sorted(self.import_directory.iterdir(), key=lambda x: x.name.casefold())
                if not file.name.startswith(".") and file.is_file() and not file.is_symlink()
                and file.suffix.lower() == ".safetensors"]

    def inspect_source(self, raw):
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("请选择本地 .safetensors 文件")
        candidate = Path(raw.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = self.import_directory / candidate
            if not candidate.resolve().is_relative_to(self.import_directory.resolve()):
                raise ValueError("相对模型路径必须位于 Qwen 导入目录")
        if candidate.is_symlink() or not candidate.is_file() or candidate.suffix.lower() != ".safetensors":
            raise ValueError("仅支持本地普通 .safetensors 文件")
        header = read_safetensors_header(candidate)
        tensors = header.tensors
        if any("lora_" in key.lower() for key in tensors):
            raise ValueError("LoRA/差分文件不能作为 Base 转换")
        if any(key.endswith((".scales", ".biases")) for key in tensors):
            raise ValueError("已经是 MLX packed 权重，请选择原始模型")
        fp8 = inspect_comfy_scaled_fp8(header)
        if not fp8 and any(value["dtype"] not in {"F32", "F16", "BF16"} for value in tensors.values()):
            raise ValueError("仅支持 FP32/BF16/FP16 或 ComfyUI scaled-FP8 E4M3FN")
        prefix = match_header(tensors, allow_auxiliary=bool(fp8))
        source_format = fp8["source_format"] if fp8 else "float"
        return {"source_path": str(candidate.resolve()), "source_name": candidate.name,
                "suggested_name": clean_name(header.metadata.get("modelspec.title") or candidate.stem),
                "file_size": header.file_size, "kind": "comfy_scaled_fp8" if fp8 else "candidate",
                "source_format": source_format, "source_prefix": prefix,
                "tensor_count": len(tensors), "source_tensor_count": 297,
                "quantized_tensor_count": (fp8 or {}).get("quantized_tensor_count", 0),
                "compatible_candidate": True, "dtypes": sorted({x["dtype"] for x in tensors.values()}),
                "estimated_outputs": dict(OUTPUT_BYTES),
                "message": "Qwen 2.1 完整结构校验通过" + ("；将解码 FP8 后导出为所选精度" if fp8 else "")}

    def publish(self, stage, result, *, name, source_name, precision="8bit"):
        stage = Path(stage).resolve()
        if stage.parent != self.staging.resolve() or stage.is_symlink():
            raise RuntimeError("转换暂存目录无效")
        if precision not in EXPORT_FORMATS or result.get("precision", "8bit") != precision:
            raise RuntimeError("转换结果与请求的输出精度不一致")
        export = EXPORT_FORMATS[precision]
        if not (result.get("strict_reload") is True and result.get("strict_load") is True
                and result.get("quantized_linear_count") == export["quantized_linear_count"]
                and result.get("source_tensor_count") == 297):
            raise RuntimeError("转换结构验证记录无效")
        for key in ("source_sha256", "output_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(result.get(key) or "")):
                raise RuntimeError("转换校验值无效")
        transformer = stage / "transformer" / "0.safetensors"
        if transformer.is_symlink() or not transformer.is_file():
            raise RuntimeError("缺少转换结果文件")
        if precision == "bf16":
            if result.get("output_tensor_count") != 297:
                raise RuntimeError("BF16 Transformer 张量数量发生变化")
            validate_bf16_safetensors(transformer, 297,
                                     metadata={"precision": "bf16", "quantization_level": "None"})
        from ..local_image.downloads import sha256
        if sha256(transformer) != result["output_sha256"]:
            raise RuntimeError("转换结果校验失败")
        slug = re.sub(r"[^a-z0-9]+", "-", clean_name(name).lower()).strip("-")[:64] or "qwen21-model"
        model_id = normalize_model_id(f"{slug}-{result['source_sha256'][:12]}-{precision}")
        final = self.directory / model_id
        if final.exists():
            previous = self._read(final)
            if (previous and previous.get("source_sha256") == result["source_sha256"]
                    and previous.get("precision") == precision):
                shutil.rmtree(stage)
                return self._public(previous)
            raise RuntimeError("目标模型目录已存在，保留原模型")
        files = {}
        for file in stage.rglob("*"):
            if file.is_symlink():
                raise RuntimeError("转换输出不应含符号链接")
            if file.is_file():
                stat = file.stat()
                files[file.relative_to(stage).as_posix()] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        for component in ("vae", "text_encoder", "processor"):
            (stage / component).symlink_to(self.shared / component, target_is_directory=True)
        manifest = {"schema_version": 1, "id": model_id, "name": clean_name(name),
                    "architecture": "qwen-image-2.1", "precision": precision,
                    "group_size": export["group_size"], "quantization": export["label"],
                    "reference_capable": True, "builtin": False, "created_at": int(time.time()),
                    "source_name": Path(source_name).name, "source_sha256": result["source_sha256"],
                    "source_format": result["source_format"],
                    "requantized": precision != "bf16" and result["source_format"].startswith("comfy-scaled-fp8"),
                    "output_sha256": result["output_sha256"], "quantized_linear_count": result["quantized_linear_count"],
                    "source_tensor_count": result["source_tensor_count"],
                    "output_tensor_count": result.get("output_tensor_count"),
                    "verification": {"strict_load": True, "strict_reload": True}, "verified_files": files,
                    "file_size": transformer.stat().st_size,
                    "shared_components": {"repo": MODEL_REPO, "revision": MODEL_REVISION}}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        os.replace(stage, final)
        item = self._read(final)
        if not item:
            raise RuntimeError("转换结果注册验证失败")
        return self._public(item)

    def delete(self, model_id):
        model_id = normalize_model_id(model_id)
        if model_id == DEFAULT_MODEL_ID:
            replacements = sorted((item for item in self.list() if item["id"] != model_id and item.get("ready")),
                                  key=lambda item: (item["precision"] != "bf16", item["id"]))
            if not replacements:
                raise ValueError("请先准备可用的替代 Base，再删除内置 Transformer")
            item = self._read(self.shared, shared_only=True)
            if not item:
                raise ValueError("共享组件校验未通过，保留内置模型")
            # Publish retirement first: interrupted cleanup must not trigger a re-download.
            # The immutable pinned file list, not directory recursion, bounds deletion.
            weights = [self.shared / entry["rfilename"] for entry in BUILTIN_FILES
                       if entry["rfilename"].startswith("transformer/")
                       and entry["rfilename"].endswith(".safetensors")]
            if (self.shared / "transformer").is_symlink() or any(path.is_symlink() for path in weights):
                raise ValueError("内置 Transformer 路径无效，保留文件")
            self._write_selection(replacements[0]["id"])
            removed_bytes = 0
            for path in weights:
                if path.exists():
                    removed_bytes += path.stat().st_size
                    path.unlink()
            return {**self._public(item), "removed_bytes": removed_bytes, "shared_components_retained": True}
        item = self._read(self.directory / model_id)
        if not item:
            raise ValueError("Base 模型不存在或清单无效")
        if self.builtin_removed and self.selection()["default_model_id"] == model_id:
            replacements = [candidate for candidate in self.list() if candidate["id"] != model_id and candidate.get("ready")]
            if not replacements:
                raise ValueError("请保留至少一个可用 Base 模型")
            self._write_selection(replacements[0]["id"])
        shutil.rmtree(self.directory / model_id)
        return self._public(item)
