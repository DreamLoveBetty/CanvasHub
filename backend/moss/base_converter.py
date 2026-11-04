"""Community MOSS checkpoint -> BF16 MLX DiT, run in a leased child process; never touches the source.

Comfy INT8 ConvRot follows comfy-kitchen's dequantize_int8_convrot_weight: FP32(q * per-row scale), inverse REGULAR
H4 Kronecker rotation, BF16 round-to-nearest-even. Native BF16 tensors stay byte-identical. Needs NumPy only.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import traceback

import numpy as np

PREFIX = "model.diffusion_model."
EVENT_PREFIX = "MOSS_CONVERT_EVENT "
QKV = re.compile(r"^layers\.\d+\.proj\.qkv\.weight$")
DTYPE_BYTES = {"I8": 1, "U8": 1, "F32": 4, "BF16": 2}
SHARD_BYTES = 2 << 30
ROWS_PER_CHUNK = 256


def emit(event, **extra):
    print(EVENT_PREFIX + json.dumps({"event": event, **extra}, ensure_ascii=False), flush=True)


def strict_object(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError(f"Duplicate JSON key: {k}")
        result[k] = v
    return result


class SafeTensorReader:
    def __init__(self, path):
        self.path = Path(path).resolve()
        size = self.path.stat().st_size
        with self.path.open("rb") as f:
            first = f.read(8)
            if len(first) != 8:
                raise ValueError(f"Truncated safetensors prefix: {path}")
            length = struct.unpack("<Q", first)[0]
            if not 2 <= length <= min(128 << 20, size - 8):
                raise ValueError(f"Invalid safetensors header length: {path}")
            header = json.loads(f.read(length), object_pairs_hook=strict_object)
        self.base = length + 8
        self.metadata = header.pop("__metadata__", {})
        if not isinstance(self.metadata, dict):
            raise ValueError("Safetensors metadata must be an object")
        self.tensors = header
        ranges = []
        for key, entry in header.items():
            dtype, shape, offsets = entry["dtype"], entry["shape"], entry["data_offsets"]
            if dtype not in DTYPE_BYTES or not isinstance(shape, list):
                raise ValueError(f"Unsupported tensor descriptor: {key}")
            if any(type(v) is not int or v < 0 for v in shape):
                raise ValueError(f"Invalid shape: {key}")
            if (not isinstance(offsets, list) or len(offsets) != 2
                    or any(type(v) is not int for v in offsets)):
                raise ValueError(f"Invalid offsets: {key}")
            a, b = offsets
            if (a < 0 or b < a or self.base + b > size
                    or b - a != math.prod(shape) * DTYPE_BYTES[dtype]):
                raise ValueError(f"Shape/size/offset mismatch: {key}")
            ranges.append((a, b, key))
        end = 0
        for a, b, key in sorted(ranges):
            if a != end:
                raise ValueError(f"Overlapping or noncontiguous tensor: {key}")
            end = b
        if end != size - self.base:
            raise ValueError("Unreferenced or truncated safetensors payload")

    def raw(self, key, start=0, length=None):
        a, b = self.tensors[key]["data_offsets"]
        length = b - a - start if length is None else length
        if start < 0 or length < 0 or start + length > b - a:
            raise ValueError(f"Read outside tensor: {key}")
        with self.path.open("rb") as f:
            f.seek(self.base + a + start)
            value = f.read(length)
        if len(value) != length:
            raise ValueError(f"Truncated read: {key}")
        return value


@lru_cache(maxsize=8)
def regular_hadamard(size):
    n = size
    if type(size) is not int or size < 4:
        raise ValueError("Regular Hadamard size must be a positive power of four")
    while n > 1 and n % 4 == 0:
        n //= 4
    if n != 1:
        raise ValueError("Regular Hadamard size must be a power of four")
    h4 = np.array([[1, 1, 1, -1], [1, 1, -1, 1],
                   [1, -1, 1, 1], [-1, 1, 1, 1]], dtype=np.float32)
    h = h4
    while h.shape[0] < size:
        h = np.kron(h, h4)
    h = h / np.float32(math.sqrt(size))
    h.flags.writeable = False
    return h


def restore_convrot(q, scale, group_size):
    q, scale = np.asarray(q), np.asarray(scale, dtype=np.float32)
    if (q.dtype != np.int8 or q.ndim != 2 or scale.shape != (q.shape[0], 1)
            or not np.isfinite(scale).all() or not (scale > 0).all()):
        raise ValueError("Expected INT8 matrix and finite positive FP32 per-row scales")
    h = regular_hadamard(group_size)
    if q.shape[1] % group_size:
        raise ValueError("Input features are not divisible by the ConvRot group size")
    dequantized = q.astype(np.float32) * scale
    result = (dequantized.reshape(-1, group_size) @ h.T).reshape(q.shape)
    if not np.isfinite(result).all():
        raise ValueError("Nonfinite restored weights")
    return result


def float32_to_bf16(values):
    values = np.ascontiguousarray(values, dtype="<f4")
    bits = values.view("<u4")
    # Round-to-nearest-even, preserving infinities and producing a quiet NaN.
    rounded = ((bits + np.uint32(0x7fff) + ((bits >> 16) & 1)) >> 16).astype("<u2")
    nan = ((bits & 0x7f800000) == 0x7f800000) & ((bits & 0x007fffff) != 0)
    return np.where(nan, (bits >> 16).astype("<u2") | 0x0040, rounded).astype("<u2")


def normalize_key(key):
    key = key.removeprefix(PREFIX)
    if key.startswith("time_embedding.2."):
        key = key.replace("time_embedding.2.", "time_embedding.1.", 1)
    return key


def prepare(source, reference):
    reader = SafeTensorReader(source)
    raw_metadata = reader.metadata.get("_quantization_metadata")
    metadata = json.loads(raw_metadata, object_pairs_hook=strict_object) if raw_metadata else {"layers": {}}
    if raw_metadata and (metadata["format_version"] != "1.0" or not metadata["layers"]):
        raise ValueError("Unsupported or empty quantization metadata")
    scales, handled, plans = {}, set(), []
    for module, config in metadata["layers"].items():
        if config != {"format": "int8_tensorwise", "convrot": True, "convrot_groupsize": 256}:
            raise ValueError(f"Unsupported quantization: {module}: {config}")
        weight, scale, marker = PREFIX + module + ".weight", PREFIX + module + ".weight_scale", module + ".comfy_quant"
        w, s, m = (reader.tensors[k] for k in (weight, scale, marker))
        if (w["dtype"] != "I8" or len(w["shape"]) != 2 or w["shape"][1] % 256
                or s["dtype"] != "F32" or s["shape"] != [w["shape"][0], 1] or m["dtype"] != "U8"):
            raise ValueError(f"Incompatible quantized tensor descriptors: {module}")
        if json.loads(reader.raw(marker)) != config:
            raise ValueError(f"Quantization marker contradicts metadata: {module}")
        values = np.frombuffer(reader.raw(scale), dtype="<f4").reshape(s["shape"])
        if not np.isfinite(values).all() or not (values > 0).all():
            raise ValueError(f"Invalid scales: {module}")
        scales[weight] = values
        handled.update((scale, marker))
    for source_key, entry in reader.tensors.items():
        if source_key in handled:
            continue
        key, shape = normalize_key(source_key), entry["shape"]
        quantized = source_key in scales
        if entry["dtype"] != ("I8" if quantized else "BF16"):
            raise ValueError(f"Unaccounted or unsupported tensor: {source_key}")
        parts = [(key, list(shape), 0, shape[0] if shape else 1)]
        if QKV.fullmatch(key):
            if len(shape) != 2 or shape[0] % 3:
                raise ValueError(f"Invalid fused QKV: {source_key}")
            rows = shape[0] // 3
            parts = [(key.replace(".qkv.weight", f".{part}.weight"), [rows, shape[1]], i * rows, (i + 1) * rows)
                     for i, part in enumerate(("q", "k", "v"))]
        for target_key, target_shape, start, end in parts:
            plans.append({"target": target_key, "source": source_key, "shape": target_shape,
                          "row_start": start, "row_end": end, "quantized": quantized,
                          "nbytes": math.prod(target_shape) * 2})
    schema = {}
    for shard in sorted(reference.glob("*.safetensors")):
        for key, entry in SafeTensorReader(shard).tensors.items():
            key = normalize_key(key)
            if key in schema or entry["dtype"] != "BF16":
                raise ValueError(f"Invalid/duplicate reference tensor: {key}")
            schema[key] = entry["shape"]
    actual = {p["target"]: p["shape"] for p in plans}
    if len(actual) != len(plans) or actual != schema:
        missing, extra = set(schema) - set(actual), set(actual) - set(schema)
        bad = [k for k in actual.keys() & schema.keys() if actual[k] != schema[k]]
        raise ValueError(f"Reference schema mismatch: missing={sorted(missing)}, extra={sorted(extra)}, shapes={bad}")
    return reader, scales, sorted(plans, key=lambda p: p["target"])


def bf16_chunks(reader, scales, plan, rows_per_chunk):
    source_key = plan["source"]
    shape = reader.tensors[source_key]["shape"]
    if not plan["quantized"]:
        # All unchanged BF16 values (including subnormals) are byte-exact copies.
        width = math.prod(shape[1:]) if shape else 1
        start = plan["row_start"] * width * 2
        for offset in range(0, plan["nbytes"], 8 << 20):
            yield reader.raw(source_key, start + offset, min(8 << 20, plan["nbytes"] - offset))
        return
    width = shape[1]
    for row in range(plan["row_start"], plan["row_end"], rows_per_chunk):
        end = min(row + rows_per_chunk, plan["row_end"])
        q = np.frombuffer(reader.raw(source_key, row * width, (end - row) * width), dtype=np.int8).reshape(end - row, width)
        restored = restore_convrot(q, scales[source_key][row:end], 256)
        yield float32_to_bf16(restored).tobytes()


def snapshot(path):
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def _shards(plans):
    groups, current, count = [], [], 0
    for plan in plans:
        if current and count + plan["nbytes"] > SHARD_BYTES:
            groups.append(current)
            current, count = [], 0
        current.append(plan)
        count += plan["nbytes"]
    return [*groups, current] if current else groups


def _write_shard(path, group, reader, scales, report):
    header, offset = {"__metadata__": {"format": "mlx", "dtype": "bfloat16"}}, 0
    for plan in group:
        header[plan["target"]] = {"dtype": "BF16", "shape": plan["shape"],
                                  "data_offsets": [offset, offset + plan["nbytes"]]}
        offset += plan["nbytes"]
    encoded = json.dumps(header, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 8)
    with path.open("xb") as stream:
        stream.write(struct.pack("<Q", len(encoded)) + encoded)
        for plan in group:
            written = 0
            for raw in bf16_chunks(reader, scales, plan, ROWS_PER_CHUNK):
                if np.any((np.frombuffer(raw, dtype="<u2") & 0x7f80) == 0x7f80):
                    raise ValueError(f"Nonfinite BF16 output: {plan['target']}")
                stream.write(raw)
                written += len(raw)
            if written != plan["nbytes"]:
                raise ValueError(f"Wrong output length: {plan['target']}")
            report()
        stream.flush()
        os.fsync(stream.fileno())
    SafeTensorReader(path)


def convert_file(source, reference, output):
    source, reference, output = Path(source).resolve(), Path(reference).resolve(), Path(output).resolve()
    before = snapshot(source)
    reader, scales, plans = prepare(source, reference)
    transformer = output / "transformer"
    transformer.mkdir(parents=True)
    index, done = {}, [0]

    def report():
        done[0] += 1
        emit("progress", progress=5 + 90 * done[0] / len(plans), stage=f"转换张量 {done[0]}/{len(plans)}")

    groups = _shards(plans)
    for number, group in enumerate(groups, 1):
        name = f"model-{number:05d}-of-{len(groups):05d}.safetensors"
        _write_shard(transformer / name, group, reader, scales, report)
        index.update({plan["target"]: name for plan in group})
    (transformer / "model.safetensors.index.json").write_text(json.dumps(
        {"metadata": {"total_size": sum(plan["nbytes"] for plan in plans)}, "weight_map": index}, indent=2))
    if snapshot(source) != before:
        raise ValueError("源文件在转换期间发生变化，已放弃本次输出")
    return {"source_format": "comfy-int8-convrot" if scales else "bf16", "tensor_count": len(plans)}


def copy_directory(source, output):
    """An already-converted MLX export only needs copying; the library validates it before publishing."""
    transformer = Path(output) / "transformer"
    transformer.mkdir(parents=True)
    files = sorted(path for path in (Path(source) / "transformer").iterdir()
                   if path.name.endswith((".safetensors", ".index.json")))
    for number, path in enumerate(files, 1):
        emit("progress", progress=5 + 90 * number / len(files), stage=f"复制 {path.name}")
        shutil.copyfile(path, transformer / path.name)
    return {"source_format": "mlx-bf16", "tensor_count": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        emit("progress", progress=3, stage="校验源模型")
        source = Path(args.source)
        result = copy_directory(source, args.output) if source.is_dir() else convert_file(
            source, args.reference, args.output)
        emit("result", **result)
    except Exception as error:
        traceback.print_exc()
        emit("error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
