"""Strict ComfyUI scaled-FP8 checkpoint inspection and decoding.

The HTTP process only uses the lightweight header inspector.  Torch and MLX
are imported lazily by :func:`load_comfy_scaled_fp8` inside the isolated model
conversion child.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import gc
import json
import math
from pathlib import Path
import struct
from typing import Any, Callable, Mapping


MAX_CHECKPOINT_BYTES = 128 * 1024**3
MAX_HEADER_BYTES = 256 * 1024**2
SOURCE_FORMAT = "comfy-scaled-fp8-e4m3fn"
FP8_DTYPE = "F8_E4M3"
MARKER_SUFFIX = ".comfy_quant"
SCALE_SUFFIX = ".weight_scale"
SUPPORTED_PARAMETER_DTYPES = frozenset({"BF16", "F16", "F32", FP8_DTYPE})
KNOWN_PREFIXES = (
    "",
    "transformer.",
    "model.diffusion_model.",
    "diffusion_model.",
    "base_model.model.",
    "model.",
    "module.",
)
_DTYPE_BYTES = {"BF16": 2, "F16": 2, "F32": 4, FP8_DTYPE: 1, "U8": 1}


class ComfyFP8Error(ValueError):
    """The file resembles ComfyUI scaled-FP8 but violates its contract."""


@dataclass(frozen=True)
class SafetensorsHeader:
    path: Path
    file_size: int
    header_size: int
    payload_offset: int
    tensors: dict[str, dict[str, Any]]
    metadata: dict[str, Any]


def read_safetensors_header(
    path: str | Path,
    *,
    max_checkpoint_bytes: int = MAX_CHECKPOINT_BYTES,
    max_header_bytes: int = MAX_HEADER_BYTES,
) -> SafetensorsHeader:
    """Read and bounds-check a safetensors header without loading tensor data."""
    path = Path(path)
    size = path.stat().st_size
    if size <= 8 or size > int(max_checkpoint_bytes):
        raise ValueError("模型文件大小无效或超过 128 GiB")
    with path.open("rb") as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("模型 safetensors 文件头不完整")
        header_size = struct.unpack("<Q", raw)[0]
        if header_size < 2 or header_size > min(int(max_header_bytes), size - 8):
            raise ValueError("模型 safetensors 文件头无效")
        try:
            value = json.loads(stream.read(header_size))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("模型 safetensors 元数据无效") from exc
    if not isinstance(value, dict):
        raise ValueError("模型 safetensors 元数据必须为对象")
    payload_size = size - 8 - header_size
    tensors: dict[str, dict[str, Any]] = {}
    metadata = value.get("__metadata__")
    metadata = metadata if isinstance(metadata, dict) else {}
    for key, item in value.items():
        if key == "__metadata__":
            continue
        if not isinstance(key, str) or not isinstance(item, dict):
            raise ValueError("模型 safetensors 张量元数据无效")
        dtype, shape, offsets = item.get("dtype"), item.get("shape"), item.get("data_offsets")
        if (
            not isinstance(dtype, str)
            or not isinstance(shape, list)
            or any(isinstance(dim, bool) or not isinstance(dim, int) or dim < 0 for dim in shape)
            or not isinstance(offsets, list)
            or len(offsets) != 2
            or any(isinstance(offset, bool) or not isinstance(offset, int) for offset in offsets)
            or offsets[0] < 0
            or offsets[0] > offsets[1]
            or offsets[1] > payload_size
        ):
            raise ValueError("模型 safetensors 张量范围无效")
        tensors[key] = {
            "dtype": dtype.upper(),
            "shape": list(shape),
            "data_offsets": list(offsets),
        }
    if not tensors:
        raise ValueError("模型 safetensors 不包含张量")
    return SafetensorsHeader(
        path=path,
        file_size=size,
        header_size=header_size,
        payload_offset=8 + header_size,
        tensors=tensors,
        metadata=metadata,
    )


def _numel(shape: list[int]) -> int:
    return math.prod(shape)


def _tensor_bytes(stream, header: SafetensorsHeader, key: str, *, limit: int) -> bytes:
    item = header.tensors[key]
    start, end = item["data_offsets"]
    length = end - start
    if length < 0 or length > limit:
        raise ComfyFP8Error(f"ComfyUI scaled-FP8 辅助张量大小异常：{key}")
    stream.seek(header.payload_offset + start)
    value = stream.read(length)
    if len(value) != length:
        raise ComfyFP8Error(f"ComfyUI scaled-FP8 辅助张量不完整：{key}")
    return value


def _validate_storage_size(key: str, item: Mapping[str, Any]) -> None:
    dtype = str(item["dtype"]).upper()
    item_size = _DTYPE_BYTES.get(dtype)
    if item_size is None:
        return
    start, end = item["data_offsets"]
    expected = _numel(item["shape"]) * item_size
    if end - start != expected:
        raise ComfyFP8Error(f"ComfyUI scaled-FP8 张量字节数与 shape 不一致：{key}")


def inspect_comfy_scaled_fp8(header: SafetensorsHeader) -> dict[str, Any] | None:
    """Return a strict format report, ``None`` when the file is not Comfy FP8."""
    tensors = header.tensors
    marker_keys = {key for key in tensors if key.endswith(MARKER_SUFFIX)}
    scale_keys = {key for key in tensors if key.endswith(SCALE_SUFFIX)}
    fp8_keys = {key for key, item in tensors.items() if item["dtype"] == FP8_DTYPE}
    other_fp8 = sorted(
        key for key, item in tensors.items()
        if str(item["dtype"]).startswith("F8_") and item["dtype"] != FP8_DTYPE
    )
    if not marker_keys and not scale_keys and not fp8_keys and not other_fp8:
        return None
    if other_fp8:
        raise ComfyFP8Error(
            "ComfyUI scaled-FP8 当前仅支持 float8_e4m3fn；检测到 "
            + ", ".join(sorted({tensors[key]["dtype"] for key in other_fp8}))
        )
    if not marker_keys or not scale_keys or not fp8_keys:
        raise ComfyFP8Error("ComfyUI scaled-FP8 结构不完整：缺少 weight、weight_scale 或 comfy_quant")
    if len(marker_keys) != len(scale_keys) or len(marker_keys) != len(fp8_keys):
        raise ComfyFP8Error(
            "ComfyUI scaled-FP8 三元组数量不一致："
            f"weight={len(fp8_keys)}、weight_scale={len(scale_keys)}、comfy_quant={len(marker_keys)}"
        )

    paired_weights: set[str] = set()
    paired_scales: set[str] = set()
    marker_variants: Counter[str] = Counter()
    with header.path.open("rb") as stream:
        for marker_key in sorted(marker_keys):
            base = marker_key[: -len(MARKER_SUFFIX)]
            weight_key = base + ".weight"
            scale_key = base + SCALE_SUFFIX
            if weight_key not in tensors or scale_key not in tensors:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 层缺少配对权重或 scale：{base}")
            weight = tensors[weight_key]
            scale = tensors[scale_key]
            marker = tensors[marker_key]
            if weight["dtype"] != FP8_DTYPE:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 权重类型必须为 F8_E4M3：{weight_key}")
            if scale["dtype"] != "F32" or scale["shape"] != []:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 weight_scale 必须是 F32 标量：{scale_key}")
            if marker["dtype"] != "U8" or len(marker["shape"]) != 1:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 comfy_quant 必须是 U8 JSON：{marker_key}")
            for key in (weight_key, scale_key, marker_key):
                _validate_storage_size(key, tensors[key])

            marker_bytes = _tensor_bytes(stream, header, marker_key, limit=2048)
            try:
                config = json.loads(marker_bytes.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 comfy_quant JSON 无效：{marker_key}") from exc
            if not isinstance(config, dict) or config.get("format") != "float8_e4m3fn":
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 marker 格式不受支持：{marker_key}")
            unexpected = set(config) - {"format", "full_precision_matrix_mult"}
            if unexpected or (
                "full_precision_matrix_mult" in config
                and not isinstance(config["full_precision_matrix_mult"], bool)
            ):
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 marker 参数不受支持：{marker_key}")
            scale_bytes = _tensor_bytes(stream, header, scale_key, limit=4)
            if len(scale_bytes) != 4:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 weight_scale 字节数无效：{scale_key}")
            scale_value = struct.unpack("<f", scale_bytes)[0]
            if not math.isfinite(scale_value) or scale_value <= 0:
                raise ComfyFP8Error(f"ComfyUI scaled-FP8 weight_scale 必须是有限正数：{scale_key}")

            paired_weights.add(weight_key)
            paired_scales.add(scale_key)
            marker_variants[json.dumps(config, ensure_ascii=True, sort_keys=True)] += 1

    orphan_weights = sorted(fp8_keys - paired_weights)
    orphan_scales = sorted(scale_keys - paired_scales)
    if orphan_weights or orphan_scales:
        example = (orphan_weights or orphan_scales)[0]
        raise ComfyFP8Error(f"ComfyUI scaled-FP8 存在未配对辅助张量：{example}")
    if any(key.endswith(".input_scale") for key in tensors):
        raise ComfyFP8Error("暂不支持包含 input_scale 的激活量化 ComfyUI FP8 模型")
    unexpected_u8 = sorted(
        key for key, item in tensors.items()
        if item["dtype"] == "U8" and key not in marker_keys
    )
    if unexpected_u8:
        raise ComfyFP8Error(f"ComfyUI scaled-FP8 包含未知 U8 张量：{unexpected_u8[0]}")

    parameter_keys = set(tensors) - marker_keys - scale_keys
    unsupported = sorted({
        tensors[key]["dtype"] for key in parameter_keys
        if tensors[key]["dtype"] not in SUPPORTED_PARAMETER_DTYPES
    })
    if unsupported:
        raise ComfyFP8Error("ComfyUI scaled-FP8 包含不支持的参数类型：" + " / ".join(unsupported))
    for key in parameter_keys:
        _validate_storage_size(key, tensors[key])
    return {
        "source_format": SOURCE_FORMAT,
        "source_tensor_count": len(parameter_keys),
        "quantized_tensor_count": len(fp8_keys),
        "marker_variants": dict(marker_variants),
    }


def _shape(value: Any) -> tuple[int, ...]:
    if isinstance(value, Mapping):
        return tuple(value.get("shape") or ())
    return tuple(value.shape)


def select_header_weights(
    tensors: Mapping[str, Mapping[str, Any]], expected: Mapping[str, Any]
) -> tuple[str, list[tuple[str, str]]]:
    """Match one known wrapper prefix using names and shapes only."""
    best = None
    for prefix in KNOWN_PREFIXES:
        mapped: list[tuple[str, str]] = []
        missing: list[str] = []
        mismatched: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
        for key, expected_array in expected.items():
            source_key = prefix + key
            source_item = tensors.get(source_key)
            if source_item is None:
                missing.append(key)
                continue
            actual_shape = _shape(source_item)
            expected_shape = _shape(expected_array)
            if actual_shape != expected_shape:
                mismatched.append((key, actual_shape, expected_shape))
                continue
            mapped.append((key, source_key))
        score = (len(mapped) + len(mismatched)) * 10 - len(missing) - len(mismatched)
        candidate = (score, prefix, mapped, missing, mismatched)
        if best is None or candidate[0] > best[0]:
            best = candidate
        if not missing and not mismatched:
            return prefix, mapped
    _, prefix, _, missing, mismatched = best
    details = []
    if missing:
        details.append(f"缺少 {len(missing)} 个张量，例如 {', '.join(missing[:3])}")
    if mismatched:
        name, actual, wanted = mismatched[0]
        details.append(f"{len(mismatched)} 个 shape 不一致，例如 {name}: {actual} != {wanted}")
    raise ValueError(
        "源模型与目标 Transformer 不兼容（"
        + (prefix or "无前缀")
        + "）："
        + "；".join(details)
    )


def load_comfy_scaled_fp8(
    path: str | Path,
    expected: Mapping[str, Any],
    mx,
    *,
    header: SafetensorsHeader | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    """Decode one validated checkpoint into BF16 MLX arrays, one tensor at a time."""
    try:
        import torch
        from safetensors import safe_open
    except ImportError as exc:  # pragma: no cover - guarded by the shared environment probe
        raise RuntimeError("共享环境缺少 Torch 或 safetensors，无法解码 ComfyUI scaled-FP8") from exc

    header = header or read_safetensors_header(path)
    report = inspect_comfy_scaled_fp8(header)
    if report is None:
        raise ComfyFP8Error("源文件不是 ComfyUI scaled-FP8 模型")
    prefix, selected = select_header_weights(header.tensors, expected)
    total = sum(
        header.tensors[source_key]["data_offsets"][1]
        - header.tensors[source_key]["data_offsets"][0]
        for _, source_key in selected
    )
    done = 0
    mapped = []
    with safe_open(str(header.path), framework="pt", device="cpu") as source, torch.inference_mode():
        for index, (target_key, source_key) in enumerate(selected, 1):
            item = header.tensors[source_key]
            value = source.get_tensor(source_key)
            if item["dtype"] == FP8_DTYPE:
                base = source_key[: -len(".weight")]
                scale = source.get_tensor(base + SCALE_SUFFIX).to(dtype=torch.float32)
                decoded = (value.to(dtype=torch.float32) * scale).to(dtype=torch.bfloat16)
                del scale
            else:
                decoded = value.to(dtype=torch.bfloat16)
            decoded = decoded.contiguous()
            array = mx.from_dlpack(decoded, copy=True)
            mx.eval(array)
            if tuple(array.shape) != tuple(expected[target_key].shape):
                raise RuntimeError(f"ComfyUI scaled-FP8 解码后 shape 不一致：{target_key}")
            mapped.append((target_key, array))
            start, end = item["data_offsets"]
            done += end - start
            if progress:
                progress(done, max(1, total), target_key)
            del value, decoded, array
            if index % 32 == 0:
                gc.collect()
    gc.collect()
    return {
        "weights": mapped,
        "source_prefix": prefix,
        "source_tensor_count": len(mapped),
        "source_format": report["source_format"],
        "source_quantized_tensor_count": report["quantized_tensor_count"],
    }


__all__ = [
    "ComfyFP8Error",
    "KNOWN_PREFIXES",
    "MAX_CHECKPOINT_BYTES",
    "MAX_HEADER_BYTES",
    "SOURCE_FORMAT",
    "SafetensorsHeader",
    "inspect_comfy_scaled_fp8",
    "load_comfy_scaled_fp8",
    "read_safetensors_header",
    "select_header_weights",
]
