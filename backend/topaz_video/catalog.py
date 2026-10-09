"""Topaz Video model metadata; availability is decided by the local runtime.

This is intentionally separate from the Gigapixel catalogue. A JSON model
descriptor in an installation does not imply that its weights are installed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    family: str
    backend_name: str
    scales: tuple[int, ...]
    parameter_keys: tuple[str, ...] = ()
    stage: str = "conventional"


GENERAL_PARAMETERS = (
    {"key": "preblur", "label": "去锯齿 / 去模糊", "type": "number", "min": -1, "max": 1, "step": 0.05, "default": 0},
    {"key": "noise", "label": "降噪", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "details", "label": "恢复细节", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "halo", "label": "去光晕", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "blur", "label": "锐化", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "compression", "label": "压缩修复", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "prenoise", "label": "输入加噪", "type": "number", "min": 0, "max": 0.1, "step": 0.01, "default": 0},
    {"key": "blend", "label": "原片混合", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    {"key": "grain", "label": "胶片颗粒", "type": "number", "min": 0, "max": 1, "step": 0.05, "default": 0},
    # Topaz advertises a numeric 0–5 range, but its native filter rejects
    # fractional non-zero sizes once grain is enabled.  Zero means automatic;
    # explicit sizes are the integer levels 1–5.
    {"key": "gsize", "label": "颗粒尺寸", "type": "number", "min": 0, "max": 5, "step": 1, "default": 0},
)
PRECISE_PARAMETERS = (
    {"key": "softness", "label": "柔和度", "type": "number", "min": 0, "max": 2, "step": 1, "default": 1},
)
PARAMETERS = {item["key"]: item for item in (*GENERAL_PARAMETERS, *PRECISE_PARAMETERS)}
GENERAL_KEYS = tuple(item["key"] for item in GENERAL_PARAMETERS)

# Only scales with locally observed model weights are declared. The installed
# slp-2.5.json points to the slp26 package, not an independent 2.5 model.
MODELS: tuple[Model, ...] = (
    Model("precise-26", "Starlight Precise 2.6", "starlight", "slp-26", (2,), ("softness",), "precise"),
    Model("precise-25", "Starlight Precise 2.5", "starlight", "slp-25", (), ("softness",), "unavailable"),
    Model("mini", "Starlight Mini", "starlight", "slm-1", (), (), "mini"),
    Model("proteus-v4", "Proteus v4", "enhance", "prob-4", (1, 4), GENERAL_KEYS),
    Model("nyx-v3", "Nyx v3", "denoise", "nyx-3", (1, 2), GENERAL_KEYS),
    Model("theia-v4", "Theia Fine Tune Fidelity v4", "enhance", "thf-4", (1, 2), GENERAL_KEYS),
    Model("iris", "Iris Medium Quality v2", "face", "iris-2", (1,), GENERAL_KEYS),
    Model("rhea", "Rhea v1", "upscale", "rhea-1", (1, 2, 4), GENERAL_KEYS),
    Model("artemis", "Artemis High Quality v12", "enhance", "ahq-12", (2,), GENERAL_KEYS),
    Model("gaia", "Gaia High Quality v5", "upscale", "ghq-5", (2,), GENERAL_KEYS),
    Model("gaia-animation", "Gaia Animation v1", "upscale", "ganim-1", (2,), GENERAL_KEYS),
)
BY_ID = {item.id: item for item in MODELS}


def public_model(model: Model, *, available: bool, reason: str = "", verified: bool = False,
                 verified_scales: tuple[int, ...] | list[int] = ()) -> dict:
    parameters = [dict(PARAMETERS[key]) for key in model.parameter_keys]
    if model.id == "nyx-v3":
        for parameter in parameters:
            if parameter["key"] == "details":
                parameter["label"] = "减少大颗粒"
    observed_scales = sorted({int(scale) for scale in verified_scales if int(scale) in model.scales})
    return {
        "id": model.id,
        "label": model.label,
        "family": model.family,
        "available": bool(available),
        "verified": bool(verified and available),
        "verified_scales": observed_scales if available else [],
        "reason": reason,
        "scales": list(model.scales),
        "parameters": parameters,
    }
