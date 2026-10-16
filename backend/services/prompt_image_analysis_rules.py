"""Image prompt-analysis normalization.

Turns a model's image-analysis JSON into the prompt contract: type flags, visual style
regions, subjects and overlays, text regions, placeholder slots, and the Chinese main /
universal-style / specialized / negative prompts. Pure functions and constants only;
image decoding (Pillow), the model call and the account-pool fallback stay in
prompt_skill_client.
"""

from __future__ import annotations

import re
from typing import Any

from .prompt_text_rules import (
    _as_dict,
    _as_list,
    _strip_code_fences,
    _has_han,
    _append_sentence_once,
)


NO_TEXT_CHINESE_CONSTRAINT = "画面无可读文字。"


IMAGE_ANALYSIS_SPECIALIZED_FLAGS = {
    "layout_prompt": "layout_design",
    "cover_template_prompt": "cover_template",
    "table_card_layout_prompt": "table_card",
    "web_design_style_prompt": "web_design",
}
IMAGE_ANALYSIS_FLAG_HINTS = {
    "layout_design": (
        "排版",
        "版式",
        "平面设计",
        "海报",
        "poster",
        "信息图",
        "infographic",
        "杂志",
        "画册",
        "宣传页",
        "广告图",
        "banner",
        "视觉层级",
        "图文布局",
    ),
    "cover_template": (
        "封面",
        "cover",
        "小红书",
        "缩略图",
        "thumbnail",
        "杂志封面",
        "书封",
        "专辑封面",
        "视频封面",
        "首图",
        "标题区",
    ),
    "table_card": (
        "表格",
        "table",
        "卡片",
        "card",
        "信息卡",
        "资料卡",
        "产品卡",
        "价格卡",
        "对比表",
        "图表",
        "chart",
        "dashboard",
        "仪表盘",
        "规格",
        "列表",
        "数据",
    ),
    "web_design": (
        "网页",
        "网站",
        "web",
        "landing",
        "官网",
        "页面",
        "ui",
        "界面",
        "app",
        "dashboard",
        "后台",
        "组件",
        "导航栏",
        "按钮",
        "hero",
    ),
}


def _clean_string(value: Any, limit: int = 8000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _data_image_parts(image_url: str) -> tuple[str, str] | None:
    match = re.match(r"^data:(image/[a-z0-9.+-]+);base64,(.*)$", str(image_url or "").strip(), re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return str(match.group(1) or "image/png").lower(), re.sub(r"\s+", "", str(match.group(2) or ""))


def _analysis_image_mime_type(image_url: str, fallback: str = "image/png") -> str:
    parts = _data_image_parts(image_url)
    if parts:
        return parts[0]
    return _clean_string(fallback or "image/png", 80) or "image/png"


def _first_text(data: dict[str, Any], *keys: str, limit: int = 8000) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return _clean_string(value, limit)
    return ""


def _build_image_analysis_user_prompt(message: str, images: list[dict[str, Any]]) -> str:
    primary = images[0]
    extra = images[1:]
    extra_lines = [
        f"- {item['id']}：{item.get('label') or item['id']}（仅记录为后续扩展输入，不参与首版文生图提示词）"
        for item in extra
    ]
    return "\n".join(
        part
        for part in [
            "请分析第一张输入图片，并输出用于提示词助手的结构化结果。",
            f"输入图片名称：{primary.get('label') or primary['id']}",
            "补充图片：\n" + "\n".join(extra_lines) if extra_lines else "",
            f"用户补充要求：\n{message}" if message else "用户补充要求：默认提取可独立用于文生图的视觉结构、风格、版式和可复用提示词。",
            "主候选必须默认不包含任何可读文字；如画面是海报、网页、表格、卡片，也只描述文字区域、信息层级和排版关系。",
            "请特别检查主体姿态/表情/手势/身体裁切，以及画面内的局部彩色图层、框选边框、控制点、鼠标指针、蒙版、几何叠加和前后景遮挡关系。",
            "请特别检查媒介与渲染语言及其作用范围：真实摄影、普通插画、扁平矢量、3D、像素风、动漫、水彩等必须区分；像素风要写清楚作用于主体/背景/物件还是也作用于文字。文字若是平滑粗体或干净矢量字体，不要写成像素字体。",
            "模块策略：通用风格提示词、负面提示词、图中文字 Markdown、完整 JSON 是全类型结果；排版布局、封面模板、表格/卡片、网页设计四类提示词只有在 image_type_flags 对应类型命中时才输出，未命中必须留空。",
        ]
        if part
    ).strip()


def _compose_no_text_prompt(blocks: dict[str, Any], data: dict[str, Any]) -> str:
    main = _first_text(blocks, "main_prompt_no_text", "main_prompt", "prompt", "完整提示词", limit=12000)
    if main:
        return _append_sentence_once(main, NO_TEXT_CHINESE_CONSTRAINT)

    pieces = [
        _first_text(data, "visual_summary", "summary", limit=1200),
        _first_text(blocks, "universal_style_prompt", "style_prompt", limit=2400),
        _first_text(blocks, "layout_prompt", "composition_prompt", limit=2400),
        _first_text(blocks, "cover_template_prompt", "template_prompt", limit=2000),
        _first_text(blocks, "table_card_layout_prompt", limit=1600),
        _first_text(blocks, "web_design_style_prompt", limit=1600),
    ]
    composed = "\n\n".join(piece for piece in pieces if piece).strip()
    if not composed:
        composed = "生成一张高质量文生图画面，采用清晰构图、统一风格、稳定色彩关系、明确光影质感、准确材质表现、丰富空间层级和自然视觉节奏。"
    negative = _first_text(blocks, "negative_prompt", "negative", limit=2000)
    no_text = _prefer_chinese_prompt(_first_text(blocks, "no_text_prompt", limit=1200), NO_TEXT_CHINESE_CONSTRAINT)
    if negative:
        composed = f"{composed}\n\n负面约束：{negative}"
    return _append_sentence_once(composed, no_text)


def _module_text(blocks: dict[str, Any], data: dict[str, Any], key: str, *fallback_keys: str) -> str:
    return _first_text(blocks, key, *fallback_keys, limit=12000) or _first_text(data, key, *fallback_keys, limit=12000)


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "y", "on", "命中", "是", "适用", "yes."}:
        return True
    if text in {"0", "false", "no", "n", "off", "未命中", "否", "不适用", "none"}:
        return False
    return None


def _has_image_analysis_hint(text: str, flag: str) -> bool:
    combined = str(text or "")
    lowered = combined.lower()
    return any(hint in combined or hint in lowered for hint in IMAGE_ANALYSIS_FLAG_HINTS.get(flag, ()))


def _normalize_image_type_flags(data: dict[str, Any], blocks: dict[str, Any]) -> dict[str, bool]:
    raw_flags = _as_dict(data.get("image_type_flags") or data.get("imageTypeFlags") or data.get("type_flags") or data.get("typeFlags"))
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    visual_summary = _first_text(data, "visual_summary", "summary", limit=2000)
    layout = _as_dict(data.get("layout"))
    generation_hints = _as_dict(data.get("generation_hints") or data.get("generationHints"))
    combined = " ".join(
        [
            image_kind,
            visual_summary,
            " ".join(str(value) for value in layout.values()),
            " ".join(str(value) for value in generation_hints.values()),
        ]
    )
    flags: dict[str, bool] = {}
    for flag in IMAGE_ANALYSIS_FLAG_HINTS:
        explicit = _boolish(raw_flags.get(flag))
        if explicit is None:
            explicit = _boolish(raw_flags.get(flag.replace("_", "")))
        flags[flag] = bool(explicit) if explicit is not None else _has_image_analysis_hint(combined, flag)

    # Web/UI screenshots are also layout designs, but not every layout design is a web page.
    if flags.get("web_design"):
        flags["layout_design"] = True
    if flags.get("cover_template"):
        flags["layout_design"] = True

    # If a legacy model omitted flags entirely, allow a non-empty specialized block to
    # rescue the obvious type. With explicit flags present, the flags win.
    if not raw_flags:
        for block_key, flag in IMAGE_ANALYSIS_SPECIALIZED_FLAGS.items():
            if _first_text(blocks, block_key, limit=400) and _has_image_analysis_hint(
                f"{combined} {_first_text(blocks, block_key, limit=1200)}",
                flag,
            ):
                flags[flag] = True
                if flag in {"cover_template", "web_design"}:
                    flags["layout_design"] = True
    return flags


def _compact_context_text(data: dict[str, Any]) -> str:
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    visual_summary = _first_text(data, "visual_summary", "summary", limit=600)
    return "，".join(part for part in [image_kind, visual_summary] if part)


REFERENCE_DEPENDENCY_MARKERS = (
    "参考图",
    "原图",
    "同款",
    "image1",
    "image 1",
    "以图生图",
    "图像编辑",
    "图片编辑",
    "改图",
    "基于图片",
    "基于这张图",
    "保留原",
)


def _has_reference_dependency(text: str) -> bool:
    cleaned = str(text or "")
    lowered = cleaned.lower()
    return any(marker in cleaned or marker in lowered for marker in REFERENCE_DEPENDENCY_MARKERS)


def _clean_standalone_context(text: str, limit: int = 900) -> str:
    cleaned = _clean_string(text, limit)
    if not cleaned:
        return ""
    replacements = (
        ("参考图同款", ""),
        ("参考图", "画面"),
        ("原图", "画面"),
        ("同款", ""),
        ("image1", ""),
        ("image 1", ""),
        ("以图生图", "文生图"),
        ("图像编辑", "图像生成"),
        ("图片编辑", "图像生成"),
        ("改图", "图像生成"),
        ("基于图片", "根据视觉描述"),
        ("基于这张图", "根据视觉描述"),
        ("保留原有", "采用"),
        ("保留原", "采用"),
    )
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[，、；：]\s*[，、；：]+", "，", cleaned)
    cleaned = re.sub(r"^[，、；：。.\s]+|[，、；：。.\s]+$", "", cleaned)
    return cleaned


def _standalone_context_text(data: dict[str, Any]) -> str:
    return _clean_standalone_context(_compact_context_text(data))


PIXEL_STYLE_MARKERS = (
    "像素",
    "pixel",
    "pixel art",
    "sprite",
    "8-bit",
    "8bit",
    "16-bit",
    "16bit",
    "低分辨率",
    "low-res",
    "low resolution",
    "方块",
    "块状",
    "阶梯",
    "锯齿",
    "tile",
    "tileset",
)


def _text_has_pixel_style(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in PIXEL_STYLE_MARKERS)


def _normalize_visual_style_regions(raw_style: dict[str, Any]) -> list[dict[str, str]]:
    raw_regions = (
        raw_style.get("style_regions")
        or raw_style.get("styleRegions")
        or raw_style.get("scoped_styles")
        or raw_style.get("scopedStyles")
        or raw_style.get("region_styles")
        or raw_style.get("regionStyles")
        or []
    )
    regions: list[dict[str, str]] = []
    for item in _as_list(raw_regions):
        if isinstance(item, dict):
            region = {
                "target": _clean_standalone_context(_first_text(item, "target", "area", "region", "scope", "applies_to", "appliesTo", limit=240), 240),
                "medium": _clean_standalone_context(_first_text(item, "medium", "style", limit=240), 240),
                "rendering": _clean_standalone_context(_first_text(item, "rendering", "render", limit=360), 360),
                "edge_quality": _clean_standalone_context(_first_text(item, "edge_quality", "edgeQuality", "edges", limit=240), 240),
                "texture": _clean_standalone_context(_first_text(item, "texture", "grain", limit=300), 300),
                "palette": _clean_standalone_context(_first_text(item, "palette", "color_palette", "colorPalette", limit=300), 300),
                "notes": _clean_standalone_context(_first_text(item, "notes", "description", "constraint", limit=420), 420),
            }
        else:
            region = {
                "target": "",
                "medium": "",
                "rendering": _clean_standalone_context(str(item), 360),
                "edge_quality": "",
                "texture": "",
                "palette": "",
                "notes": "",
            }
        if any(value for value in region.values()):
            regions.append(region)
    return regions[:10]


def _normalize_visual_style(data: dict[str, Any]) -> dict[str, Any]:
    raw_style = _as_dict(data.get("visual_style") or data.get("visualStyle") or data.get("style_profile") or data.get("styleProfile"))
    hints = _as_dict(data.get("generation_hints") or data.get("generationHints"))
    style_keywords = _as_list(raw_style.get("style_keywords") or raw_style.get("styleKeywords") or hints.get("style_keywords") or hints.get("styleKeywords"))
    normalized = {
        "medium": _clean_standalone_context(_first_text(raw_style, "medium", limit=300) or _first_text(hints, "medium", limit=300), 300),
        "rendering": _clean_standalone_context(_first_text(raw_style, "rendering", "render", limit=500) or _first_text(hints, "rendering", "render", limit=500), 500),
        "style_scope": _clean_standalone_context(_first_text(raw_style, "style_scope", "styleScope", "scope", "applies_to", "appliesTo", limit=500), 500),
        "subject_background_style": _clean_standalone_context(_first_text(raw_style, "subject_background_style", "subjectBackgroundStyle", "scene_style", "sceneStyle", limit=500), 500),
        "typography_style": _clean_standalone_context(_first_text(raw_style, "typography_style", "typographyStyle", "text_style", "textStyle", limit=500), 500),
        "text_style_is_pixelated": bool(_boolish(raw_style.get("text_style_is_pixelated") or raw_style.get("textStyleIsPixelated") or raw_style.get("pixelated_text") or raw_style.get("pixelatedText"))),
        "style_regions": _normalize_visual_style_regions(raw_style),
        "edge_quality": _clean_standalone_context(_first_text(raw_style, "edge_quality", "edgeQuality", "edges", limit=300), 300),
        "texture": _clean_standalone_context(_first_text(raw_style, "texture", "grain", limit=400), 400),
        "palette": _clean_standalone_context(_first_text(raw_style, "palette", "color_palette", "colorPalette", limit=500) or _first_text(hints, "palette", limit=500), 500),
        "resolution_language": _clean_standalone_context(_first_text(raw_style, "resolution_language", "resolutionLanguage", "resolution", limit=300), 300),
        "style_keywords": [
            _clean_standalone_context(str(item), 120)
            for item in style_keywords
            if str(item or "").strip()
        ][:12],
    }
    return normalized


def _visual_style_context_text(data: dict[str, Any]) -> str:
    style = _normalize_visual_style(data)
    # Keep this as the compact global style line only. Scope, subject/background,
    # typography, and region details are appended with labels by
    # _format_visual_style_prompt(); including them here duplicates the same
    # information and makes generated prompts repeat phrases such as “真实摄影”.
    parts = [
        style.get("medium"),
        style.get("rendering"),
        style.get("edge_quality"),
        style.get("texture"),
        style.get("palette"),
        style.get("resolution_language"),
        "，".join(style.get("style_keywords") or []),
    ]
    return "，".join(part for part in parts if part)


def _region_has_pixel_style(region: dict[str, str]) -> bool:
    positive_style_text = " ".join(
        str(region.get(key) or "")
        for key in ("medium", "rendering", "edge_quality", "texture", "palette")
    )
    return _text_has_pixel_style(positive_style_text)


def _has_pixel_style(data: dict[str, Any]) -> bool:
    style = _normalize_visual_style(data)
    base_context = " ".join(
        str(part or "")
        for part in [
            _first_text(data, "image_kind", "imageKind", limit=120),
            _first_text(data, "visual_summary", "summary", limit=1200),
            style.get("medium"),
            style.get("rendering"),
            style.get("style_scope"),
            style.get("subject_background_style"),
            style.get("edge_quality"),
            style.get("texture"),
            style.get("palette"),
            style.get("resolution_language"),
            " ".join(style.get("style_keywords") or []),
            " ".join(str(value) for value in _as_dict(data.get("generation_hints") or data.get("generationHints")).values()),
        ]
    )
    return _text_has_pixel_style(base_context) or any(_region_has_pixel_style(region) for region in style.get("style_regions") or [])


def _format_visual_style_regions(style: dict[str, Any]) -> str:
    lines: list[str] = []
    global_medium = str(style.get("medium") or "").strip()
    for region in style.get("style_regions") or []:
        region_medium = str(region.get("medium") or "").strip()
        parts = [
            "" if region_medium and region_medium == global_medium else region_medium,
            region.get("rendering"),
            region.get("edge_quality"),
            region.get("texture"),
            region.get("palette"),
            region.get("notes"),
        ]
        detail = "，".join(part for part in dict.fromkeys(parts) if part)
        target = region.get("target") or "局部区域"
        if not detail:
            continue
        if _region_has_pixel_style(region):
            detail = f"{detail}，该区域保留清晰方块像素、低分辨率像素网格、硬边无柔化抗锯齿、阶梯状斜线、有限色板、块状阴影和 sprite/tile-like 结构"
        lines.append(f"{target}：{detail}")
    return "；".join(lines)


def _format_visual_style_prompt(data: dict[str, Any]) -> str:
    style = _normalize_visual_style(data)
    style_context = _visual_style_context_text(data)
    region_text = _format_visual_style_regions(style)
    if not style_context and not region_text and not _has_pixel_style(data):
        return ""
    scope_parts = []
    if style.get("style_scope"):
        scope_parts.append(f"整体作用范围：{style['style_scope']}")
    if style.get("subject_background_style"):
        scope_parts.append(f"主体/背景：{style['subject_background_style']}")
    if region_text:
        scope_parts.append(f"区域风格：{region_text}")
    typography_style = style.get("typography_style") or ""
    if typography_style:
        scope_parts.append(f"文字/标题：{typography_style}")
    if _has_pixel_style(data) and not style.get("text_style_is_pixelated"):
        scope_parts.append("文字/标题按 text_regions 的字体风格独立处理，未明确为像素字体时不要强制像素化")
    elif style.get("text_style_is_pixelated"):
        scope_parts.append("文字也识别为像素/位图字体时才使用像素字体边缘")
    details = "；".join(part for part in scope_parts if part)
    if style_context and details:
        return f"媒介与渲染：{style_context}；{details}。"
    if details:
        return f"媒介与渲染：{details}。"
    return f"媒介与渲染：{style_context}。"


def _normalize_subjects(data: dict[str, Any]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(_as_list(data.get("subjects") or data.get("subject_details") or data.get("subjectDetails"))):
        if isinstance(item, dict):
            outfit_parts = [
                _clean_standalone_context(_first_text(item, "outfit", "styling", "clothing", "costume", "wardrobe", limit=500), 500),
                _clean_standalone_context(_first_text(item, "outfit_details", "outfitDetails", "clothing_details", "clothingDetails", "costume_details", "costumeDetails", limit=500), 500),
                _clean_standalone_context(_first_text(item, "top", "upper_body_clothing", "upperBodyClothing", "shirt", "outerwear", limit=240), 240),
                _clean_standalone_context(_first_text(item, "bottom", "lower_body_clothing", "lowerBodyClothing", "skirt", "pants", limit=240), 240),
                _clean_standalone_context(_first_text(item, "legwear", "hosiery", "tights", "pantyhose", "stockings", "socks", "袜装", "腿部覆盖物", limit=260), 260),
                _clean_standalone_context(_first_text(item, "footwear", "shoes", "boots", "鞋履", limit=220), 220),
            ]
            outfit = "，".join(part for part in dict.fromkeys(outfit_parts) if part)
            subject = {
                "name": _clean_standalone_context(_first_text(item, "name", "title", limit=120), 120) or f"主体{index + 1}",
                "role": _clean_standalone_context(_first_text(item, "role", limit=160), 160),
                "visual_traits": _clean_standalone_context(_first_text(item, "visual_traits", "visualTraits", "traits", limit=500), 500),
                "pose": _clean_standalone_context(_first_text(item, "pose", "action", "gesture", limit=500), 500),
                "expression": _clean_standalone_context(_first_text(item, "expression", "mood", limit=300), 300),
                "gaze": _clean_standalone_context(_first_text(item, "gaze", "view_direction", "viewDirection", limit=240), 240),
                "body_crop": _clean_standalone_context(_first_text(item, "body_crop", "bodyCrop", "crop", "framing", limit=300), 300),
                "outfit": _clean_standalone_context(outfit, 900),
                "makeup_hair": _clean_standalone_context(_first_text(item, "makeup_hair", "makeupHair", "hair_makeup", "hairMakeup", "hairstyle", "hair", "makeup", "妆发", limit=600), 600),
                "accessories": _clean_standalone_context(_first_text(item, "accessories", "props", "jewelry", "headwear", "hair_accessories", "hairAccessories", "配饰", limit=500), 500),
                "placement": _clean_standalone_context(_first_text(item, "placement", "position", limit=300), 300),
                "relationship": _clean_standalone_context(_first_text(item, "relationship", "relation", limit=500), 500),
            }
        else:
            subject = {
                "name": f"主体{index + 1}",
                "role": "",
                "visual_traits": _clean_standalone_context(str(item), 500),
                "pose": "",
                "expression": "",
                "gaze": "",
                "body_crop": "",
                "outfit": "",
                "makeup_hair": "",
                "accessories": "",
                "placement": "",
                "relationship": "",
            }
        if any(value for key, value in subject.items() if key != "name"):
            normalized.append(subject)
    return normalized[:6]


def _normalize_overlay_elements(data: dict[str, Any]) -> list[dict[str, str]]:
    raw = (
        data.get("overlays")
        or data.get("overlay_elements")
        or data.get("overlayElements")
        or data.get("graphic_overlays")
        or data.get("graphicOverlays")
        or data.get("foreground_overlays")
        or data.get("foregroundOverlays")
        or []
    )
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(_as_list(raw)):
        overlay_id = f"O{index + 1}"
        if isinstance(item, dict):
            overlay = {
                "id": _clean_string(item.get("id") or overlay_id, 32) or overlay_id,
                "type": _clean_standalone_context(_first_text(item, "type", "kind", limit=120), 120),
                "position": _clean_standalone_context(_first_text(item, "position", "placement", limit=300), 300),
                "appearance": _clean_standalone_context(_first_text(item, "appearance", "visual_traits", "visualTraits", "description", limit=700), 700),
                "layering": _clean_standalone_context(_first_text(item, "layering", "layer", "z_index", "zIndex", limit=400), 400),
                "relationship": _clean_standalone_context(_first_text(item, "relationship", "relation", "covers", limit=500), 500),
            }
        else:
            overlay = {
                "id": overlay_id,
                "type": "",
                "position": "",
                "appearance": _clean_standalone_context(str(item), 700),
                "layering": "",
                "relationship": "",
            }
        if any(value for key, value in overlay.items() if key != "id"):
            normalized.append(overlay)
    return normalized[:8]


def _format_subject_detail_prompt(subjects: list[dict[str, str]]) -> str:
    detail_lines: list[str] = []
    for subject in subjects[:3]:
        parts = [
            subject.get("name") or subject.get("role"),
            subject.get("placement"),
            subject.get("visual_traits"),
            subject.get("pose"),
            subject.get("expression"),
            subject.get("gaze"),
            subject.get("body_crop"),
            subject.get("outfit"),
            subject.get("makeup_hair"),
            subject.get("accessories"),
            subject.get("relationship"),
        ]
        line = "，".join(part for part in dict.fromkeys(parts) if part)
        if line:
            detail_lines.append(line)
    if not detail_lines:
        return ""
    return "主体细节：" + "；".join(detail_lines) + "。"


def _format_overlay_detail_prompt(overlays: list[dict[str, str]]) -> str:
    detail_lines: list[str] = []
    for overlay in overlays[:5]:
        parts = [
            overlay.get("type"),
            overlay.get("position"),
            overlay.get("appearance"),
            overlay.get("layering"),
            overlay.get("relationship"),
        ]
        line = "，".join(part for part in dict.fromkeys(parts) if part)
        if line:
            detail_lines.append(line)
    if not detail_lines:
        return ""
    return "叠加视觉元素：" + "；".join(detail_lines) + "。"


def _main_prompt_detail_additions(data: dict[str, Any]) -> list[str]:
    return [
        detail
        for detail in [
            _format_visual_style_prompt(data),
            _format_subject_detail_prompt(_normalize_subjects(data)),
            _format_overlay_detail_prompt(_normalize_overlay_elements(data)),
        ]
        if detail
    ]


def _enhance_main_prompt_details(text: str, data: dict[str, Any]) -> str:
    cleaned = str(text or "").strip()
    additions = [detail for detail in _main_prompt_detail_additions(data) if detail and detail not in cleaned]
    if not additions:
        return cleaned
    if NO_TEXT_CHINESE_CONSTRAINT in cleaned:
        cleaned = cleaned.replace(NO_TEXT_CHINESE_CONSTRAINT, "").strip()
        cleaned = re.sub(r"[，、；：。.\s]+$", "", cleaned)
    enhanced = f"{cleaned}\n\n" + "\n".join(additions)
    return _append_sentence_once(enhanced, NO_TEXT_CHINESE_CONSTRAINT)


def _enhance_universal_style_details(text: str, data: dict[str, Any]) -> str:
    cleaned = str(text or "").strip()
    style_detail = _format_visual_style_prompt(data)
    if not style_detail or style_detail in cleaned:
        return cleaned
    return f"{style_detail}{cleaned}".strip()



BASE_IMAGE_PLACEHOLDER_SLOTS = (
    ("[SUBJECT_GROUP]", "主体组", "subject", "后续主体参考图融合或替换主体身份"),
    ("[POSE_OR_EXPRESSION]", "姿态 / 表情", "subject_attribute", "替换主体动作、表情和情绪状态"),
    ("[OUTFIT_STYLE]", "服装 / 造型", "subject_attribute", "替换主体穿搭、发型、妆容或造型风格"),
    ("[MAIN_OBJECT]", "主要物件 / 装饰", "object", "替换画面中的关键道具、装饰物或符号元素"),
    ("[BACKGROUND_SCENE]", "背景场景", "scene", "替换背景环境、空间和场景气质"),
)


def _has_placeholder_slot(text: str) -> bool:
    return bool(re.search(r"\[[A-Z][A-Z0-9_]{2,}\]", str(text or "")))


def _text_placeholder_for_region(region: dict[str, str], index: int = 0) -> tuple[str, str]:
    role = str(region.get("role") or "").lower()
    size = str(region.get("size") or "").lower()
    text = str(region.get("text") or "")
    combined = f"{role} {size} {text}".lower()
    if any(marker in combined for marker in ("主标题", "大标题", "标题", "title", "hero")):
        return "[MAIN_TITLE]", "主标题"
    if any(marker in combined for marker in ("副标题", "subtitle", "sub title")):
        return "[SUBTITLE]", "副标题"
    if any(marker in combined for marker in ("刊期", "日期", "时间", "期号", "编号", "vol", "date", "meta")):
        return "[DATE_OR_META]", "日期 / 元信息"
    if any(marker in combined for marker in ("按钮", "行动", "cta", "button")):
        return "[CTA_TEXT]", "按钮 / 行动文案"
    if any(marker in combined for marker in ("品牌", "logo", "商标")):
        return "[BRAND_OR_LOGO_TEXT]", "品牌 / 标识文字"
    if any(marker in combined for marker in ("价格", "金额", "price")):
        return "[PRICE_OR_VALUE]", "价格 / 数值"
    if any(marker in combined for marker in ("正文", "说明", "卖点", "栏目", "描述", "support", "body")):
        return "[SUPPORTING_TEXT]", "辅助说明"
    return f"[TEXT_SLOT_{index + 1}]", f"文字槽位 {index + 1}"


def _build_placeholder_slots(text_regions: list[dict[str, str]], image_type_flags: dict[str, bool]) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = [
        {
            "slot": slot,
            "label": label,
            "kind": kind,
            "description": description,
            "source_region_id": "",
        }
        for slot, label, kind, description in BASE_IMAGE_PLACEHOLDER_SLOTS
    ]
    if image_type_flags.get("table_card"):
        slots.extend([
            {"slot": "[CARD_TITLE]", "label": "卡片标题", "kind": "text", "description": "资料卡、产品卡或表格标题槽位", "source_region_id": ""},
            {"slot": "[DATA_GROUP]", "label": "数据组", "kind": "data", "description": "表格、图表或数值分组槽位", "source_region_id": ""},
            {"slot": "[KEY_VALUE_ITEMS]", "label": "键值信息", "kind": "data", "description": "多条字段和值的可替换信息槽位", "source_region_id": ""},
            {"slot": "[STATUS_TAG]", "label": "状态标签", "kind": "text", "description": "状态、分类或标签文本槽位", "source_region_id": ""},
        ])
    if image_type_flags.get("web_design"):
        slots.extend([
            {"slot": "[PAGE_TITLE]", "label": "页面标题", "kind": "text", "description": "网页 Hero 或页面主标题槽位", "source_region_id": ""},
            {"slot": "[NAV_ITEMS]", "label": "导航项", "kind": "text", "description": "导航栏项目槽位", "source_region_id": ""},
            {"slot": "[CONTENT_CARD_GROUP]", "label": "内容卡片组", "kind": "component", "description": "网页或 App 内容卡片组槽位", "source_region_id": ""},
        ])
    for index, region in enumerate(text_regions or []):
        slot, label = _text_placeholder_for_region(region, index)
        slots.append({
            "slot": slot,
            "label": label,
            "kind": "text",
            "description": f"{label}文字槽位，位置：{region.get('position') or '按版式关系'}",
            "source_region_id": str(region.get("id") or ""),
        })
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in slots:
        slot = item.get("slot") or ""
        region_id = item.get("source_region_id") or ""
        key = f"{slot}:{region_id}" if region_id else slot
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _format_placeholder_slots_markdown(slots: list[dict[str, str]]) -> str:
    lines = []
    for item in slots:
        region = f"；来源：{item.get('source_region_id')}" if item.get("source_region_id") else ""
        lines.append(f"{item.get('slot')}：{item.get('label')}；{item.get('description')}{region}")
    return "\n".join(lines).strip()


def _build_chinese_main_prompt(data: dict[str, Any], image_type_flags: dict[str, bool]) -> str:
    context = _standalone_context_text(data) or "具有明确视觉特征的图像"
    pieces = [f"生成一张独立文生图画面：{context}。"]
    if image_type_flags.get("layout_design"):
        pieces.append("采用清晰的版式层级、视觉重心、留白节奏、网格秩序、边距关系和整体信息密度。")
    if image_type_flags.get("cover_template"):
        pieces.append("强化封面式主视觉、主体焦点、杂志/社媒首图构图和醒目的编辑感。")
    if image_type_flags.get("table_card"):
        pieces.append("保持卡片、表格、图表或信息块的清晰分组、边界关系、视觉对齐和阅读顺序。")
    if image_type_flags.get("web_design"):
        pieces.append("呈现网页/UI 的导航结构、卡片系统、按钮形态、区块间距、组件层级和产品界面质感。")
    if not any(image_type_flags.values()):
        pieces.append("重点描述主体、场景、构图、色彩、光影、材质、空间层次和整体风格。")
    pieces.extend(_main_prompt_detail_additions(data))
    pieces.append(NO_TEXT_CHINESE_CONSTRAINT)
    return "".join(pieces)


def _build_chinese_universal_style_prompt(data: dict[str, Any]) -> str:
    context = _standalone_context_text(data)
    style_context = _format_visual_style_prompt(data)
    prefix = f"围绕“{context}”，" if context else ""
    style_clause = f"{style_context}" if style_context else "准确保留媒介类型、渲染方式、边缘质量、纹理颗粒、色板关系和分辨率语言。"
    return f"{prefix}提取可复用的整体视觉语言：{style_clause}统一画面气质、主体层级、构图节奏、色彩关系、光影方向、材质质感、空间深度和成片精致度，避免风格混杂和视觉目标偏移。"


def _build_chinese_specialized_prompt(block_key: str, data: dict[str, Any], image_type_flags: dict[str, bool], text_regions: list[dict[str, str]] | None = None) -> str:
    context = _standalone_context_text(data) or "该视觉类型"
    has_text = bool(text_regions)
    detected_slots = [slot for slot, _ in (_text_placeholder_for_region(region, index) for index, region in enumerate(text_regions or []))]
    common_slots = ["[MAIN_TITLE]", "[SUBTITLE]", "[SUPPORTING_TEXT]", *detected_slots]
    common_text_slots = "、".join(dict.fromkeys(common_slots))
    if block_key == "layout_prompt" and image_type_flags.get("layout_design"):
        return f"排版布局模板提示词：{context}；以 [SUBJECT_GROUP] 作为主视觉主体，使用 [POSE_OR_EXPRESSION] 控制动作/表情，[OUTFIT_STYLE] 控制造型，[MAIN_OBJECT] 放置关键道具或装饰，[BACKGROUND_SCENE] 控制背景场景；文字使用 {common_text_slots} 等槽位按原有信息层级排列，保持画面比例、主次视觉层级、留白、对齐、网格、边距、视觉动线和整体层级关系。"
    if block_key == "cover_template_prompt" and image_type_flags.get("cover_template"):
        text_clause = f"文字槽位使用 {common_text_slots}" if has_text else "可选文字槽位使用 [MAIN_TITLE]、[SUBTITLE]、[SUPPORTING_TEXT]"
        return f"封面模板提示词：一张{context}，画面主体为 [SUBJECT_GROUP]，表情/动作设为 [POSE_OR_EXPRESSION]，服装造型为 [OUTFIT_STYLE]；[SUBJECT_GROUP] 按封面主视觉位置裁切并形成明确焦点，[MAIN_OBJECT] 作为关键装饰或符号元素，[BACKGROUND_SCENE] 提供背景层次；{text_clause}，按标题、辅助信息、说明文字的视觉层级排列；保持封面边距、主体裁切、视觉重心、醒目编辑感和可复用首图结构。"
    if block_key == "table_card_layout_prompt" and image_type_flags.get("table_card"):
        return f"表格/卡片信息布局提示词：{context}；使用 [CARD_TITLE] 定义卡片或表格标题，[DATA_GROUP] 组织数据区块，[KEY_VALUE_ITEMS] 放置字段和值，[STATUS_TAG] 放置状态标签；如有主体图或产品图，用 [SUBJECT_GROUP] 或 [MAIN_OBJECT] 承载；保持卡片分组、表格列宽、图表区域、状态块、数据层级、间距、对齐和阅读顺序。"
    if block_key == "web_design_style_prompt" and image_type_flags.get("web_design"):
        return f"网页/UI 设计风格词：{context}；使用 [NAV_ITEMS] 表示导航内容，[PAGE_TITLE] 表示 Hero 或页面标题，[SUBJECT_GROUP] 表示主视觉人物/产品/插图，[CTA_TEXT] 表示按钮文案，[CONTENT_CARD_GROUP] 表示内容卡片组；描述导航、Hero 区、内容卡片、按钮、表单、数据区、组件圆角、阴影、边框、配色、字体气质和响应式界面层级。"
    return ""


def _build_image_specific_negative_prompt(data: dict[str, Any], image_type_flags: dict[str, bool]) -> str:
    context = _standalone_context_text(data) or "该画面类型"
    image_kind = _first_text(data, "image_kind", "imageKind", limit=80)
    text_markdown = _first_text(data, "text_markdown", "textMarkdown", "ocr_text", "ocrText", limit=400)
    pieces = [f"针对{context}，避免主体关系失衡、构图重心偏移、色彩气质不一致、光影方向混乱和媒介质感跑偏。"]
    if image_type_flags.get("layout_design"):
        pieces.append("避免版式层级错乱、留白节奏被破坏、图文占位失衡、网格对齐松散、视觉动线不清。")
    if image_type_flags.get("cover_template"):
        pieces.append("避免封面标题区失衡、主体裁切失去焦点、刊号/副标题占位杂乱、封面质感变成普通广告图。")
    if image_type_flags.get("table_card"):
        pieces.append("避免卡片边界混乱、表格列宽不齐、数据块拥挤、标签错位、图表比例失真和信息层级不清。")
    if image_type_flags.get("web_design"):
        pieces.append("避免导航、按钮、卡片、表单和内容区错位，避免廉价模板感、组件层级混乱和网页截图式噪点。")
    if _visual_style_context_text(data):
        pieces.append("避免把某一区域的媒介风格错误扩散到所有文字、Logo、标题、留白底版或整张版式；避免区域之间的渲染方式、边缘质量、纹理颗粒和色板关系互相污染。")
    if _has_pixel_style(data):
        pieces.append("对于识别为像素风的区域，避免转成真实摄影、柔和矢量插画、3D 渲染或水彩笔触；避免作用范围内出现平滑渐变、细腻真实材质、抗锯齿过强、像素边缘被磨平、块状结构丢失。")
    if any(keyword in image_kind for keyword in ("摄影", "人像", "照片")):
        pieces.append("避免肤色失真、五官变形、肢体异常、过度磨皮、背景抢主体和廉价影楼感。")
    if any(keyword in image_kind for keyword in ("产品", "商品", "包装")):
        pieces.append("避免产品比例失真、材质错误、反光脏乱、边缘变形、商标乱写和包装文字乱码。")
    if any(keyword in image_kind for keyword in ("插画", "海报", "信息图")):
        pieces.append("避免风格混杂、笔触质感不统一、装饰元素喧宾夺主和信息密度失控。")
    if text_markdown:
        pieces.append("避免自动生成未经确认的可读文字、日期、刊号、品牌名、二维码、价格或随机字母数字。")
    else:
        pieces.append("避免凭空添加可读文字、Logo、水印、二维码、价格、品牌标识或随机字符。")
    return "".join(pieces)


def _is_polluted_visual_prompt(text: str) -> bool:
    cleaned = str(text or "")
    if _has_reference_dependency(cleaned):
        return True
    hard_markers = ("OCR", "ocr", "保留图中文字", "编辑稿", "请按以下", "勾选", "除非用户", "text_markdown")
    if any(marker in cleaned for marker in hard_markers):
        return True
    soft_groups = (
        ("文字", "占位"),
        ("文字", "可读"),
        ("文字", "生成"),
        ("字母", "数字"),
        ("Logo", "水印"),
        ("二维码", "价格"),
    )
    return any(all(marker in cleaned for marker in group) for group in soft_groups)


def _clean_ocr_markdown(text: str) -> str:
    cleaned = _strip_code_fences(str(text or "").strip())
    lines = cleaned.splitlines()
    if lines and lines[0].strip().lower() in {"markdown", "md"}:
        lines = lines[1:]
    return "\n".join(lines).strip()


def _normalize_text_regions(data: dict[str, Any], text_markdown: str) -> list[dict[str, str]]:
    raw_regions = data.get("text_regions") or data.get("textRegions") or data.get("ocr_regions") or data.get("ocrRegions")
    regions: list[dict[str, str]] = []
    if isinstance(raw_regions, list):
        for index, item in enumerate(raw_regions):
            if not isinstance(item, dict):
                continue
            text = _clean_string(item.get("text") or item.get("original_text") or item.get("originalText"), 1200)
            if not text:
                continue
            region_id = _clean_string(item.get("id") or item.get("slot") or f"T{len(regions) + 1}", 16).upper()
            if not re.match(r"^T\d+$", region_id):
                region_id = f"T{len(regions) + 1}"
            regions.append({
                "id": region_id,
                "text": text,
                "role": _clean_string(item.get("role") or item.get("label") or "文字", 80),
                "position": _clean_string(item.get("position") or item.get("placement") or "", 160),
                "anchor": _clean_string(item.get("anchor") or "", 80),
                "alignment": _clean_string(item.get("alignment") or item.get("align") or "", 40),
                "size": _clean_string(item.get("size") or item.get("scale") or item.get("level") or "", 40),
                "style": _clean_string(item.get("style") or item.get("font_style") or item.get("fontStyle") or "", 240),
            })
    if regions:
        return regions

    cleaned = _clean_ocr_markdown(text_markdown)
    if not cleaned:
        return []
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    if len(blocks) <= 1:
        blocks = [line.strip() for line in cleaned.splitlines() if line.strip()]
    fallback_positions = ("顶部区域", "上半部分", "画面中部", "下半部分", "底部区域")
    for index, block in enumerate(blocks):
        regions.append({
            "id": f"T{index + 1}",
            "text": block,
            "role": "文字",
            "position": fallback_positions[min(index, len(fallback_positions) - 1)],
            "anchor": "",
            "alignment": "",
            "size": "",
            "style": "",
        })
    return regions


def _format_text_regions_markdown(regions: list[dict[str, str]], fallback_text: str = "") -> str:
    if not regions:
        return _clean_ocr_markdown(fallback_text)
    blocks = []
    for region in regions:
        meta = []
        if region.get("role"):
            meta.append(region["role"])
        if region.get("position"):
            meta.append(f"位置：{region['position']}")
        if region.get("alignment"):
            meta.append(f"对齐：{region['alignment']}")
        if region.get("size"):
            meta.append(f"字号：{region['size']}")
        if region.get("style"):
            meta.append(f"样式：{region['style']}")
        header = f"{region.get('id') or 'T?'}｜" + "｜".join(meta)
        blocks.append(f"{header}\n{region.get('text') or ''}".strip())
    return "\n\n".join(blocks).strip()


def _prefer_chinese_prompt(text: str, fallback: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned and _has_han(cleaned):
        return cleaned
    return fallback


def _prefer_standalone_chinese_prompt(text: str, fallback: str, *, reject_tool_words: bool = False) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or not _has_han(cleaned):
        return fallback
    if _has_reference_dependency(cleaned):
        return fallback
    if reject_tool_words and _is_polluted_visual_prompt(cleaned):
        return fallback
    return cleaned
