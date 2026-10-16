"""Shared prompt text rules for the prompt-skill client.

Hint lexicons and safety-constraint phrases, the M0-M14 formula-module inference and
guards, JSON / code-fence cleanup, and the shaping of polish and style-extract results.
Pure functions and constants only: provider calls, settings (including the environment
tunables), caches and the Codex -> account-pool fallback stay in
backend/prompt_skill_client.py.
"""

from __future__ import annotations

import re
from typing import Any


MODULE_ORDER = [f"M{index}" for index in range(15)]
PERSON_HINTS = (
    "人物",
    "人像",
    "女性",
    "女人",
    "女孩",
    "男性",
    "男人",
    "男孩",
    "角色",
    "网红",
    "模特",
    "肖像",
    "妻子",
    "母亲",
    "妈妈",
    "孕妇",
    "孕期",
    "孕肚",
)
FEMALE_HINTS = ("女性", "女人", "女孩", "美女", "女网红", "成熟女性", "东亚女性", "亚洲女性", "妻子", "孕妇", "母亲", "妈妈")
PHOTO_HINTS = ("照片", "摄影", "写真", "自拍", "人像", "肖像", "真实", "网红", "社交媒体", "商业人像", "抓拍", "纪实", "记录")
MOBILE_PHOTO_HINTS = ("手机", "抓拍", "随手拍", "POV", "pov", "爸爸", "妈妈", "丈夫", "妻子", "生活纪实", "家庭记录")
PREGNANCY_HINTS = ("怀孕", "孕期", "孕妇", "孕肚", "孕晚期", "胎动", "孕期记录", "孕期纪念")
SCENE_HINTS = ("场景", "背景", "空间", "街", "室内", "室外", "咖啡馆", "城市", "自然光", "摄影棚", "卧室", "客厅", "家居", "家庭")
TEXTURE_HINTS = ("质感", "材质", "皮肤", "发丝", "服装", "面料", "反光", "纹理", "金属", "玻璃", "磨砂", "皮革", "丝绸", "树脂", "PVC", "涂装")
FORMAT_HINTS = (
    "壁纸",
    "海报",
    "手办",
    "设计稿",
    "UI",
    "界面",
    "信息图",
    "Logo",
    "logo",
    "包装",
    "封面",
    "头像",
    "Banner",
    "banner",
    "详情页",
    "图标",
    "产品图",
    "多图合成",
    "修图",
)
PRODUCT_HINTS = ("产品", "商品", "包装", "瓶", "鞋", "手办", "玩具", "模型", "道具", "设备", "家具", "摆件")
STRUCTURE_HINTS = ("姿态", "动作", "结构", "形体", "造型", "轮廓", "组件", "按钮", "卡片", "布局", "版式", "站姿", "坐姿", "手势", "网格")
STYLE_HINTS = ("风格", "赛博", "复古", "极简", "可爱", "3A", "二次元", "插画", "像素", "国潮", "品牌", "电影感", "CG", "动漫", "海报", "壁纸")
LAYOUT_HINTS = ("构图", "画幅", "比例", "景别", "机位", "视角", "透视", "留白", "居中", "网格", "对齐", "排版")
MEDIUM_HINTS = PHOTO_HINTS + MOBILE_PHOTO_HINTS + ("插画", "3D", "CG", "渲染", "手办", "设计稿", "UI", "界面", "壁纸", "海报", "信息图", "Logo", "logo")
LIGHTING_HINTS = (
    "光线",
    "光影",
    "色彩",
    "配色",
    "颜色",
    "色调",
    "渐变",
    "深色",
    "浅色",
    "明暗",
    "亮度",
    "对比",
    "自然光",
    "窗光",
    "逆光",
    "侧光",
    "补光",
    "直闪",
    "轮廓光",
    "发丝光",
    "暗部",
    "高光",
    "低曝光",
    "曝光",
    "烟雾",
)
HIGH_CONTRAST_LIGHTING_HINTS = (
    "暗调",
    "强对比",
    "暗背景",
    "夜景",
    "低曝光",
    "背景很暗",
    "黑暗",
    "浮出来",
    "主体分离",
    "赛博",
    "舞台感",
)
LIGHTING_CONSTRAINT_HINTS = ("过曝", "死黑", "烟雾过亮", "平均受光", "主体与背景黏连", "廉价发光")
RISK_HINTS = (
    "胸",
    "乳",
    "饱满",
    "丰满",
    "丰腴",
    "身材",
    "曲线",
    "性感",
    "臀",
    "腿",
    "吊带",
    "睡裙",
    "暴露",
    "暧昧",
    "诱惑",
    "撩人",
    "擦边",
    "裸",
    "私房",
)
CONSTRAINT_HINTS = ("避免", "不要", "防止", "排除", "约束", "非")
BODY_SAFETY_CONSTRAINT_HINTS = ("幼态", "低俗", "局部", "暴露", "夸张身体", "廉价网红", "过度磨皮")
BODY_SAFETY_FULL_CONSTRAINT = "避免幼态化、低俗化、身体局部特写、过度暴露服装、夸张身体比例、廉价网红感和过度磨皮。"
BODY_SAFETY_COMPACT_CONSTRAINT = "避免幼态化、低俗化、局部身体特写、过度暴露、夸张比例和过度磨皮。"
PREGNANCY_CONSTRAINT_HINTS = ("影楼风", "过度摆拍", "不真实孕肚", "孕肚形态", "广角畸变", "商业广告感")
PREGNANCY_FULL_CONSTRAINT = "负面约束：避免影楼风、过度摆拍、不真实孕肚形态、强烈广角畸变、过度磨皮、商业广告感过重、背景杂乱。"
PREGNANCY_COMPACT_CONSTRAINT = "避免影楼风、过度摆拍、不真实孕肚、强广角畸变、过度磨皮和背景杂乱。"
HIGH_CONTRAST_FULL_CONSTRAINT = "避免人物过曝、背景死黑、廉价发光特效、烟雾过亮、主体与背景黏连和全画面平均受光。"
HIGH_CONTRAST_COMPACT_CONSTRAINT = "避免过曝、背景死黑、廉价发光、烟雾过亮、主体背景黏连和平均受光。"
GENERIC_CONSTRAINT = "避免结构错误、风格冲突、信息过载和背景抢主体。"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _strip_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def _text_has_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _has_han(text: Any) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _normalize_modules(items: list[Any]) -> list[str]:
    valid = set(MODULE_ORDER)
    seen: set[str] = set()
    for item in items:
        module = str(item or "").strip().upper()
        if module in valid:
            seen.add(module)
    return [module for module in MODULE_ORDER if module in seen]


def _has_constraint(text: str) -> bool:
    return _text_has_any(text, CONSTRAINT_HINTS)


def _has_body_safety_constraint(text: str) -> bool:
    return _text_has_any(text, BODY_SAFETY_CONSTRAINT_HINTS)


def _has_pregnancy_constraint(text: str) -> bool:
    return _text_has_any(text, PREGNANCY_CONSTRAINT_HINTS)


def _has_lighting_constraint(text: str) -> bool:
    return _text_has_any(text, LIGHTING_CONSTRAINT_HINTS)


def _paragraph_count(text: str) -> int:
    parts = [part.strip() for part in str(text or "").replace("\r\n", "\n").split("\n")]
    return len([part for part in parts if part])


def _append_sentence_once(text: str, sentence: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return sentence
    if sentence in cleaned:
        return cleaned
    if cleaned.endswith(("。", "！", "？", "；")):
        separator = ""
    elif cleaned.endswith((".", "!", "?", ";")):
        separator = " "
    else:
        separator = "。"
    return f"{cleaned}{separator}{sentence}"


def _infer_formula_modules(original_text: str, full_prompt: str, compact_prompt: str) -> tuple[set[str], bool]:
    combined = f"{original_text} {full_prompt} {compact_prompt}"
    has_person = _text_has_any(combined, PERSON_HINTS)
    has_female = _text_has_any(combined, FEMALE_HINTS)
    has_photo = _text_has_any(combined, PHOTO_HINTS)
    has_mobile_photo = _text_has_any(combined, MOBILE_PHOTO_HINTS)
    has_pregnancy = _text_has_any(combined, PREGNANCY_HINTS)
    has_scene = _text_has_any(combined, SCENE_HINTS)
    has_texture = _text_has_any(combined, TEXTURE_HINTS)
    has_format = _text_has_any(combined, FORMAT_HINTS)
    has_product = _text_has_any(combined, PRODUCT_HINTS)
    has_structure = _text_has_any(combined, STRUCTURE_HINTS)
    has_style = _text_has_any(combined, STYLE_HINTS)
    has_layout = _text_has_any(combined, LAYOUT_HINTS)
    has_medium = _text_has_any(combined, MEDIUM_HINTS)
    has_lighting = _text_has_any(combined, LIGHTING_HINTS)
    has_high_contrast_lighting = _text_has_any(combined, HIGH_CONTRAST_LIGHTING_HINTS)
    has_risk = _text_has_any(original_text, RISK_HINTS)

    required = {"M0", "M2", "M3", "M7", "M14"}
    if has_female or has_risk:
        required.update({"M1", "M12"})
    if has_risk:
        required.add("M13")
    if has_photo or has_person or has_mobile_photo or has_medium:
        required.add("M3")
    if has_pregnancy:
        required.update({"M1", "M4", "M8", "M9", "M10", "M11", "M12"})
    if has_scene:
        required.add("M4")
    if has_structure or has_product or has_person:
        required.add("M5")
    if has_style or has_format:
        required.add("M6")
    if has_lighting or has_high_contrast_lighting:
        required.add("M8")
    if has_texture or has_product or has_person:
        required.add("M9")
    if has_person or has_scene or has_format or has_product or has_lighting or has_high_contrast_lighting:
        required.add("M10")
    if has_format or has_product:
        required.add("M11")
    if has_high_contrast_lighting:
        required.update({"M8", "M10", "M12"})
    if has_layout:
        required.add("M7")
    if _has_constraint(full_prompt) or _has_constraint(compact_prompt):
        required.add("M12")
    return required, has_risk


def _apply_formula_guards(data: dict[str, Any], original_text: str) -> dict[str, Any]:
    full_prompt = str(data.get("full_prompt") or data.get("完整提示词") or "").strip()
    compact_prompt = str(data.get("compact_prompt") or data.get("精简提示词") or data.get("精简可投喂版") or "").strip()
    if not full_prompt:
        raise ValueError("模型返回缺少 full_prompt")
    if not compact_prompt:
        compact_prompt = full_prompt

    raw_modules = data.get("modules")
    module_items = raw_modules if isinstance(raw_modules, list) else []
    required_modules, has_risk = _infer_formula_modules(original_text, full_prompt, compact_prompt)
    modules = _normalize_modules([*module_items, *required_modules])
    has_pregnancy = _text_has_any(f"{original_text} {full_prompt} {compact_prompt}", PREGNANCY_HINTS)
    has_high_contrast_lighting = _text_has_any(f"{original_text} {full_prompt} {compact_prompt}", HIGH_CONTRAST_LIGHTING_HINTS)

    if has_pregnancy:
        if not _has_pregnancy_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, PREGNANCY_FULL_CONSTRAINT)
        if not _has_pregnancy_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, PREGNANCY_COMPACT_CONSTRAINT)
    elif has_risk:
        if not _has_body_safety_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, BODY_SAFETY_FULL_CONSTRAINT)
        if not _has_body_safety_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, BODY_SAFETY_COMPACT_CONSTRAINT)
    elif has_high_contrast_lighting:
        if not _has_lighting_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, HIGH_CONTRAST_FULL_CONSTRAINT)
        if not _has_lighting_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, HIGH_CONTRAST_COMPACT_CONSTRAINT)
    elif "M12" in modules:
        if not _has_constraint(full_prompt):
            full_prompt = _append_sentence_once(full_prompt, GENERIC_CONSTRAINT)
        if not _has_constraint(compact_prompt):
            compact_prompt = _append_sentence_once(compact_prompt, GENERIC_CONSTRAINT)

    warnings = data.get("warnings")
    normalized_warnings = [str(item) for item in warnings] if isinstance(warnings, list) else []
    if has_risk and not normalized_warnings:
        normalized_warnings.append("已将身体局部或性感化表达转译为成熟得体的整体体态、服装剪裁与商业人像表达。")

    return {
        "full_prompt": full_prompt,
        "compact_prompt": compact_prompt,
        "modules": modules,
        "warnings": normalized_warnings,
        "router_summary": str(data.get("router_summary") or "").strip(),
        "original_text": original_text,
    }


def _extract_first_json_block(text: str) -> str:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("模型未返回 JSON 对象")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        ch = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return cleaned[start:index + 1]
    raise ValueError("模型返回的 JSON 不完整")


def _fallback_style_extract(text: str, message: str, candidate: str) -> dict[str, Any]:
    source = " ".join(part for part in [message, candidate, text] if str(part or "").strip())
    compact = " ".join(str(source or "自定义风格").split())[:420]
    name = "自定义风格"
    for marker, label in [
        ("电影", "电影感"),
        ("产品", "产品感"),
        ("敦煌", "敦煌"),
        ("皮影", "皮影戏"),
        ("写实", "超写实"),
        ("冷调", "冷调克制"),
        ("广告", "去广告感"),
    ]:
        if marker in source:
            name = label
            break
    prompt_style = compact or "保持主体清晰，强化构图、光影、材质和整体情绪，避免无关元素发散。"
    return {
        "name": name,
        "description": "从当前文本节点和提示词助手讨论中提取的风格预设。",
        "positive_style": prompt_style,
        "avoid": "避免改变主体身份、过度商业广告感、无关装饰堆砌、画面跑题。",
        "best_for": "文本节点提示词复用",
        "prompt_style": prompt_style,
        "tags": [],
    }


def _normalize_polish_result(data: dict[str, Any], original_text: str) -> dict[str, Any]:
    return _apply_formula_guards(data, original_text)
