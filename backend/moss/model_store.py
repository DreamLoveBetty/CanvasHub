"""Read-only binding of a local MOSS checkpoint: whitelist, fingerprints and the worker's model view."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time

from ..local_image.comfy_fp8 import read_safetensors_header
from ..local_image.downloads import sha256
from .assets import load_lock
from .contracts import DEFAULT_MODEL_ID, normalize_model_id
from .lora_adapter import LAYER_COUNT, TARGET_SHAPES
from .native_adapter import BRIDGE_VERSION, PARTS, create_view

INDEX_NAME = "model.safetensors.index.json"
TOKENIZER_FILES = tuple(f"tokenizer/{name}" for name in ("tokenizer.json", "tokenizer_config.json",
                                                         "chat_template.jinja"))
STUDENT_LOCATIONS = ("lora/turbo_student.safetensors", "turbo_student.safetensors")
DEFAULT_LABEL = "MOSS Image SFT · BF16"


@dataclass(frozen=True)
class ResolvedModel:
    model_id: str
    view_path: Path
    student_path: Path
    destripe_path: Path
    fingerprint: str


def whitelist(lock=None):
    """Relative files a binding depends on; anything else may change freely."""
    weights = sorted((lock or load_lock())["base_model"]["files"])
    return [*weights, *(f"{part}/{INDEX_NAME}" for part in PARTS), *TOKENIZER_FILES]


def _stamp(path):
    stat = path.stat()
    return {"size": stat.st_size, "modified_ns": stat.st_mtime_ns}


def _check_schema(name, tensors):
    if not name.startswith("transformer/"):
        return
    for key, tensor in tensors.items():
        parts = key.split(".")
        if len(parts) == 5 and parts[0] == "layers" and parts[2] == "proj" and parts[4] == "weight":
            expected = TARGET_SHAPES.get(parts[3])
            if int(parts[1]) >= LAYER_COUNT or (expected and tuple(tensor["shape"]) != expected):
                raise ValueError(f"MOSS 张量 shape 错误：{key}")


def _transformer_tensors(directory):
    """Header map under upstream names, which is what the sampler loads whichever spelling a checkpoint uses."""
    tensors = {}
    for path in sorted(directory.glob("*.safetensors")):
        for key, tensor in read_safetensors_header(path).tensors.items():
            tensors[key.replace("time_embedding.2.", "time_embedding.1.")] = (tuple(tensor["shape"]), tensor["dtype"])
    return tensors


def _check_part(source, part, names):
    """Every shard's tensors must match that part's index exactly, with no duplicates."""
    try:
        mapping = json.loads((source / part / INDEX_NAME).read_text(encoding="utf-8"))["weight_map"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"MOSS 索引无效：{part}") from error
    if not isinstance(mapping, dict):
        raise ValueError(f"MOSS 索引无效：{part}")
    seen = {}
    for name in names:
        tensors = read_safetensors_header(source / name).tensors
        _check_schema(name, tensors)
        for key in tensors:
            if key in seen:
                raise ValueError(f"MOSS 分片包含重复张量：{key}")
            seen[key] = Path(name).name
    if seen != mapping:
        raise ValueError(f"MOSS 分片与索引不一致：{part}")


class ModelStore:
    def __init__(self, root, assets_dir, *, lock=None):
        self.root = Path(root)
        self.assets_dir = Path(assets_dir)
        self.lock = lock or load_lock()
        self._guard = threading.RLock()

    def _directory(self, model_id):
        return self.root / "models" / normalize_model_id(model_id)

    def _binding_path(self, model_id):
        return self._directory(model_id) / "binding.json"

    def _read(self, model_id):
        try:
            value = json.loads(self._binding_path(model_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _verified_hash(self, path, expected):
        if path.stat().st_size != expected["size"] or sha256(path) != expected["sha256"]:
            raise ValueError(f"MOSS 文件与锁定版本不一致：{path.name}")
        return expected["sha256"]

    def _find_student(self, source):
        expected = self.lock["managed"]["student"]
        found = [source / name for name in STUDENT_LOCATIONS if (source / name).is_file()]
        if len({sha256(path) for path in found}) > 1:
            raise ValueError("源目录存在两个不同的 Turbo student")
        fallback = self.assets_dir / expected["file"]
        path = found[0] if found else fallback
        if not path.is_file():
            raise ValueError("缺少 Turbo student，请先运行 MOSS 准备")
        self._verified_hash(path, expected)
        return path

    def _managed_inputs(self):
        """Files prepared into assets_dir, checked against the lock."""
        hashes = {}
        for name, expected in self.lock["configs"]["files"].items():
            path = self.assets_dir / "configs" / name
            if not path.is_file():
                raise ValueError("缺少 MOSS 配置文件，请先运行准备")
            hashes[f"configs/{name}"] = self._verified_hash(path, expected)
        destripe = self.assets_dir / Path(self.lock["managed"]["destripe"]["file"]).name
        if not destripe.is_file():
            raise ValueError("缺少 destripe 适配器，请先运行 MOSS 准备")
        self._verified_hash(destripe, self.lock["managed"]["destripe"])
        return hashes, destripe

    def _write_binding(self, model_id, value):
        directory = self._directory(model_id)
        with tempfile.NamedTemporaryFile("w", dir=directory, suffix=".tmp", delete=False, encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(stream.name, self._binding_path(model_id))

    def bind(self, source_path, model_id=DEFAULT_MODEL_ID):
        """Full verification; reads the source and writes only under the store root."""
        model_id = normalize_model_id(model_id)
        if model_id != self.lock["base_model"]["id"]:
            raise ValueError("未知 MOSS Base 模型")
        source = Path(source_path).expanduser()
        if not source.is_absolute() or not source.is_dir():
            raise ValueError("MOSS 源目录必须是已存在的绝对路径")
        source = source.resolve()
        root = self.root.resolve()
        if source == root or source in root.parents:
            raise ValueError("MOSS 状态目录不能位于源权重目录内")
        files = whitelist(self.lock)
        missing = [name for name in files if not (source / name).is_file()]
        if missing:
            raise ValueError(f"MOSS 源目录缺少文件：{missing[0]}")
        weights = self.lock["base_model"]["files"]
        for part in PARTS:
            _check_part(source, part, [name for name in weights if name.startswith(part + "/")])
        hashes = {name: self._verified_hash(source / name, weights[name]) if name in weights else sha256(source / name)
                  for name in files}
        student = self._find_student(source)
        managed, destripe = self._managed_inputs()
        with self._guard:
            directory = self._directory(model_id)
            directory.mkdir(parents=True, exist_ok=True)
            view = directory / "view"
            shutil.rmtree(view, ignore_errors=True)
            create_view(source, self.assets_dir / "configs", view, files)
            payload = {"bridge": BRIDGE_VERSION, "files": hashes, "managed": managed,
                       "student": self.lock["managed"]["student"]["sha256"],
                       "destripe": self.lock["managed"]["destripe"]["sha256"]}
            fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            binding = {"schema_version": 1, "model_id": model_id, "source_path": str(source),
                       "fingerprint": fingerprint, "bridge": BRIDGE_VERSION, "bound_at": int(time.time()),
                       "files": {name: {**_stamp(source / name), "sha256": hashes[name]} for name in files},
                       "student_path": str(student), "student": _stamp(student),
                       "destripe_path": str(destripe), "destripe": _stamp(destripe),
                       "configs": {part: _stamp(view / part / "config.json") for part in PARTS}}
            self._write_binding(model_id, binding)
        return self.public(model_id)

    def healthy_binding(self, model_id):
        binding = self._read(model_id)
        return binding if binding and not self._invalid_reason(binding) else None

    def forget(self, model_id):
        shutil.rmtree(self._directory(model_id), ignore_errors=True)

    def bind_variant(self, source_path, model_id, label):
        """Bind a transformer-only fine-tune; encoder, tokenizer, VAE and adapters stay those of the official base."""
        source = Path(source_path).expanduser()
        if not source.is_absolute() or not source.is_dir():
            raise ValueError("MOSS 源目录必须是已存在的绝对路径")
        source = source.resolve()
        root = self.root.resolve()
        if source == root or source in root.parents:
            raise ValueError("MOSS 状态目录不能位于源权重目录内")
        parent = self.healthy_binding(DEFAULT_MODEL_ID)
        if not parent:
            raise ValueError("请先绑定官方 MOSS 权重，微调 Base 需要复用其文本编码器与 VAE")
        names = sorted(f"transformer/{path.name}" for path in (source / "transformer").glob("*.safetensors"))
        if not names or not (source / "transformer" / INDEX_NAME).is_file():
            raise ValueError("MOSS 微调目录缺少 transformer 分片或索引")
        _check_part(source, "transformer", names)
        parent_source = Path(parent["source_path"])
        if _transformer_tensors(source / "transformer") != _transformer_tensors(parent_source / "transformer"):
            raise ValueError("MOSS 微调的张量名称、形状或精度与官方权重不一致")
        model_id = normalize_model_id(model_id)
        shared = {name: stamp for name, stamp in parent["files"].items() if not name.startswith("transformer/")}
        own = [*names, f"transformer/{INDEX_NAME}"]
        hashes = {name: sha256(source / name) for name in own}
        links = {**{name: str(parent_source / name) for name in shared}, **{name: str(source / name) for name in own}}
        with self._guard:
            directory = self._directory(model_id)
            directory.mkdir(parents=True, exist_ok=True)
            view = directory / "view"
            shutil.rmtree(view, ignore_errors=True)
            create_view(source, self.assets_dir / "configs", view, list(links), links)
            payload = {"bridge": BRIDGE_VERSION, "parent": parent["fingerprint"], "files": hashes}
            binding = {"schema_version": 1, "model_id": model_id, "label": label, "parent": DEFAULT_MODEL_ID,
                       "source_path": str(source), "sources": links,
                       "fingerprint": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
                       "bridge": BRIDGE_VERSION, "bound_at": int(time.time()),
                       "files": {**shared, **{name: {**_stamp(source / name), "sha256": hashes[name]} for name in own}},
                       **{key: parent[key] for key in ("student_path", "student", "destripe_path", "destripe")},
                       "configs": {part: _stamp(view / part / "config.json") for part in PARTS}}
            self._write_binding(model_id, binding)
        return self.public(model_id)

    def _invalid_reason(self, binding):
        if binding.get("bridge") != BRIDGE_VERSION:
            return "桥接版本已变化，请重新绑定"
        origin = lambda name: Path(binding.get("sources", {}).get(name) or Path(binding["source_path"]) / name)
        view = self._directory(binding["model_id"]) / "view"
        checks = [(origin(name), stamp, name) for name, stamp in binding["files"].items()]
        checks += [(Path(binding["student_path"]), binding["student"], "student"),
                   (Path(binding["destripe_path"]), binding["destripe"], "destripe")]
        checks += [(view / part / "config.json", stamp, f"{part}/config.json")
                   for part, stamp in binding["configs"].items()]
        for path, stamp, name in checks:
            try:
                current = _stamp(path)
            except OSError:
                return f"绑定文件丢失：{name}"
            if any(current[key] != stamp[key] for key in current):
                return f"绑定文件已变化：{name}"
        for name in binding["files"]:
            link = view / name
            if name.endswith(INDEX_NAME):
                continue
            if not link.is_symlink() or Path(os.readlink(link)) != origin(name):
                return f"模型视图已变化：{name}"
        return None

    def resolve(self, model_id=DEFAULT_MODEL_ID):
        """Cheap per-job check of the receipt, files and view links."""
        binding = self._read(model_id)
        if not binding:
            raise ValueError("MOSS 模型尚未绑定")
        reason = self._invalid_reason(binding)
        if reason:
            raise ValueError(f"MOSS 绑定已失效：{reason}")
        return ResolvedModel(binding["model_id"], self._directory(model_id) / "view", Path(binding["student_path"]),
                             Path(binding["destripe_path"]), binding["fingerprint"])

    def public(self, model_id=DEFAULT_MODEL_ID):
        """Frontend-safe state: never carries local paths."""
        binding = self._read(model_id)
        if not binding:
            return {"model_id": model_id, "label": model_id, "ready": False, "reason": "尚未绑定", "fingerprint": None,
                    "bound_at": None}
        reason = self._invalid_reason(binding)
        return {"model_id": model_id, "label": binding.get("label", DEFAULT_LABEL), "ready": reason is None,
                "reason": reason, "fingerprint": binding["fingerprint"], "bound_at": binding["bound_at"]}

    def list(self):
        """The official base first, then every bound fine-tune."""
        others = sorted(path.parent.name for path in (self.root / "models").glob("*/binding.json")
                        if path.parent.name != DEFAULT_MODEL_ID)
        return [self.public(model_id) for model_id in (DEFAULT_MODEL_ID, *others)]
