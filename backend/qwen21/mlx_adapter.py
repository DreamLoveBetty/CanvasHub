"""Worker-only Qwen/Viggle adapter. Never import in the HTTP process."""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

import mlx.core as mx
from mflux.models.common.config import ModelConfig
from mflux.models.common.schedulers import register_contrib
from mflux.models.common.schedulers.base_scheduler import BaseScheduler
from mflux.models.qwen21.reference import QwenImage21Edit

from .profiles import turbo_sigmas, viggle_sigmas
from .lora_store import canonical_lora_key, canonical_name
from ..local_image.comfy_fp8 import read_safetensors_header
from ..local_image.safetensors import save_safetensors_atomic


def prepare_loras(loras, cache_directory):
    """Canonicalize accepted community keys in the worker, never edit originals.

    The pinned mapping has no alpha patterns. Fold alpha/rank into B once to
    preserve its semantics instead of silently dropping community alpha values.
    """
    result = []
    for item in loras:
        path = Path(item["path"])
        header = read_safetensors_header(path)
        mapped = {key: canonical_lora_key(key) for key in header.tensors}
        if all(key == canonical_name(*target) and target[1] != "alpha" for key, target in mapped.items()):
            result.append(item)
            continue
        stat = path.stat()
        cache_id = hashlib.sha256(f"lora-keys-v1:{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
        destination = Path(cache_directory) / (cache_id + ".safetensors")
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            weights = mx.load(str(path))
            canonical = {canonical_name(*mapped[key]): value for key, value in weights.items()}
            for key, (target, side) in mapped.items():
                if side == "alpha":
                    alpha = float(weights[key].item())
                    if not math.isfinite(alpha) or alpha < 0:
                        raise ValueError("Qwen LoRA alpha 必须为有限非负数")
                    b_key = canonical_name(target, "B")
                    rank = canonical[b_key].shape[1]
                    canonical[b_key] = canonical[b_key] * (alpha / rank)
                    canonical.pop(canonical_name(target, "alpha"))
            save_safetensors_atomic(mx, destination, canonical, metadata={"architecture": "qwen-image-2.1"})
        result.append({**item, "path": str(destination)})
    return result


class ViggleTurboScheduler(BaseScheduler):
    def __init__(self, config):
        model = config.model_config
        sigmas = viggle_sigmas(config.num_inference_steps, config.width, config.height,
                               base_shift=model.sigma_base_shift, max_shift=model.sigma_max_shift,
                               base_seq_len=model.sigma_base_seq_len, max_seq_len=model.sigma_max_seq_len)
        self._sigmas = mx.array(sigmas, dtype=mx.float32)

    @property
    def sigmas(self):
        return self._sigmas

    def step(self, noise, timestep, latents, **kwargs):
        result = latents.astype(mx.float32) + (self._sigmas[timestep + 1] - self._sigmas[timestep]) * noise.astype(mx.float32)
        return result.astype(latents.dtype)


class DistilledTurboScheduler(ViggleTurboScheduler):
    """Official Turbo checkpoint: its fixed 8 sigma nodes, no resolution shift."""

    def __init__(self, config):
        self._sigmas = mx.array(turbo_sigmas(config.num_inference_steps), dtype=mx.float32)


def load_pipeline(model_path, loras, turbo):
    register_contrib(ViggleTurboScheduler, "canvas_viggle")
    register_contrib(DistilledTurboScheduler, "canvas_turbo")
    config = copy.copy(ModelConfig.qwen_image_21())
    if turbo:
        config.sigma_shift_terminal = None
    return QwenImage21Edit(model_path=str(model_path), model_config=config,
                           lora_paths=[str(x["path"]) for x in loras] or None,
                           lora_scales=[float(x["scale"]) for x in loras] or None,
                           bake_lora=False)
