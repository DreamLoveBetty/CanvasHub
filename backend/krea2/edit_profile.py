"""Pure Krea 2 instruction-edit geometry and adapter-independent defaults.

This module deliberately has no MLX, HTTP or storage imports.  The worker-only
runtime consumes the geometry below, while request validation and regression
tests can exercise the same contract without loading the local inference stack.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


EDIT_MODE = "edit"
STANDARD_MODE = "standard"
MODES = (STANDARD_MODE, EDIT_MODE)
FIT_MODES = ("fit", "crop")
DEFAULT_REFERENCE_STRENGTH = 4.0
DEFAULT_GROUNDING_PX = 768
DEFAULT_EDIT_ADAPTER_SCALE = 1.0


@dataclass(frozen=True)
class ReferenceGeometry:
    """Pixel crop/resize and RoPE placement for one edit reference.

    Krea 2's VAE downsamples by eight and its DiT patch size is two, so every
    reference-token cell corresponds to 16 source pixels.
    """

    crop_left: int
    crop_top: int
    crop_width: int
    crop_height: int
    output_width: int
    output_height: int
    token_width: int
    token_height: int
    offset_x: float
    offset_y: float
    fit_mode: str


def reference_geometry(source_width, source_height, target_width, target_height,
                       fit_mode="fit"):
    """Return the v1.2 training-matched source geometry.

    ``fit`` preserves a genuinely different source aspect ratio and places its
    token grid at a centered (possibly half-token) RoPE offset.  Near-matched
    ratios use a tiny centered crop so no uncovered one-token edge band is
    manufactured.  ``crop`` is the v1/v1.1 legacy fill geometry.
    """
    values = (source_width, source_height, target_width, target_height)
    if any(isinstance(value, bool) for value in values):
        raise ValueError("图片尺寸必须是正整数")
    try:
        source_width, source_height, target_width, target_height = map(int, values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("图片尺寸必须是正整数") from exc
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise ValueError("图片尺寸必须是正整数")
    if target_width % 16 or target_height % 16:
        raise ValueError("编辑输出尺寸必须是 16 的倍数")
    fit_mode = str(fit_mode or "fit").strip().lower()
    if fit_mode not in FIT_MODES:
        raise ValueError("未知参考图适配方式")

    if fit_mode == "crop":
        scale = max(target_height / source_height, target_width / source_width)
        crop_height = min(source_height, int(round(target_height / scale)))
        crop_width = min(source_width, int(round(target_width / scale)))
        left, top = ((source_width - crop_width) // 2,
                     (source_height - crop_height) // 2)
        return ReferenceGeometry(
            left, top, crop_width, crop_height, target_width, target_height,
            target_width // 16, target_height // 16, 0.0, 0.0, fit_mode)

    scale = min(target_height / source_height, target_width / source_width)
    # Match the upstream v1.2 node: small aspect-ratio differences fill the
    # output after a minimal center crop instead of leaving a 1-2 token margin.
    crop_tolerance = 0.08
    if (source_height * scale >= target_height * (1 - crop_tolerance)
            and source_width * scale >= target_width * (1 - crop_tolerance)):
        fill_scale = max(target_height / source_height, target_width / source_width)
        crop_height = min(source_height, int(round(target_height / fill_scale)))
        crop_width = min(source_width, int(round(target_width / fill_scale)))
        left, top = ((source_width - crop_width) // 2,
                     (source_height - crop_height) // 2)
        return ReferenceGeometry(
            left, top, crop_width, crop_height, target_width, target_height,
            target_width // 16, target_height // 16, 0.0, 0.0, fit_mode)

    output_height = min(
        max(16, math.floor(source_height * scale / 16) * 16), target_height)
    output_width = min(
        max(16, math.floor(source_width * scale / 16) * 16), target_width)
    # Crop to the exact scale before resize.  Directly squashing to the /16
    # floor creates the visible doubled seam fixed by the upstream v1.2.4 node.
    crop_height = min(source_height, max(1, int(round(output_height / scale))))
    crop_width = min(source_width, max(1, int(round(output_width / scale))))
    left, top = ((source_width - crop_width) // 2,
                 (source_height - crop_height) // 2)
    token_height, token_width = output_height // 16, output_width // 16
    target_token_height, target_token_width = target_height // 16, target_width // 16
    return ReferenceGeometry(
        left, top, crop_width, crop_height, output_width, output_height,
        token_width, token_height,
        (target_token_width - token_width) / 2,
        (target_token_height - token_height) / 2,
        fit_mode,
    )


__all__ = [
    "DEFAULT_EDIT_ADAPTER_SCALE",
    "DEFAULT_GROUNDING_PX",
    "DEFAULT_REFERENCE_STRENGTH",
    "EDIT_MODE",
    "FIT_MODES",
    "MODES",
    "ReferenceGeometry",
    "STANDARD_MODE",
    "reference_geometry",
]
