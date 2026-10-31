"""Zero-offset edit alignment: crop one reference to a Qwen resize fixed point.

The pinned edit pipeline resizes every reference to ``dimensions(1024, ratio)``.
A reference already at such a size stays untouched there, so its latent grid
matches an output of the same size. Pillow only; no HTTP, task or MLX access.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageOps

from .profiles import dimensions

MIN_SIZE, MAX_SIZE, STEP = 256, 2048, 32


def fixed_point_size(width, height, resolution=1024):
    """Return the fixed-point size whose ratio is closest to the source."""
    if width <= 0 or height <= 0:
        raise ValueError("参考图尺寸无效")
    target = math.log(width / height)
    best, best_score = None, None
    for candidate_w in range(MIN_SIZE, MAX_SIZE + STEP, STEP):
        for candidate_h in range(MIN_SIZE, MAX_SIZE + STEP, STEP):
            if dimensions(f"{candidate_w}:{candidate_h}", resolution) != (candidate_w, candidate_h):
                continue
            score = (abs(math.log(candidate_w / candidate_h) - target),
                     abs(candidate_w * candidate_h - resolution * resolution))
            if best_score is None or score < best_score:
                best, best_score = (candidate_w, candidate_h), score
    if best is None:
        raise ValueError("无法为参考图计算零偏移尺寸")
    return best


def crop_box(width, height, target_width, target_height):
    """Centered source-pixel box with the target ratio. Floats keep it exact."""
    scale = min(width / target_width, height / target_height)
    crop_width, crop_height = target_width * scale, target_height * scale
    left, top = (width - crop_width) / 2, (height - crop_height) / 2
    return left, top, left + crop_width, top + crop_height


def align_reference(source, destination, resolution=1024):
    """Write the aligned PNG and return JSON-safe mapping back to the source."""
    with Image.open(Path(source)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
    width, height = image.size
    target_width, target_height = fixed_point_size(width, height, resolution)
    box = crop_box(width, height, target_width, target_height)
    aligned = image.resize((target_width, target_height), Image.Resampling.LANCZOS, box=box)
    aligned.save(Path(destination), format="PNG")
    kept = (box[2] - box[0]) * (box[3] - box[1]) / (width * height)
    return {"source_width": width, "source_height": height, "crop_box": list(box),
            "width": target_width, "height": target_height,
            "cropped_percent": round((1 - kept) * 100, 2)}
