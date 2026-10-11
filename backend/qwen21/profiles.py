"""Pure Qwen 2.1 geometry, independent edit noise and Viggle sigma profiles."""
from __future__ import annotations

import hashlib
import math


DEFAULT_PRESET = "viggle-v03-r256"
ADAPTERS = {
    "viggle-v021-r256": {"label": "Viggle v0.2.1 · r256", "rank": 256,
        "filename": "Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r256.safetensors",
        "revision": "009a44a895ef85f7e643c80fdca9543795248867", "size": 1_359_147_904,
        "sha256": "2a0148f5c73abbed5f97da5ea356e439318aadb281d01fce4af39cdf43728803"},
    "viggle-v03-r256": {"label": "Viggle v0.3 · r256", "rank": 256,
        "filename": "Qwen-Image-2.1-viggle-turbo-v0.3-6step-lora-r256.safetensors",
        "revision": "009a44a895ef85f7e643c80fdca9543795248867", "size": 1_359_147_904,
        "sha256": "f06c266e04438b5272bdfb99410421d52a65d7a37f6f42aabc3cb1faf0142644"},
    "viggle-v021-r128": {"label": "Viggle v0.2.1 · r128", "rank": 128,
        "filename": "Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors",
        "revision": "bb26a0f38e5fe6c124aaccc9187a87eed5d9ed13", "size": 679_604_800,
        "sha256": "bafb91d0047df3f9b8a5a850b0c967f051164314d8aad778dfa34d9c24ec345b"},
}
# Official Qwen-Image-2.1-Turbo schedule (checkpoint model_index.json sample_sigmas).
# Its scheduler disables dynamic shifting with shift=1.0, so these nodes are used
# as-is: never resolution-shifted like Viggle, never re-spaced like the base model.
TURBO_PRESET = "turbo-8"
TURBO_SIGMAS = (1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568)
PRESETS = {"standard": {"label": "标准 · 默认 40 步", "steps": 40, "guidance": 1.0, "min_steps": 2,
                        "max_steps": 60, "max_references": 10}}
PRESETS.update({key: {"label": value["label"], "steps": 6, "guidance": 1.0, "min_steps": 5,
                      "max_steps": 60, "max_references": 3}
                for key, value in ADAPTERS.items()})
# Distilled checkpoint, not an adapter: valid only with a Base whose manifest
# declares sampling=turbo-8, and such a Base accepts no other preset.
PRESETS[TURBO_PRESET] = {"label": "Turbo · 8 步", "steps": len(TURBO_SIGMAS), "guidance": 1.0,
                         "min_steps": len(TURBO_SIGMAS), "max_steps": len(TURBO_SIGMAS),
                         "max_references": 10}
LEGACY_PRESETS = {"viggle-6": (DEFAULT_PRESET, 6), "viggle-8": (DEFAULT_PRESET, 8)}


def canonical_preset(value):
    value = str(value or DEFAULT_PRESET)
    return LEGACY_PRESETS.get(value, (value, None))[0]


def preset_kind(value):
    """standard = base 40-step linear; adapter = Viggle LoRA; distilled = Turbo Base."""
    value = canonical_preset(value)
    if value == "standard":
        return "standard"
    if value in ADAPTERS:
        return "adapter"
    if value == TURBO_PRESET:
        return "distilled"
    raise ValueError("未知 Qwen 推理预设")


def turbo_sigmas(steps):
    if isinstance(steps, bool) or steps != len(TURBO_SIGMAS):
        raise ValueError(f"Turbo 蒸馏模型固定为 {len(TURBO_SIGMAS)} 步")
    return [*TURBO_SIGMAS, 0.0]


def raw_viggle_sigmas(steps):
    if isinstance(steps, bool) or int(steps) != steps or not 5 <= int(steps) <= 60:
        raise ValueError("Viggle 步数必须在 5–60 之间")
    # Author's rule: change the high-noise end only; retain all four low-noise
    # anchors. 9 turbo steps here are NOT the separate 7-turbo + 2-base mode.
    count = int(steps) - 4
    return tuple(1 - .125 * index / count for index in range(count)) + (.875, .75, .5, .25)


RAW_SIGMAS = {steps: raw_viggle_sigmas(steps) for steps in (5, 6, 7, 8)}


def dimensions(ratio, resolution=1024):
    a, b = (int(x) for x in str(ratio).split(":"))
    width = math.sqrt(resolution * resolution * a / b)
    return max(32, round(width / 32) * 32), max(32, round(width * b / a / 32) * 32)


def edit_noise_seed(seed, references):
    """Separate the output RNG from reference conditioning, deterministically.

    Hash image pixels, not machine-specific filenames. This prevents seed 0
    from accidentally reusing conditioning noise while preserving reproduction.
    """
    if not references:
        return int(seed)
    value = hashlib.sha256(str(int(seed)).encode())
    for image in references:
        value.update(f"{image.width}x{image.height}:{image.mode}".encode())
        value.update(image.tobytes())
    return int.from_bytes(value.digest()[:4], "little")


def viggle_sigmas(steps, width, height, *, base_shift=.5, max_shift=.9,
                  base_seq_len=256, max_seq_len=8192):
    nodes = raw_viggle_sigmas(steps)
    m = (max_shift - base_shift) / (max_seq_len - base_seq_len)
    mu = m * width * height / 256 + base_shift - m * base_seq_len
    shift = math.exp(mu)
    return [shift / (shift + 1 / sigma - 1) for sigma in nodes] + [0.0]
