"""MLX-safe atomic safetensors publication; imports no accelerator library."""
import os
import math
from pathlib import Path

from .comfy_fp8 import read_safetensors_header


def estimate_bf16_bytes(tensors):
    """Estimate float output from header shapes, not source FP8/F32 byte size.

    Scale/encoding markers belong to the source decoder, not the exported model.
    A small header allowance is separate from the service's staging headroom.
    """
    return 1024**2 + sum(2 * math.prod(item["shape"]) for key, item in tensors.items()
                        if not key.endswith((".weight_scale", ".comfy_quant")))


def validate_bf16_safetensors(path, tensor_count, *, metadata):
    """Bounded CPU-only proof of BF16 storage, alongside strict worker reload.

    Never infer BF16 from a filename or a manifest alone, and never accept a
    packed checkpoint or a float32 tensor labelled as BF16.
    """
    header = read_safetensors_header(path)
    if (tensor_count <= 0 or len(header.tensors) != tensor_count
            or any(item["dtype"] != "BF16" or key.endswith((".scales", ".biases"))
                   for key, item in header.tensors.items())
            or any(header.metadata.get(key) != value for key, value in metadata.items())):
        raise ValueError("BF16 Transformer 存储精度或结构校验失败")
    return header


def pending_safetensors_path(destination):
    destination = Path(destination)
    if destination.suffix.lower() != ".safetensors":
        raise ValueError("转换输出必须使用 .safetensors 扩展名")
    return destination.with_name(f".{destination.stem}.tmp{destination.suffix}")


def save_safetensors_atomic(mx, destination, arrays, metadata):
    destination = Path(destination)
    pending = pending_safetensors_path(destination)
    pending.unlink(missing_ok=True)
    mx.save_safetensors(str(pending), arrays, metadata=metadata)
    if not pending.is_file():
        raise RuntimeError("MLX 未生成预期的 safetensors 临时文件")
    os.replace(pending, destination)
