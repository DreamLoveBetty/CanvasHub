"""MOSS prompt and geometry compiler. Pure: no filesystem, GPU, network or model imports.

Box rounding and the final JSON follow the official `compile_prompt.py` (Apache-2.0, as
vendored in ComfyUI-MOSS-Storyboard 11b58a3). Deliberate differences: drafts are bounded by
the product limits, a free region cannot exceed MAX_FREE_REGIONS, and storyboards are built
from cell text instead of a hand-written draft.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

from .contracts import MAX_FREE_REGIONS, check_fields, integer, strict_json_loads, validate_size

SCHEMA = "canvashub.moss.layout"
SCHEMA_VERSION = 1
LABELS = ("object", "character", "text")
CANVAS_KINDS = ("single", "multi_panel", "collage")
GRIDS = {(1, 3), (3, 1), (2, 2), (2, 3), (3, 2), (2, 4), (4, 2), (3, 3)}
MAX_GRID_SPACING = 256
MIN_PANEL_EDGE = 256
DEFAULT_TEXT_CAPTION = "画面文字，清晰可读"
ITEM_FIELDS = {"id", "label", "caption", "bbox", "text", "tags", "palette"}
ITEM_SOURCES = {"text_source", "caption_source"}
PANEL_SOURCES = {"caption_source"}
_COUNT = r"\d+|[一二两三四五六七八九十]"
_STATED_COUNTS = (re.compile(rf"(?:恰好|正好|共)\s*({_COUNT})\s*(?:个|幅|张)?\s*(?:面板|分镜|格子|画格|格)"),
                  re.compile(rf"({_COUNT})\s*(?:个)?\s*宫格"),
                  re.compile(r"\b(\d+)\s+panels?\b", re.IGNORECASE))
_CHINESE_COUNTS = dict(zip("一二两三四五六七八九十", (1, 2, 2, 3, 4, 5, 6, 7, 8, 9, 10)))


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _filled(value):
    return isinstance(value, str) and bool(value.strip())


def _identifier(value, seen, name):
    if not _filled(value) or len(value) > 128:
        raise ValueError(f"{name} ID 无效")
    if value in seen:
        raise ValueError(f"{name} ID 重复：{value}")
    seen.add(value)


def _strings(value, name):
    if not isinstance(value, list) or not all(_filled(entry) for entry in value):
        raise ValueError(f"{name} 必须是非空文本列表")


def _summary(value, allowed):
    check_fields(value, allowed, "summary ")
    if "canvas" in value and value["canvas"] not in CANVAS_KINDS:
        raise ValueError("summary.canvas 无效")
    for key in ("meta", "palette"):
        if key in value:
            _strings(value[key], f"summary.{key}")
    return value


def _box(value, width, height):
    """Validate left-top pixel xyxy, then enclose it in centered yxyx pixels."""
    if not isinstance(value, list) or len(value) != 4 or not all(type(v) in (int, float) for v in value):
        raise ValueError("区域坐标必须是四个数字")
    x1, y1, x2, y2 = value
    # Range first: NaN fails every comparison, and JSON integers can exceed the float range.
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"区域超出 {width}×{height} 画幅或面积为零")
    return [math.floor(round(y1, 9)) - height // 2, math.floor(round(x1, 9)) - width // 2,
            math.ceil(round(y2, 9)) - height // 2, math.ceil(round(x2, 9)) - width // 2]


def _region_shape(raw, seen, width, height, allowed):
    check_fields(raw, allowed, "区域")
    _identifier(raw.get("id"), seen, "区域")
    if raw.get("label") not in LABELS:
        raise ValueError("区域类型无效")
    _box(raw.get("bbox"), width, height)
    for key in ("tags", "palette"):
        if key in raw:
            _strings(raw[key], f"区域 {key}")
    if not isinstance(raw.get("caption", ""), str) or not isinstance(raw.get("text", ""), str):
        raise ValueError("区域文字必须是文本")


def _region_content(raw, *, text_bound=False, caption_bound=False):
    if raw["label"] == "text":
        if not text_bound and not _filled(raw.get("text")):
            raise ValueError("文字区域须填写实际文案")
    elif not caption_bound and not _filled(raw.get("caption")):
        raise ValueError("物体或人物区域须填写描述")


def _compile_free(width, height, draft, prompt):
    check_fields(draft, {"items", "summary"}, "布局草稿")
    items = draft.get("items")
    if not _filled(prompt):
        raise ValueError("自由 Layout 须填写全局描述")
    if not isinstance(items, list) or not items:
        raise ValueError("自由 Layout 至少需要一个区域")
    if len(items) > MAX_FREE_REGIONS:
        raise ValueError(f"自由 Layout 最多 {MAX_FREE_REGIONS} 个区域")
    seen, compiled = set(), []
    for raw in items:
        _region_shape(raw, seen, width, height, ITEM_FIELDS)
        _region_content(raw)
        caption = raw.get("caption", "")
        entry = {"label": raw["label"], "caption": caption if _filled(caption) else DEFAULT_TEXT_CAPTION,
                 "bbox": _box(raw["bbox"], width, height)}
        compiled.append({**entry, **{key: raw[key] for key in ("text", "tags", "palette") if key in raw}})
    summary = _summary(draft.get("summary", {}), {"meta", "canvas", "palette"})
    return _canonical({"summary": {"caption": prompt, **summary}, "items": compiled,
                       "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}), None, []


def _partition(total, parts, margin, gutter):
    """Pixel spans along one axis; the remainder goes to the leading cells, one pixel each."""
    usable = total - 2 * margin - (parts - 1) * gutter
    if usable < parts:
        raise ValueError("边距和间隔过大，分格没有面积")
    base, extra = divmod(usable, parts)
    spans, start = [], margin
    for index in range(parts):
        end = start + base + (index < extra)
        spans.append((start, end))
        start = end + gutter
    return spans


def _grid_shape(raw):
    rows, cols = raw.get("rows"), raw.get("cols")
    if type(rows) is not int or type(cols) is not int or (rows, cols) not in GRIDS:
        raise ValueError("不支持的分镜行列")
    integer(raw.get("margin"), "边距", 0, MAX_GRID_SPACING)
    integer(raw.get("gutter"), "间隔", 0, MAX_GRID_SPACING)


def grid_geometry(width, height, rows, cols, margin, gutter, panel_ids):
    """The single geometry used by compile, preview, crop and overlay."""
    _grid_shape({"rows": rows, "cols": cols, "margin": margin, "gutter": gutter})
    if len(panel_ids) != rows * cols:
        raise ValueError(f"分镜格数应为 {rows * cols}")
    seen = set()
    for panel_id in panel_ids:
        _identifier(panel_id, seen, "分镜")
    xs, ys = _partition(width, cols, margin, gutter), _partition(height, rows, margin, gutter)
    boxes = [[x1, y1, x2, y2] for y1, y2 in ys for x1, x2 in xs]
    panels = [{"panel_id": panel_id, "index": index, "bbox": box}
              for index, (panel_id, box) in enumerate(zip(panel_ids, boxes))]
    return {"width": width, "height": height, "rows": rows, "cols": cols, "margin": margin, "gutter": gutter,
            "panels": panels}


def _stated_count(text):
    for pattern in _STATED_COUNTS:
        match = pattern.search(text)
        if match:
            value = match.group(1)
            return int(value) if value.isdigit() else _CHINESE_COUNTS[value]
    return None


def _compile_storyboard(width, height, draft, prompt):
    check_fields(draft, {"rows", "cols", "margin", "gutter", "panels", "summary"}, "分镜草稿")
    _grid_shape(draft)
    panels = draft.get("panels")
    if not isinstance(panels, list):
        raise ValueError(f"分镜格数应为 {draft['rows'] * draft['cols']}")
    for raw in panels:
        check_fields(raw, {"id", "caption"}, "分镜")
    spec = grid_geometry(width, height, draft["rows"], draft["cols"], draft["margin"], draft["gutter"],
                         [raw.get("id") for raw in panels])
    for index, raw in enumerate(panels):
        if not _filled(raw.get("caption")):
            raise ValueError(f"第 {index + 1} 格须填写描述")
    summary = _summary(draft.get("summary", {}), {"meta", "palette"})
    count = draft["rows"] * draft["cols"]
    # The declaration is what makes MOSS divide the page; it is not user-editable.
    caption = f"单一画布，严格对称 {draft['rows']}×{draft['cols']} 网格，恰好 {count} 个面板，细白线分隔"
    if _filled(prompt):
        caption = f"{caption}；{prompt}"
    items = [{"label": "object", "caption": raw["caption"], "bbox": _box(panel["bbox"], width, height)}
             for raw, panel in zip(panels, spec["panels"])]
    warnings = []
    stated = _stated_count(prompt)
    if stated is not None and stated != count:
        warnings.append({"code": "panel_count_conflict", "message": f"全局描述写了 {stated} 格，当前布局是 {count} 格"})
    edge = min(min(box[2] - box[0], box[3] - box[1]) for box in (panel["bbox"] for panel in spec["panels"]))
    if edge < MIN_PANEL_EDGE:
        warnings.append({"code": "small_panels", "message": f"单格短边只有 {edge}px，细节可能不足"})
    return _canonical({"summary": {"caption": caption, **summary}, "items": items,
                       "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}), spec, warnings


def compile_layout(mode, width, height, draft, global_prompt):
    if mode == "text":
        prompt, spec, warnings = global_prompt, None, []
    elif mode == "layout":
        prompt, spec, warnings = _compile_free(width, height, draft, global_prompt)
    elif mode == "storyboard":
        prompt, spec, warnings = _compile_storyboard(width, height, draft, global_prompt)
    else:
        raise ValueError("未知 MOSS 工作模式")
    return {"prompt": prompt, "prompt_hash": _hash(prompt), "geometry_spec": spec,
            "geometry_hash": _hash(_canonical(spec)) if spec else None, "warnings": warnings}


def _source(value):
    """Validate a ContentSource and report whether it names a text node; nodes are never looked up here."""
    if not isinstance(value, dict) or value.get("kind") not in ("inline", "text_node"):
        raise ValueError("文本来源无效")
    if value["kind"] == "inline":
        check_fields(value, {"kind"}, "文本来源")
        return False
    check_fields(value, {"kind", "node_id"}, "文本来源")
    if not _filled(value.get("node_id")) or len(value["node_id"]) > 128:
        raise ValueError("文本来源节点无效")
    return True


def _own_free(draft, width, height, active):
    check_fields(draft, {"items", "summary"}, "free_draft")
    _summary(draft.get("summary", {}), {"meta", "canvas", "palette"})
    items = draft.get("items")
    if not isinstance(items, list) or len(items) > MAX_FREE_REGIONS:
        raise ValueError(f"自由 Layout 最多 {MAX_FREE_REGIONS} 个区域")
    seen, bound = set(), False
    for raw in items:
        _region_shape(raw, seen, width, height, ITEM_FIELDS | ITEM_SOURCES)
        text_bound = "text_source" in raw and _source(raw["text_source"])
        caption_bound = "caption_source" in raw and _source(raw["caption_source"])
        bound = bound or text_bound or caption_bound
        if active:
            _region_content(raw, text_bound=text_bound, caption_bound=caption_bound)
    return bound


def _own_grid(draft, width, height, active):
    check_fields(draft, {"rows", "cols", "margin", "gutter", "panels", "summary"}, "grid_draft")
    _grid_shape(draft)
    _summary(draft.get("summary", {}), {"meta", "palette"})
    panels = draft.get("panels")
    if not isinstance(panels, list):
        raise ValueError("分镜草稿无效")
    seen, bound = set(), False
    for index, raw in enumerate(panels):
        check_fields(raw, {"id", "caption"} | PANEL_SOURCES, "分镜")
        _identifier(raw.get("id"), seen, "分镜")
        if not isinstance(raw.get("caption", ""), str):
            raise ValueError("分镜描述必须是文本")
        caption_bound = "caption_source" in raw and _source(raw["caption_source"])
        bound = bound or caption_bound
        if active and not caption_bound and not _filled(raw.get("caption")):
            raise ValueError(f"第 {index + 1} 格须填写描述")
    if active:
        grid_geometry(width, height, draft["rows"], draft["cols"], draft["margin"], draft["gutter"],
                      [raw["id"] for raw in panels])
    return bound


def _import_own(raw):
    check_fields(raw, {"schema", "schema_version", "mode", "width", "height", "prompt", "prompt_source",
                       "free_draft", "grid_draft"}, "草稿包")
    if raw.get("schema_version") != SCHEMA_VERSION or type(raw.get("schema_version")) is not int:
        raise ValueError("不支持的草稿版本")
    mode = raw.get("mode")
    if mode not in ("text", "layout", "storyboard"):
        raise ValueError("未知 MOSS 工作模式")
    width, height = validate_size(raw.get("width"), raw.get("height"))
    prompt = raw.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("提示词必须是文本")
    bound = "prompt_source" in raw and _source(raw["prompt_source"])
    if mode != "storyboard" and not bound and not _filled(prompt):
        raise ValueError("草稿缺少全局描述")
    free, grid = raw.get("free_draft"), raw.get("grid_draft")
    if free is None and mode == "layout" or grid is None and mode == "storyboard":
        raise ValueError("草稿缺少当前模式的内容")
    if free is not None and _own_free(free, width, height, mode == "layout"):
        bound = True
    if grid is not None and _own_grid(grid, width, height, mode == "storyboard"):
        bound = True
    return raw, bound


def _import_official(raw):
    if "caption" in raw:
        check_fields(raw, {"caption"}, "官方草稿")
        if not _filled(raw["caption"]):
            raise ValueError("官方草稿缺少描述")
        return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "mode": "text", "width": 1024, "height": 1024,
                "prompt": raw["caption"], "prompt_source": {"kind": "inline"}}, False
    required = {"width", "height", "bbox_coord_space", "bbox_format", "summary", "items"}
    check_fields(raw, required, "官方草稿")
    if not required <= raw.keys():
        raise ValueError("无法识别的草稿格式")
    if raw["bbox_coord_space"] != "abs" or raw["bbox_format"] != "xyxy":
        raise ValueError("只能导入未编译的官方草稿")
    width, height = validate_size(raw["width"], raw["height"])
    check_fields(raw["summary"], {"caption", "meta", "canvas", "palette"}, "summary ")
    summary = dict(raw["summary"])
    prompt = summary.pop("caption", "")
    items = raw["items"]
    if not isinstance(items, list) or not items:
        raise ValueError("官方草稿至少需要一个区域")
    free = {"summary": summary, "items": [{"id": f"item-{index + 1}", **item} if isinstance(item, dict) else item
                                          for index, item in enumerate(items)]}
    compile_layout("layout", width, height, free, prompt)
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "mode": "layout", "width": width, "height": height,
            "prompt": prompt, "prompt_source": {"kind": "inline"}, "free_draft": free}, False


def import_draft(raw):
    """Validate original draft text. Sources stay references until the client resolves them and recompiles."""
    value = strict_json_loads(raw)
    draft, bound = _import_own(value) if value.get("schema") == SCHEMA else _import_official(value)
    return {"kind": "import_draft", "draft": draft, "requires_source_resolution": bound}
