"""Versioned, accelerator-free marker contract and deterministic rasterizer."""
from __future__ import annotations

import math

PROFILE = "editutils-area-v1"
IMPLEMENTATION = "canvashub-area-1"
PRESETS = {"flat": .0149, "small": .0294, "medium": .0322,
           "large": .0718, "huge": .1395, "gigantic": .1650}
REFERENCE_SIZES = (1024, 768, 512)


def normalize_reference_size(value):
    if type(value) is not int or value not in REFERENCE_SIZES:
        raise ValueError("控制图编码尺寸必须是 1024、768 或 512")
    return value


def prepare_control_images(image, reference_size=1024):
    """Resize VAE reference only; preserve area-384 VL input and output canvas.

    Right/bottom white padding and rounding match the original 1024 contract.
    Lower sizes are opt-in experiments, not equivalent conditioning.
    """
    from PIL import Image
    reference_size = normalize_reference_size(reference_size)
    width, height = image.size
    ratio = reference_size / max(width, height)
    rw, rh = max(1, round(width * ratio)), max(1, round(height * ratio))
    reference = Image.new("RGB", ((rw + 15)//16*16, (rh + 15)//16*16), "white")
    reference.paste(image.resize((rw, rh), Image.Resampling.LANCZOS), (0, 0))
    ratio = 384 / math.sqrt(width * height)
    vision = image.resize((round(width * ratio), round(height * ratio)), Image.Resampling.LANCZOS)
    return reference, vision


def normalize_control(value):
    if not isinstance(value, dict) or value.get("profile") != PROFILE:
        raise ValueError("未知 Krea 2 区域控制协议")
    circles = value.get("circles")
    if not isinstance(circles, list) or not 1 <= len(circles) <= 2:
        raise ValueError("区域控制需要 1–2 个椭圆标记")
    normalized = []
    for item in circles:
        if not isinstance(item, dict):
            raise ValueError("区域控制标记无效")
        circle = {}
        for key, lower, upper in (("cx", 0, 1), ("cy", 0, 1),
                                  ("rx", .001, 1), ("ry", .001, 1),
                                  ("angle", -180, 180)):
            try:
                raw = item.get(key, 0 if key == "angle" else None)
                number = float(raw)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(f"区域控制 {key} 无效") from exc
            if isinstance(raw, bool) or not math.isfinite(number) or not lower <= number <= upper:
                raise ValueError(f"区域控制 {key} 超出范围")
            circle[key] = number
        normalized.append(circle)
    return {"profile": PROFILE, "circles": normalized}


def render_control(value, width, height):
    """Pixel-centre ellipse union. Optional guide pixels NEVER enter output."""
    import numpy as np
    from PIL import Image

    value = normalize_control(value)
    if (type(width) is not int or type(height) is not int
            or not 256 <= width <= 2048 or not 256 <= height <= 2048
            or width % 16 or height % 16):
        raise ValueError("控制图尺寸须为 256–2048 的 16 倍数")
    yy, xx = np.ogrid[:height, :width]
    mask = np.zeros((height, width), dtype=bool)
    for circle in value["circles"]:
        x = xx + .5 - circle["cx"] * width
        y = yy + .5 - circle["cy"] * height
        radians = math.radians(circle["angle"])
        c, s = math.cos(radians), math.sin(radians)
        mask |= ((c*x + s*y)/(circle["rx"]*width))**2 + (
            (-s*x + c*y)/(circle["ry"]*height))**2 <= 1
    pixels = np.zeros((height, width, 3), dtype=np.uint8)
    pixels[mask] = (250, 219, 174)
    return Image.fromarray(pixels), {"coverage": float(mask.mean()),
                                     "implementation": IMPLEMENTATION}
