"""Qwen-specific ordinary LoRA schema on the shared direct-folder scanner."""
from __future__ import annotations

import re
from ..local_image.comfy_fp8 import read_safetensors_header
from ..local_image.lora_store import LoRAStore as _LoRAStore
from .weight_schema import expected_shapes


def canonical_lora_key(key):
    """Map known wrappers/PEFT names to the upstream Qwen target namespace."""
    name = key.removeprefix("base_model.model.")
    for prefix in ("model.diffusion_model.", "transformer.", "diffusion_model."):
        name = name.removeprefix(prefix)
    for suffix, side in ((".lora_A.default.weight", "A"), (".lora_B.default.weight", "B"),
                         (".lora_A.weight", "A"), (".lora_B.weight", "B"),
                         (".lora_down.weight", "A"), (".lora_up.weight", "B"), (".alpha", "alpha")):
        if name.endswith(suffix):
            target = name[:-len(suffix)]
            block = re.fullmatch(r"transformer_blocks\.(\d+)\.(attn\.(?:to_q|to_k|to_v|to_out\.0)|img_mlp\.(?:proj|gate_layer|out|gate_up))", target)
            globals_ = {"modulation.1", "time_text_embed.timestep_embedder.linear_1",
                        "time_text_embed.timestep_embedder.linear_2"}
            if not (block and int(block[1]) < 32 or target in globals_):
                raise ValueError("LoRA 包含 Qwen 2.1 不支持的目标层")
            return target, side
    raise ValueError("Qwen LoRA 张量名称不受支持")


def canonical_name(target, side):
    return "transformer." + target + (".alpha" if side == "alpha" else f".lora_{side}.weight")


class LoRAStore(_LoRAStore):
    def __init__(self, root):
        super().__init__(root, label="Qwen 2.1 LoRA", allow_peft_default=True)

    def _inspect(self, path):
        result = super()._inspect(path)
        tensors = read_safetensors_header(path).tensors
        pairs, alphas = {}, set()
        expected = {key.removesuffix(".weight"): shape for key, shape in expected_shapes().items()}
        for key, tensor in tensors.items():
            name, side = canonical_lora_key(key)
            shape = tuple(tensor["shape"])
            if tensor["dtype"] not in {"F32", "F16", "BF16"}:
                raise ValueError("Qwen LoRA 必须为 FP32、FP16 或 BF16")
            if side == "alpha":
                if shape not in {(), (1,)}:
                    raise ValueError("LoRA alpha 必须是标量")
                if name in alphas:
                    raise ValueError("LoRA 包含重复 alpha")
                alphas.add(name)
                continue
            target_shape = expected.get(name)
            if name.endswith("img_mlp.gate_up"):
                target_shape = (24576, 4096) if name.replace("gate_up", "proj") in expected else None
            if not target_shape or len(target_shape) != 2 or side is None or len(shape) != 2:
                raise ValueError("LoRA 包含 Qwen 2.1 不支持的目标层")
            if (side == "A" and shape[1] != target_shape[1]) or (side == "B" and shape[0] != target_shape[0]):
                raise ValueError("LoRA shape 与 Qwen 2.1 不匹配")
            pair = pairs.setdefault(name, {})
            if side in pair:
                raise ValueError("LoRA 包含重复目标层")
            pair[side] = shape
        if any(set(value) != {"A", "B"} or value["A"][0] != value["B"][1] for value in pairs.values()):
            raise ValueError("LoRA A/B 秩或目标层不匹配")
        if alphas - pairs.keys():
            raise ValueError("LoRA alpha 没有对应的 A/B 权重")
        return result
