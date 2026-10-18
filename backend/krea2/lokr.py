"""CPU-only validation for the direct two-factor Krea LoKr format.

This is deliberately not a generic LyCORIS loader: decomposed/Tucker/DoRA,
convolutional and mixed A/B files fail closed. No accelerator imports here.
"""
from __future__ import annotations

import math
import re

from ..local_image.comfy_fp8 import read_safetensors_header


FORMAT = "lokr-direct-v1"
_SPECIAL = {
    "img_in": "first", "final_layer_linear": "last.linear",
    "time_embed_linear_1": "tmlp.0", "time_embed_linear_2": "tmlp.2",
    "time_mod_proj": "tproj.1", "txt_in_linear_1": "txtmlp.1",
    "txt_in_linear_2": "txtmlp.3", "text_fusion_projector": "txtfusion.projector",
}
_LAYER = {
    "attn_to_q": "attn.wq", "attn_to_k": "attn.wk", "attn_to_v": "attn.wv",
    "attn_to_out_0": "attn.wo", "attn_to_gate": "attn.gate",
    "ff_gate": "mlp.gate", "ff_up": "mlp.up", "ff_down": "mlp.down",
}


def target_path(name):
    """Explicit aliases avoid ambiguities from globally replacing underscores."""
    if not name.startswith("lycoris_"):
        raise ValueError(f"不支持的 Krea LoKr 层名：{name}")
    name = name.removeprefix("lycoris_")
    if name in _SPECIAL:
        return _SPECIAL[name]
    match = re.fullmatch(
        r"(transformer_blocks|text_fusion_(?:layerwise|refiner)_blocks)_(\d+)_(.+)", name)
    if match:
        section, index, layer = match.groups()
        maximum = 28 if section == "transformer_blocks" else 2
        if int(index) < maximum and layer in _LAYER:
            prefix = "blocks" if section == "transformer_blocks" else (
                "txtfusion." + section.removeprefix("text_fusion_"))
            return f"{prefix}.{int(index)}.{_LAYER[layer]}"
    raise ValueError(f"不支持的 Krea LoKr 目标层：{name}")


def inspect_lokr(path):
    """Return a strict header report, or None for an ordinary LoRA file."""
    header = read_safetensors_header(path, max_checkpoint_bytes=2 * 1024**3,
                                     max_header_bytes=64 * 1024**2)
    if not any(".lokr_" in key for key in header.tensors):
        return None
    groups, spans = {}, []
    for key, tensor in header.tensors.items():
        name, dot, suffix = key.rpartition(".")
        if not dot or suffix not in {"lokr_w1", "lokr_w2", "alpha"}:
            raise ValueError("LoKr 首版只支持完整的二维 lokr_w1 / lokr_w2（不支持混合或分解格式）")
        target = target_path(name)
        group = groups.setdefault(target, {})
        if suffix in group:
            raise ValueError("LoKr 目标层映射重复")
        shape, dtype = tensor["shape"], tensor["dtype"]
        item_bytes = {"F32": 4, "F16": 2, "BF16": 2}.get(dtype)
        start, end = tensor["data_offsets"]
        if (not item_bytes or end - start != math.prod(shape) * item_bytes
                or any(dim <= 0 for dim in shape)):
            raise ValueError("LoKr 张量精度或存储大小无效")
        if suffix == "alpha":
            if math.prod(shape) != 1:
                raise ValueError("LoKr alpha 必须是标量")
        elif len(shape) != 2:
            raise ValueError("LoKr 首版只支持二维线性层")
        group[suffix] = {"key": key, "shape": shape}
        spans.append((start, end))
    cursor = 0
    for start, end in sorted(spans):
        if start != cursor:
            raise ValueError("LoKr 张量存储重叠或包含空洞")
        cursor = end
    if cursor != header.file_size - header.payload_offset:
        raise ValueError("LoKr 文件包含未声明的数据")
    for target, group in groups.items():
        if not {"lokr_w1", "lokr_w2"} <= group.keys():
            raise ValueError(f"LoKr 因子不完整：{target}")
        a, b = group["lokr_w1"]["shape"], group["lokr_w2"]["shape"]
        group["shape"] = [a[0] * b[0], a[1] * b[1]]
    return {"adapter_format": FORMAT, "tensor_count": len(header.tensors),
            "adapter_count": len(groups), "layers": groups}
