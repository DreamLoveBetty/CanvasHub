"""Community MOSS Bases owned by the project: import folder, compatibility inspection, publishing and removal."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import shutil

from .contracts import DEFAULT_MODEL_ID, normalize_model_id
from .model_store import INDEX_NAME, _check_part, _transformer_tensors

SAFETY_BYTES = 2 * 1024**3
OUTPUT_BYTES = 11 * 1024**3


def clean_name(value):
    return re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f/\\]+", " ", str(value or ""))).strip()[:120]


def model_id_for(name):
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-._")[:100]
    return normalize_model_id(slug or "moss-" + hashlib.sha256(name.encode()).hexdigest()[:12])


class BaseLibrary:
    def __init__(self, root, models):
        self.root, self.models = Path(root), models
        self.import_directory = self.root / "base-imports"
        self.directory = self.root / "bases"
        self.staging = self.directory / ".staging"

    def paths(self):
        for directory in (self.import_directory, self.directory, self.staging):
            directory.mkdir(parents=True, exist_ok=True)
        return {"base_model_directory": str(self.directory), "import_directory": str(self.import_directory)}

    @staticmethod
    def _is_source(path):
        if path.name.startswith(".") or path.is_symlink():
            return False
        return (path.is_file() and path.suffix.lower() == ".safetensors") or (
            path.is_dir() and (path / "transformer" / INDEX_NAME).is_file())

    def list_imports(self):
        self.paths()
        items = []
        for path in sorted(self.import_directory.iterdir(), key=lambda item: item.name.casefold()):
            if self._is_source(path):
                files = path.rglob("*.safetensors") if path.is_dir() else [path]
                items.append({"source_name": path.name, "file_size": sum(file.stat().st_size for file in files)})
        return items

    def reference(self):
        """The official transformer every fine-tune must match; its binding also supplies the other parts."""
        binding = self.models.healthy_binding(DEFAULT_MODEL_ID)
        if not binding:
            raise ValueError("请先绑定官方 MOSS 权重，微调 Base 需要复用其文本编码器与 VAE")
        return Path(binding["source_path"]) / "transformer"

    def _source(self, name):
        self.paths()
        path = self.import_directory / str(name or "")
        if path.parent != self.import_directory or not self._is_source(path):
            raise ValueError("请选择导入目录内的 .safetensors 文件或已转换的模型目录")
        return path

    def inspect(self, name):
        from . import base_converter

        path, reference = self._source(name), self.reference()
        result = {"source_name": path.name, "source_path": str(path), "suggested_name": path.stem if path.is_file()
                  else path.name, "compatible_candidate": True, "message": "检查通过，可以开始转换"}
        try:
            if path.is_dir():
                names = [f"transformer/{file.name}" for file in (path / "transformer").glob("*.safetensors")]
                _check_part(path, "transformer", names)
                if _transformer_tensors(path / "transformer") != _transformer_tensors(reference):
                    raise ValueError("张量名称、形状或精度与官方权重不一致")
                result.update(source_format="mlx-bf16", tensor_count=len(_transformer_tensors(path / "transformer")))
            else:
                reader, scales, plans = base_converter.prepare(path, reference)
                result.update(source_format="comfy-int8-convrot" if scales else "bf16", tensor_count=len(reader.tensors),
                              dtypes=sorted({entry["dtype"] for entry in reader.tensors.values()}))
                del plans
        except (ValueError, KeyError, TypeError, OSError) as error:
            result.update(compatible_candidate=False, message=f"不是兼容的 MOSS Transformer：{error}"[:400])
        return result

    def require_space(self):
        self.paths()
        if shutil.disk_usage(self.directory).free < OUTPUT_BYTES + SAFETY_BYTES:
            raise RuntimeError("MOSS Base 目录空间不足，至少需要约 13 GiB")

    def publish(self, stage, name):
        """Move a verified stage into the library, then bind it; a failed bind leaves nothing behind."""
        model_id = model_id_for(name)
        if model_id == DEFAULT_MODEL_ID:
            raise ValueError("名称与官方 Base 冲突")
        target = self.directory / model_id
        if target.exists():
            raise ValueError("同名 Base 已存在，请换一个名称或先删除")
        Path(stage).rename(target)
        try:
            return self.models.bind_variant(target, model_id, name)
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def delete(self, model_id):
        if normalize_model_id(model_id) == DEFAULT_MODEL_ID:
            raise ValueError("官方 Base 不能删除")
        self.models.forget(model_id)
        shutil.rmtree(self.directory / model_id, ignore_errors=True)
