"""Byte-level normalization of ordinary MOSS LoRA files. Never imports MLX or changes tensor values."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile

from ..local_image.comfy_fp8 import read_safetensors_header
from .contracts import normalize_asset_id

CONVERTER_VERSION = "moss-lora-keys-v1"
LAYER_COUNT = 42
# (output, input) of each adapted Linear; "qkv" exists only in fused LoRA files.
TARGET_SHAPES = {"q": (3072, 3072), "k": (3072, 3072), "v": (3072, 3072), "o": (3072, 3072),
                 "ffn_up_gate": (16384, 3072), "ffn_down": (3072, 8192), "qkv": (9216, 3072)}
DTYPE_BYTES = {"F32": 4, "F16": 2, "BF16": 2}
_PREFIXES = ("model.diffusion_model.", "diffusion_model.", "transformer.")
_SUFFIXES = ((".lora_A.default.weight", "down"), (".lora_B.default.weight", "up"),
             (".lora_A.weight", "down"), (".lora_B.weight", "up"),
             (".lora_down.weight", "down"), (".lora_up.weight", "up"), (".alpha", "alpha"))
_LAYER = r"(0|[1-9]\d?)"
_MODULE = "qkv|q|k|v|o|ffn_up_gate|ffn_down"
_DOTTED = re.compile(rf"layers\.{_LAYER}\.proj\.({_MODULE})")
_FLAT = re.compile(rf"layers_{_LAYER}_proj_({_MODULE})")


@dataclass(frozen=True)
class _Slice:
    """One output tensor, as a byte range of the source file."""
    dtype: str
    shape: tuple
    start: int
    length: int


def _canonical_module(layer, module):
    return f"diffusion_model.layers.{layer}.proj.{module}"


def _output_key(module, side):
    return module + (".alpha" if side == "alpha" else f".lora_{side}.weight")


def parse_key(key):
    """Map one source tensor name to (layer, module, side); anything unrecognized raises."""
    name = key.removeprefix("base_model.model.")
    flat = name.startswith("lora_unet_")
    name = name.removeprefix("lora_unet_")
    if not flat:
        for prefix in _PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                break
    for suffix, side in _SUFFIXES:
        if name.endswith(suffix):
            match = (_FLAT if flat else _DOTTED).fullmatch(name[:-len(suffix)])
            if match and int(match[1]) < LAYER_COUNT:
                return int(match[1]), match[2], side
            break
    raise ValueError(f"LoRA 包含 MOSS 不支持的张量：{key}")


def _alpha_value(stream, dtype, offset):
    stream.seek(offset)
    raw = stream.read(DTYPE_BYTES[dtype])
    if len(raw) != DTYPE_BYTES[dtype]:
        raise ValueError("LoRA alpha 数据不完整")
    if dtype == "BF16":  # bfloat16 is the top half of a float32.
        return struct.unpack("<f", b"\0\0" + raw)[0]
    return struct.unpack("<f" if dtype == "F32" else "<e", raw)[0]


def _collect(header):
    """Group a header by (layer, module) and check every tensor against the fixed schema."""
    groups = {}
    for key, tensor in header.tensors.items():
        layer, module, side = parse_key(key)
        dtype, shape = tensor["dtype"], tuple(tensor["shape"])
        if dtype not in DTYPE_BYTES:
            raise ValueError("MOSS LoRA 必须为 FP32、FP16 或 BF16")
        start, end = tensor["data_offsets"]
        if end - start != math.prod(shape) * DTYPE_BYTES[dtype]:
            raise ValueError(f"LoRA 张量大小与 shape 不符：{key}")
        pair = groups.setdefault((layer, module), {})
        if side in pair:
            raise ValueError(f"LoRA 包含重复目标层：layers.{layer}.proj.{module}")
        pair[side] = _Slice(dtype, shape, header.payload_offset + start, end - start)
    return groups


def _validate_group(stream, layer, module, pair):
    label = f"layers.{layer}.proj.{module}"
    down, up, alpha = pair.get("down"), pair.get("up"), pair.get("alpha")
    if not down or not up:
        raise ValueError(f"LoRA 缺少 A/B 权重：{label}")
    if len(down.shape) != 2 or len(up.shape) != 2 or not down.shape[0] or down.shape[0] != up.shape[1]:
        raise ValueError(f"LoRA A/B 秩不一致：{label}")
    output, width = TARGET_SHAPES[module]
    if down.shape[1] != width or up.shape[0] != output:
        raise ValueError(f"LoRA shape 与 MOSS 不匹配：{label}")
    if alpha:
        if alpha.shape not in {(), (1,)}:
            raise ValueError(f"LoRA alpha 必须是标量：{label}")
        value = _alpha_value(stream, alpha.dtype, alpha.start)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"LoRA alpha 必须是有限正数：{label}")


def _split_fused(pair):
    """mx.split(qkv, 3) order: each row third of `up` goes to q, k, v; `down` and alpha are shared."""
    up = pair["up"]
    rows, chunk = up.shape[0] // 3, up.length // 3
    for index, module in enumerate("qkv"):
        part = _Slice(up.dtype, (rows, up.shape[1]), up.start + index * chunk, chunk)
        yield module, {**pair, "up": part}


def _plan(path):
    """Validated output tensors, plus whether the file is already canonical."""
    header = read_safetensors_header(path)
    groups = _collect(header)
    outputs = {}
    with Path(path).open("rb") as stream:
        for (layer, module), pair in groups.items():
            _validate_group(stream, layer, module, pair)
            if module == "qkv" and any((layer, name) in groups for name in "qkv"):
                raise ValueError(f"LoRA 同一层同时包含 qkv 与 q/k/v：layers.{layer}")
            for target, parts in (_split_fused(pair) if module == "qkv" else ((module, pair),)):
                canonical = _canonical_module(layer, target)
                for side, part in parts.items():
                    outputs[_output_key(canonical, side)] = part
    if not outputs:
        raise ValueError("LoRA 不包含可用张量")
    return outputs, set(outputs) == set(header.tensors), len(groups)


def inspect(path):
    """Header check for the import path; returns the same counters as the shared store."""
    outputs, _, adapters = _plan(path)
    return {"tensor_count": len(outputs), "adapter_count": adapters}


def _encode_header(outputs, sha256):
    header = {"__metadata__": {"format": "pt", "canvashub_moss_converter": CONVERTER_VERSION,
                               "canvashub_moss_source_sha256": sha256}}
    offset = 0
    for key in sorted(outputs):
        part = outputs[key]
        header[key] = {"dtype": part.dtype, "shape": list(part.shape),
                       "data_offsets": [offset, offset + part.length]}
        offset += part.length
    encoded = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return encoded + b" " * (-len(encoded) % 8), offset


def _expected_size(encoded, payload):
    return 8 + len(encoded) + payload


def _cache_matches(path, encoded, payload):
    try:
        if path.is_symlink() or path.stat().st_size != _expected_size(encoded, payload):
            return False
        with path.open("rb") as stream:
            raw = stream.read(8 + len(encoded))
    except OSError:
        return False
    return raw == struct.pack("<Q", len(encoded)) + encoded


def _write(asset_path, destination, outputs, encoded, payload):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{destination.stem}-", suffix=".tmp", dir=destination.parent,
                                     delete=False) as target:
        pending = Path(target.name)
    try:
        with pending.open("wb") as target, Path(asset_path).open("rb") as source:
            target.write(struct.pack("<Q", len(encoded)) + encoded)
            for key in sorted(outputs):
                part = outputs[key]
                source.seek(part.start)
                blob = source.read(part.length)
                if len(blob) != part.length:
                    raise ValueError(f"LoRA 张量数据不完整：{key}")
                target.write(blob)
            target.flush()
            os.fsync(target.fileno())
        if pending.stat().st_size != _expected_size(encoded, payload):
            raise ValueError("LoRA 转换结果大小异常")
        os.replace(pending, destination)
    finally:
        pending.unlink(missing_ok=True)


def cache_path(sha256, cache_dir):
    return Path(cache_dir) / f"{normalize_asset_id(sha256)}-{CONVERTER_VERSION}.safetensors"


def prepare(asset_path, sha256, cache_dir):
    """Path of an apply_lora-ready file. Canonical sources are returned as is; sources are never touched."""
    outputs, canonical, _ = _plan(asset_path)
    if canonical:
        return Path(asset_path)
    destination = cache_path(sha256, cache_dir)
    encoded, payload = _encode_header(outputs, normalize_asset_id(sha256))
    if not _cache_matches(destination, encoded, payload):
        _write(asset_path, destination, outputs, encoded, payload)
    return destination


def evict(sha256, cache_dir):
    """Drop every converter version of one asset, plus interrupted writes."""
    asset = normalize_asset_id(sha256)
    directory = Path(cache_dir)
    for pattern in (f"{asset}-*.safetensors", f".{asset}-*.tmp"):
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)
