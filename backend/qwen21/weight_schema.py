"""Exact raw Qwen-Image 2.1 Transformer schema (not Qwen 1/old Edit)."""
from __future__ import annotations

from ..local_image.comfy_fp8 import KNOWN_PREFIXES


def expected_shapes():
    d = 4096
    result = {"img_in.weight": (d, 64), "proj_out.weight": (64, d),
              "modulation.1.weight": (4 * d, d), "norm_out.linear.weight": (d, d),
              "txt_in.text_norm.weight": (d,), "txt_in.in_layer.weight": (d, d),
              "txt_in.out_layer.weight": (d, d),
              "time_text_embed.timestep_embedder.linear_1.weight": (d, 256),
              "time_text_embed.timestep_embedder.linear_2.weight": (d, d)}
    for block in range(32):
        prefix = f"transformer_blocks.{block}."
        for name in ("to_q", "to_k", "to_v", "to_out.0"):
            result[prefix + "attn." + name + ".weight"] = (d, d)
        for name in ("norm_q", "norm_k"):
            result[prefix + "attn." + name + ".weight"] = (128,)
        for name in ("proj", "gate_layer"):
            result[prefix + "img_mlp." + name + ".weight"] = (3 * d, d)
        result[prefix + "img_mlp.out.weight"] = (d, 3 * d)
    return result


def mlx_name(raw_name):
    return raw_name.replace("modulation.1.", "modulation.layers.1.", 1)


def match_header(tensors, *, allow_auxiliary=False):
    expected = expected_shapes()
    for prefix in KNOWN_PREFIXES:
        if all(prefix + key in tensors and tuple(tensors[prefix + key]["shape"]) == shape
               for key, shape in expected.items()):
            selected = {prefix + key for key in expected}
            allowed = set(selected)
            if allow_auxiliary:
                for source in selected:
                    if source.endswith(".weight"):
                        allowed.update({source.removesuffix(".weight") + ".weight_scale",
                                        source.removesuffix(".weight") + ".comfy_quant"})
            extra = set(tensors) - allowed
            if extra:
                raise ValueError("源模型包含非 Qwen 2.1 Transformer 张量：" + ", ".join(sorted(extra)[:3]))
            return prefix
    raise ValueError("文件不含完整的 Qwen-Image 2.1 Transformer，或参数名称/shape 不匹配")
