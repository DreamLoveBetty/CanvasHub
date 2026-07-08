#!/usr/bin/env python3
"""Shared helpers for requested-vs-actual image resolution metadata."""

from __future__ import annotations

import re
from typing import Any


def _positive_int(value: Any) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def normalize_resolution_label(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    compact = raw.replace(" ", "")
    aliases = {
        "standard": "1k",
        "normal": "1k",
        "low": "1k",
        "medium": "2k",
        "hd": "4k",
        "high": "4k",
    }
    if compact in aliases:
        return aliases[compact]
    if compact in {"1k", "2k", "4k"}:
        return compact
    match = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", raw)
    if match:
        return infer_resolution_label(match.group(1), match.group(2))
    return ""


def infer_resolution_label(width: Any, height: Any) -> str:
    longest = max(_positive_int(width), _positive_int(height))
    if longest >= 3600:
        return "4k"
    if longest >= 1800:
        return "2k"
    if longest >= 900:
        return "1k"
    return ""


def normalize_size(value: Any) -> dict[str, int] | None:
    if isinstance(value, dict):
        width = _positive_int(value.get("width") or value.get("w"))
        height = _positive_int(value.get("height") or value.get("h"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        width = _positive_int(value[0])
        height = _positive_int(value[1])
    else:
        match = re.search(r"(\d{1,5})\s*[x×]\s*(\d{1,5})", str(value or ""))
        if not match:
            return None
        width = _positive_int(match.group(1))
        height = _positive_int(match.group(2))
    if not width or not height:
        return None
    return {"width": width, "height": height}


def normalize_actual_sizes(value: Any) -> list[dict[str, int]]:
    items = value if isinstance(value, list) else ([value] if value else [])
    sizes: list[dict[str, int]] = []
    for item in items:
        size = normalize_size(item)
        if size:
            sizes.append(size)
    return sizes


def size_string(value: Any) -> str:
    size = normalize_size(value)
    return f"{size['width']}x{size['height']}" if size else str(value or "").strip()


def build_resolution_metadata(
    requested_resolution: Any,
    actual_sizes: Any,
    requested_size: Any = "",
) -> dict[str, Any]:
    requested_label = (
        normalize_resolution_label(requested_resolution)
        or normalize_resolution_label(requested_size)
    )
    sizes = normalize_actual_sizes(actual_sizes)
    primary = sizes[0] if sizes else None
    actual_label = infer_resolution_label(primary["width"], primary["height"]) if primary else ""
    actual_resolutions = [
        infer_resolution_label(item["width"], item["height"])
        for item in sizes
    ]
    actual_resolutions = [item for item in actual_resolutions if item]
    effective_label = actual_label or requested_label
    metadata: dict[str, Any] = {
        "requested_resolution": requested_label,
        "actual_resolution": actual_label,
        "actual_resolutions": actual_resolutions,
        "effective_resolution": effective_label,
        "resolution_mismatch": bool(actual_label and requested_label and actual_label != requested_label),
        "actual_sizes": sizes,
    }
    if requested_size not in (None, ""):
        metadata["requested_size"] = size_string(requested_size)
    if primary:
        width = primary["width"]
        height = primary["height"]
        metadata.update(
            {
                "actual_width": width,
                "actual_height": height,
                "actual_size": f"{width}x{height}",
                "actual_megapixels": round((width * height) / 1_000_000, 2),
            }
        )
    return metadata
