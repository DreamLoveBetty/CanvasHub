"""CPU-only validation for the direct two-factor Krea LoKr format.

This is deliberately not a generic LyCORIS loader: decomposed/Tucker/DoRA,
convolutional and mixed A/B files fail closed. No accelerator imports here.
"""
from __future__ import annotations

import math
import re

from ..local_image.comfy_fp8 import read_safetensors_header


FORMAT = "lokr-direct-v1"
STYLE_FORMAT = "lokr-style-v1"
_SPECIAL = {
    "img_in": "first", "first": "first",
    "final_layer_linear": "last.linear", "last_linear": "last.linear",
    "time_embed_linear_1": "tmlp.0", "tmlp_0": "tmlp.0",
    "time_embed_linear_2": "tmlp.2", "tmlp_2": "tmlp.2",
    "time_mod_proj": "tproj.1", "tproj_1": "tproj.1",
    "txt_in_linear_1": "txtmlp.1", "txtmlp_1": "txtmlp.1",
    "txt_in_linear_2": "txtmlp.3", "txtmlp_3": "txtmlp.3",
    "text_fusion_projector": "txtfusion.projector", "txtfusion_projector": "txtfusion.projector",
}
_LAYER = {
    "attn_to_q": "attn.wq", "attn_wq": "attn.wq",
    "attn_to_k": "attn.wk", "attn_wk": "attn.wk",
    "attn_to_v": "attn.wv", "attn_wv": "attn.wv",
    "attn_to_out_0": "attn.wo", "attn_wo": "attn.wo",
    "attn_to_gate": "attn.gate", "attn_gate": "attn.gate",
    "ff_gate": "mlp.gate", "mlp_gate": "mlp.gate",
    "ff_up": "mlp.up", "mlp_up": "mlp.up",
    "ff_down": "mlp.down", "mlp_down": "mlp.down",
}
_DOTTED_PREFIXES = ("base_model.model.", "diffusion_model.", "transformer.")
_DOTTED_TRANSLATE = (
    ("transformer_blocks", "blocks"),
    ("text_fusion", "txtfusion"),
    ("final_layer.linear", "last.linear"),
    ("img_in", "first"),
    ("time_embed.linear_1", "tmlp.0"),
    ("time_embed.linear_2", "tmlp.2"),
    ("time_mod_proj", "tproj.1"),
    ("txt_in.linear_1", "txtmlp.1"),
    ("txt_in.linear_2", "txtmlp.3"),
    ("attn.to_out.0", "attn.wo"),
    ("attn.to_q", "attn.wq"),
    ("attn.to_k", "attn.wk"),
    ("attn.to_v", "attn.wv"),
    ("attn.to_gate", "attn.gate"),
    ("ff.gate", "mlp.gate"),
    ("ff.up", "mlp.up"),
    ("ff.down", "mlp.down"),
)
_VALID_TARGETS = (
    set(_SPECIAL.values())
    | {f"blocks.{idx}.{layer}" for idx in range(28) for layer in set(_LAYER.values())}
    | {f"txtfusion.{sec}.{idx}.{layer}"
       for sec in ("layerwise_blocks", "refiner_blocks")
       for idx in range(2)
       for layer in set(_LAYER.values())}
)


def target_path(name):
    """Explicit aliases avoid ambiguities from globally replacing underscores."""
    raw = str(name or "")
    if raw.startswith(("lycoris_", "lora_unet_")):
        stem = raw.removeprefix("lycoris_").removeprefix("lora_unet_")
        if stem in _SPECIAL:
            return _SPECIAL[stem]
        match = re.fullmatch(
            r"(transformer_blocks|blocks|(?:text_fusion|txtfusion)_(?:layerwise|refiner)_blocks)_(\d+)_(.+)",
            stem,
        )
        if match:
            section, index, layer = match.groups()
            is_main = section in {"transformer_blocks", "blocks"}
            maximum = 28 if is_main else 2
            if int(index) < maximum and layer in _LAYER:
                if is_main:
                    prefix = "blocks"
                else:
                    sub = section.removeprefix("text_fusion_").removeprefix("txtfusion_")
                    prefix = f"txtfusion.{sub}"
                return f"{prefix}.{int(index)}.{_LAYER[layer]}"
        raise ValueError(f"不支持的 Krea LoKr 目标层：{stem}")
    if raw.startswith(_DOTTED_PREFIXES):
        dotted = raw
        if dotted.startswith("base_model.model."):
            dotted = dotted[len("base_model.model."):]
        for pre in ("diffusion_model.", "transformer."):
            if dotted.startswith(pre):
                dotted = dotted[len(pre):]
                break
        for old, new in _DOTTED_TRANSLATE:
            dotted = dotted.replace(old, new)
        if dotted in _VALID_TARGETS:
            return dotted
        raise ValueError(f"不支持的 Krea LoKr 目标层：{raw}")
    raise ValueError(f"不支持的 Krea LoKr 层名：{name}")


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
    adapter_format = FORMAT if all(key.startswith("lycoris_") for key in header.tensors) else STYLE_FORMAT
    return {"adapter_format": adapter_format, "tensor_count": len(header.tensors),
            "adapter_count": len(groups), "layers": groups}
