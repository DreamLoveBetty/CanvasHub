from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter


ALPHA_CORE_THRESHOLD = 16
ALPHA_GROUP_FILTER_SIZE = 5
MAX_REGION_LAYERS = 15
MIN_CORE_PIXELS = 32
MIN_TRANSPARENT_FRACTION = 0.005


@dataclass
class _AlphaComponent:
    runs: list[tuple[int, int, int]]
    mask_bbox: tuple[int, int, int, int]
    source_bbox: tuple[int, int, int, int]
    core_pixels: int
    visible_pixels: int
    alpha_sum: int


@dataclass
class TransparentLayerSet:
    composite_path: Path
    source_path: Path
    layer_paths: list[tuple[Path, str]]
    layer_records: list[dict[str, Any]]
    stats: dict[str, Any]


def _connected_component_runs(mask: Image.Image) -> list[list[tuple[int, int, int]]]:
    width, height = mask.size
    pixels = memoryview(mask.tobytes())
    parents: list[int] = []
    all_runs: list[tuple[int, int, int, int]] = []
    previous: list[tuple[int, int, int]] = []

    def new_label() -> int:
        label = len(parents)
        parents.append(label)
        return label

    def find(label: int) -> int:
        while parents[label] != label:
            parents[label] = parents[parents[label]]
            label = parents[label]
        return label

    def union(first: int, second: int) -> int:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parents[second_root] = first_root
        return first_root

    for y in range(height):
        offset = y * width
        current: list[tuple[int, int, int]] = []
        previous_index = 0
        x = 0
        while x < width:
            while x < width and pixels[offset + x] == 0:
                x += 1
            if x >= width:
                break
            start = x
            while x < width and pixels[offset + x] != 0:
                x += 1
            end = x - 1

            while previous_index < len(previous) and previous[previous_index][1] < start - 1:
                previous_index += 1
            overlapping: list[int] = []
            probe = previous_index
            while probe < len(previous) and previous[probe][0] <= end + 1:
                overlapping.append(previous[probe][2])
                probe += 1

            label = overlapping[0] if overlapping else new_label()
            for other in overlapping[1:]:
                union(label, other)
            current.append((start, end, label))
            all_runs.append((y, start, end, label))
        previous = current

    components: dict[int, list[tuple[int, int, int]]] = {}
    for y, start, end, label in all_runs:
        components.setdefault(find(label), []).append((y, start, end))
    return list(components.values())


def _runs_bbox(runs: list[tuple[int, int, int]]) -> tuple[int, int, int, int]:
    return (
        min(start for _, start, _ in runs),
        runs[0][0],
        max(end for _, _, end in runs) + 1,
        runs[-1][0] + 1,
    )


def _mask_from_runs(
    runs: list[tuple[int, int, int]],
    bbox: tuple[int, int, int, int],
) -> Image.Image:
    left, top, right, bottom = bbox
    width = right - left
    payload = bytearray(width * (bottom - top))
    for y, start, end in runs:
        row_start = (y - top) * width + start - left
        payload[row_start : row_start + end - start + 1] = b"\xff" * (end - start + 1)
    return Image.frombytes("L", (width, bottom - top), bytes(payload))


def _component_from_runs(
    runs: list[tuple[int, int, int]],
    alpha: Image.Image,
    core_threshold: int,
) -> _AlphaComponent | None:
    bbox = _runs_bbox(runs)
    mask = _mask_from_runs(runs, bbox)
    selected_alpha = ImageChops.multiply(alpha.crop(bbox), mask)
    relative_bbox = selected_alpha.getbbox()
    if not relative_bbox:
        return None
    left, top, _, _ = bbox
    source_bbox = (
        left + relative_bbox[0],
        top + relative_bbox[1],
        left + relative_bbox[2],
        top + relative_bbox[3],
    )
    histogram = selected_alpha.histogram()
    return _AlphaComponent(
        runs=runs,
        mask_bbox=bbox,
        source_bbox=source_bbox,
        core_pixels=sum(histogram[core_threshold:]),
        visible_pixels=sum(histogram[1:]),
        alpha_sum=sum(value * count for value, count in enumerate(histogram)),
    )


def _bbox_distance(
    first: tuple[int, int, int, int],
    second: tuple[int, int, int, int],
) -> tuple[int, int]:
    horizontal = max(first[0] - second[2], second[0] - first[2], 0)
    vertical = max(first[1] - second[3], second[1] - first[3], 0)
    first_center = ((first[0] + first[2]) // 2, (first[1] + first[3]) // 2)
    second_center = ((second[0] + second[2]) // 2, (second[1] + second[3]) // 2)
    center_distance = (first_center[0] - second_center[0]) ** 2 + (first_center[1] - second_center[1]) ** 2
    return horizontal * horizontal + vertical * vertical, center_distance


def _group_components(
    components: list[_AlphaComponent],
    canvas_area: int,
    max_region_layers: int,
) -> list[list[_AlphaComponent]]:
    if not components:
        return []
    ranked = sorted(components, key=lambda item: (item.core_pixels, item.alpha_sum), reverse=True)
    minimum_anchor_pixels = max(MIN_CORE_PIXELS, round(canvas_area * 0.0005))
    candidates = [item for item in ranked if item.core_pixels >= minimum_anchor_pixels]
    if len(candidates) < min(2, len(ranked)):
        candidates = ranked[: min(2, len(ranked))]
    anchors = candidates[: max(1, min(max_region_layers, len(candidates)))]
    groups: dict[int, list[_AlphaComponent]] = {id(anchor): [anchor] for anchor in anchors}
    anchor_ids = set(groups)
    for component in ranked:
        if id(component) in anchor_ids:
            continue
        nearest = min(anchors, key=lambda anchor: _bbox_distance(component.source_bbox, anchor.source_bbox))
        groups[id(nearest)].append(component)
    return list(groups.values())


def _layer_from_group(
    source: Image.Image,
    group: list[_AlphaComponent],
) -> tuple[Image.Image, tuple[int, int, int, int], int, int]:
    runs = [run for component in group for run in component.runs]
    bbox = _runs_bbox(sorted(runs))
    mask = _mask_from_runs(runs, bbox)
    selected_alpha = ImageChops.multiply(source.getchannel("A").crop(bbox), mask)
    relative_bbox = selected_alpha.getbbox()
    if not relative_bbox:
        raise RuntimeError("alpha component group did not contain visible source pixels")
    left, top, _, _ = bbox
    actual_bbox = (
        left + relative_bbox[0],
        top + relative_bbox[1],
        left + relative_bbox[2],
        top + relative_bbox[3],
    )
    selected_alpha = selected_alpha.crop(relative_bbox)
    layer_crop = source.crop(actual_bbox)
    layer_crop.putalpha(selected_alpha)
    histogram = selected_alpha.histogram()
    return layer_crop, actual_bbox, sum(histogram[1:]), sum(value * count for value, count in enumerate(histogram))


def _save_full_canvas_layer(
    layer_crop: Image.Image,
    bbox: tuple[int, int, int, int],
    canvas_size: tuple[int, int],
    path: Path,
) -> Image.Image:
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    layer.paste(layer_crop, (bbox[0], bbox[1]))
    layer.save(path, "PNG")
    return layer


def write_transparent_layers(
    image_data: bytes,
    output_dir: Path,
    *,
    core_threshold: int = ALPHA_CORE_THRESHOLD,
    group_filter_size: int = ALPHA_GROUP_FILTER_SIZE,
    max_region_layers: int = MAX_REGION_LAYERS,
) -> TransparentLayerSet:
    output_dir.mkdir(parents=True, exist_ok=True)
    loaded = Image.open(BytesIO(image_data))
    loaded.load()
    if str(loaded.format or "").upper() != "PNG":
        raise RuntimeError("ChatGPT did not return a PNG image")
    if "A" not in loaded.getbands() and "transparency" not in loaded.info:
        raise RuntimeError("ChatGPT PNG does not contain an alpha channel")

    source = Image.alpha_composite(Image.new("RGBA", loaded.size, (0, 0, 0, 0)), loaded.convert("RGBA"))
    alpha = source.getchannel("A")
    histogram = alpha.histogram()
    canvas_area = source.width * source.height
    transparent_pixels = histogram[0]
    visible_pixels = sum(histogram[1:])
    core_pixels = sum(histogram[core_threshold:])
    if visible_pixels < MIN_CORE_PIXELS or core_pixels < MIN_CORE_PIXELS:
        raise RuntimeError("ChatGPT PNG does not contain enough visible alpha content")
    if transparent_pixels / max(1, canvas_area) < MIN_TRANSPARENT_FRACTION:
        raise RuntimeError("ChatGPT PNG background is not truly transparent")

    core = alpha.point(lambda value: 255 if value >= core_threshold else 0)
    grouped_mask = core.filter(ImageFilter.MaxFilter(group_filter_size))
    raw_components = [
        component
        for runs in _connected_component_runs(grouped_mask)
        if (component := _component_from_runs(runs, alpha, core_threshold)) is not None
    ]
    if not raw_components:
        raise RuntimeError("ChatGPT transparent PNG does not contain a detectable visible region")
    component_groups = _group_components(raw_components, canvas_area, max_region_layers)

    assigned = bytearray(canvas_area)
    group_payloads: list[tuple[Image.Image, tuple[int, int, int, int], int, int, int]] = []
    for group in component_groups:
        for component in group:
            for y, start, end in component.runs:
                row_start = y * source.width + start
                assigned[row_start : row_start + end - start + 1] = b"\xff" * (end - start + 1)
        layer_crop, bbox, layer_pixels, alpha_sum = _layer_from_group(source, group)
        group_payloads.append((layer_crop, bbox, layer_pixels, alpha_sum, len(group)))
    group_payloads.sort(key=lambda item: (item[1][1], item[1][0], item[1][3], item[1][2]))

    layer_drafts: list[dict[str, Any]] = []
    assigned_mask = Image.frombytes("L", source.size, bytes(assigned))
    residual_alpha = ImageChops.multiply(alpha, ImageChops.invert(assigned_mask))
    residual_bbox = residual_alpha.getbbox()
    if residual_bbox:
        residual_crop = source.crop(residual_bbox)
        residual_crop.putalpha(residual_alpha.crop(residual_bbox))
        residual_histogram = residual_crop.getchannel("A").histogram()
        layer_drafts.append(
            {
                "label": "LOW_ALPHA_RESIDUAL",
                "description": "Visible low-alpha pixels outside the detected region cores",
                "crop": residual_crop,
                "bbox": residual_bbox,
                "visible_pixels": sum(residual_histogram[1:]),
                "alpha_sum": sum(value * count for value, count in enumerate(residual_histogram)),
                "component_count": 0,
            }
        )
    for region_index, (layer_crop, bbox, layer_pixels, alpha_sum, component_count) in enumerate(group_payloads, start=1):
        layer_drafts.append(
            {
                "label": f"REGION_{region_index:02d}",
                "description": f"Alpha-connected visible region group {region_index}",
                "crop": layer_crop,
                "bbox": bbox,
                "visible_pixels": layer_pixels,
                "alpha_sum": alpha_sum,
                "component_count": component_count,
            }
        )
    if not layer_drafts:
        raise RuntimeError("transparent alpha split did not produce an editable layer")

    layers_dir = output_dir / "layers"
    layers_dir.mkdir(parents=True, exist_ok=True)
    layer_paths: list[tuple[Path, str]] = []
    layer_records: list[dict[str, Any]] = []
    reconstructed = Image.new("RGBA", source.size, (0, 0, 0, 0))
    for index, draft in enumerate(layer_drafts, start=1):
        label = str(draft["label"])
        path = layers_dir / f"{index:02d}_{label}.png"
        layer = _save_full_canvas_layer(draft["crop"], draft["bbox"], source.size, path)
        reconstructed = Image.alpha_composite(reconstructed, layer)
        left, top, right, bottom = draft["bbox"]
        layer_records.append(
            {
                "index": index,
                "name": label,
                "description": str(draft["description"]),
                "file": f"layers/{path.name}",
                "coverage": round(float(draft["alpha_sum"]) / max(1, 255 * canvas_area), 6),
                "visible_pixel_count": int(draft["visible_pixels"]),
                "component_count": int(draft["component_count"]),
                "placement": {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                },
            }
        )
        layer_paths.append((path, f"{index:02d}_{label}"))

    if ImageChops.difference(reconstructed, source).getbbox() is not None:
        raise RuntimeError("alpha layers do not reconstruct the transparent PNG exactly")

    composite_path = output_dir / "composite_preview.png"
    source_path = output_dir / "generated_transparent.png"
    source.save(composite_path, "PNG")
    source.save(source_path, "PNG")
    stats = {
        "core_threshold": core_threshold,
        "group_filter_size": group_filter_size,
        "raw_component_count": len(raw_components),
        "region_layer_count": len(group_payloads),
        "residual_layer": bool(residual_bbox),
        "layer_count": len(layer_records),
        "transparent_pixel_fraction": round(transparent_pixels / max(1, canvas_area), 6),
        "low_alpha_pixel_fraction": round(sum(histogram[1:core_threshold]) / max(1, canvas_area), 6),
        "reconstruction_exact": True,
    }
    return TransparentLayerSet(
        composite_path=composite_path,
        source_path=source_path,
        layer_paths=layer_paths,
        layer_records=layer_records,
        stats=stats,
    )
