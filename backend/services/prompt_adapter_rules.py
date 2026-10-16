"""Prompt adapter rules: risk scoring and safe-rewrite shaping.

Classifies the task type, scores sexual / minor / violence / real-person risk, applies the
fixed replacement table, builds the structured fallback prompts, and cleans and constrains
safe-rewrite model output. `analyze_prompt_adapter` is the public entry. Pure functions
and constants only; the model call for a safe rewrite stays in prompt_skill_client.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .prompt_text_rules import _strip_code_fences, _append_sentence_once, _extract_first_json_block


SAFE_REWRITE_CONSTRAINT = "Safety constraints: non-explicit, no nudity, no minors, no watermark."
SAFE_REWRITE_STRUCTURED_SECTIONS = (
    "Canvas",
    "Image Type",
    "Subject",
    "Role / Worldbuilding",
    "Pose / Action",
    "Clothing / Styling",
    "Composition / Camera",
    "Scene / Background",
    "Lighting / Color",
    "Material / Rendering",
    "Constraints",
)

ADAPTER_TASK_TYPES = [
    {
        "id": "cosplay_event",
        "label": "Cosplay / 漫展 / 角色定妆",
        "keywords": ("cosplay", "漫展", "展会", "convention", "expo", "角色定妆", "cosplayer", "头饰", "礼服"),
        "template_hint": "cosplay event portrait, costume craftsmanship, character styling, editorial convention photo",
    },
    {
        "id": "portrait_photo",
        "label": "写真 / 摄影人像",
        "keywords": ("人像", "写真", "portrait", "selfie", "photo", "摄影", "模特", "肖像", "拍照"),
        "template_hint": "editorial portrait, fashion photography, cinematic lighting, tasteful styling, natural skin texture",
    },
    {
        "id": "historical_fantasy",
        "label": "古风 / 仙侠 / 奇幻",
        "keywords": ("古风", "仙侠", "fantasy", "historical", "奇幻", "汉服", "仙气", "古代", "王朝", "江湖"),
        "template_hint": "historical-inspired costume, layered silk robe, embroidered outer gown, opaque inner garment",
    },
    {
        "id": "cyberpunk_game",
        "label": "赛博朋克 / 3A 游戏角色",
        "keywords": ("赛博", "cyberpunk", "3A", "游戏角色", "game character", "neon", "霓虹", "tactical", "装甲"),
        "template_hint": "sci-fi armor paneling, sleek reflective tactical suit, heroic silhouette, game character poster",
    },
    {
        "id": "business_fashion",
        "label": "现代职场 / 通勤风",
        "keywords": ("OL", "office", "办公室", "职场", "通勤", "西装", "business", "workplace", "高跟"),
        "template_hint": "professional fashion, tailored blazer, commuting outfit, business editorial portrait",
    },
    {
        "id": "product_ad",
        "label": "产品 / 广告 / 电商图",
        "keywords": ("产品", "商品", "广告", "电商", "包装", "product", "commercial", "品牌", "详情页"),
        "template_hint": "clean studio lighting, product hero shot, premium material, commercial advertising",
    },
    {
        "id": "architecture_scene",
        "label": "建筑 / 室内 / 场景",
        "keywords": ("建筑", "室内", "interior", "architecture", "空间", "房间", "街景", "场景", "可视化"),
        "template_hint": "architectural visualization, natural lighting, material realism, spatial depth, clean composition",
    },
    {
        "id": "action_dark",
        "label": "战斗 / 暴力 / 暗黑动作",
        "keywords": ("战斗", "battle", "combat", "blood", "gore", "暗黑", "动作", "武器", "伤口"),
        "template_hint": "stylized action, non-graphic combat, battle-worn armor, sparks, smoke, debris",
    },
    {
        "id": "children_family",
        "label": "儿童 / 家庭 / 校园",
        "keywords": ("儿童", "孩子", "小孩", "child", "children", "family", "家庭", "校园", "school"),
        "template_hint": "wholesome, family-friendly, age-appropriate clothing, warm documentary style",
    },
    {
        "id": "reference_edit",
        "label": "参考图 / 图像编辑",
        "keywords": ("参考图", "改图", "edit", "reference", "保持", "换背景", "修图", "基于图片"),
        "template_hint": "safe image edit, preserve non-explicit nature, adjust background, lighting, color, material, or style",
    },
]

ADAPTER_REPLACEMENTS = [
    ("real_person", ("celebrity nude", "real person nude", "private celebrity"), "original fictional adult character in a non-explicit editorial portrait", "Convert real-person sexualized framing into an original fictional safe portrait."),
    ("real_person", ("deepfake nude", "deepfake"), "original fictional adult character portrait", "Remove deepfake or real-person sexualization framing."),
    ("explicit", ("explicit sexual", "sexual act", "porn"), "non-explicit editorial character portrait", "Convert explicit sexual framing into a safe editorial portrait."),
    ("explicit", ("genitals",), "fully clothed non-explicit styling", "Remove explicit anatomy wording."),
    ("explicit", ("明确色情", "性交", "性行为", "性器官", "非同意亲密", "偷拍"), "非露骨的原创成年角色定妆照", "将明确色情、非同意或偷拍表述转为安全原创角色语境。"),
    ("real_person", ("真实人物色情", "名人裸照", "换脸色情"), "原创成年角色的非露骨编辑人像", "移除真实人物色情化或换脸色情表述。"),
    ("age", ("young East Asian women",), "clearly adult East Asian women", "Clarify adult age when the prompt contains mature styling or close portrait framing."),
    ("age", ("young women",), "clearly adult women", "Clarify adult age in a mature or fashion-oriented prompt."),
    ("age", ("young girl", "girl"), "clearly adult woman", "Replace youthful wording with clearly adult framing."),
    ("age", ("teen-looking", "teenage", "youthful"), "mature adult appearance", "Remove teen/youthful framing from image-generation prompt."),
    ("age", ("schoolgirl",), "academy-inspired adult fashion", "Convert school-coded wording into adult styling language."),
    ("age", ("cute little", "childlike", "loli"), "elegant stylized adult", "Avoid childlike framing in image prompts."),
    ("age", ("女孩", "少女", "幼态", "学生妹"), "明确成年的女性角色", "移除幼态或学生妹表述，改为明确成年角色。"),
    ("sexualized", ("sexy",), "elegant high-fashion", "Reduce sexualized wording while preserving visual appeal."),
    ("sexualized", ("seductive",), "softly posed and confident", "Convert seductive wording into editorial posing language."),
    ("sexualized", ("sultry",), "cinematic and moody", "Convert sultry mood into cinematic language."),
    ("sexualized", ("provocative",), "bold editorial fashion", "Convert provocative wording into editorial styling."),
    ("sexualized", ("erotic", "naughty", "horny"), "refined non-explicit", "Remove explicit sexual framing."),
    ("sexualized", ("tempting",), "alluring fashion presence / elegant charisma", "Convert tempting wording into fashion charisma."),
    ("sexualized", ("sensual",), "graceful and refined", "Soften sensual wording into refined mood language."),
    ("sexualized", ("flirtatious",), "gentle confident expression", "Convert flirtatious expression into confident portrait language."),
    ("sexualized", ("性感", "诱惑", "挑逗", "擦边", "色情"), "优雅、自信、时尚摆拍", "将性化表述转为时尚与角色气质语言。"),
    ("body", ("big breasts", "huge chest"), "dramatic structured bodice", "Convert body-size wording into garment construction."),
    ("body", ("breasts",), "bodice silhouette", "Convert body-part wording into clothing silhouette."),
    ("body", ("revealing cleavage",), "refined deep-V gown", "Convert cleavage wording into formal clothing design."),
    ("body", ("cleavage",), "deep neckline", "Convert body focus into neckline/costume wording."),
    ("body", ("hips",), "tailored waistline", "Convert body focus into garment tailoring."),
    ("body", ("butt",), "back silhouette and garment drape", "Avoid explicit body-part focus."),
    ("body", ("thighs",), "leg line within full-body styling", "Keep leg details as styling, not body focus."),
    ("body", ("legs focus",), "full outfit composition", "Shift focus from legs to full outfit."),
    ("body", ("feet focus",), "footwear visible as part of full-body styling", "Shift focus from feet to full-body styling."),
    ("body", ("top-heavy",), "curvy fashion silhouette", "Convert body-proportion wording into fashion silhouette."),
    ("body", ("bust-dominant",), "structured bodice-forward costume design", "Convert bust-focused wording into costume design."),
    ("body", ("胸部", "乳房", "爆乳", "事业线", "身体局部特写"), "胸衣轮廓、上身剪裁、结构化衣身", "将身体局部描述转为服装剪裁语言。"),
    ("exposure", ("naked", "nude"), "clothed tasteful styling", "Remove nudity framing and keep the prompt non-explicit."),
    ("exposure", ("see-through",), "layered translucent fabric over an opaque base", "Convert see-through wording into layered fabric construction."),
    ("exposure", ("transparent dress",), "translucent outer layer over an opaque inner garment", "Convert transparent clothing into safe layered styling."),
    ("exposure", ("transparent",), "translucent outer layer", "Use material language instead of body visibility."),
    ("exposure", ("bare skin",), "open-shoulder design / exposed neckline area", "Convert bare-skin wording into clothing design."),
    ("exposure", ("barely covered",), "elegant layered costume", "Replace revealing coverage wording with costume layers."),
    ("exposure", ("lingerie",), "corset-inspired bodice / eveningwear", "Convert underwear framing into fashion construction."),
    ("exposure", ("underwear",), "fitted inner garment", "Use garment layer language."),
    ("exposure", ("wet clothes clinging",), "rain-textured fabric", "Avoid body-clinging framing."),
    ("exposure", ("revealing outfit",), "open-cut formal gown / stylized costume design", "Convert revealing wording into formal costume design."),
    ("exposure", ("透视", "透明", "若隐若现", "几乎遮不住"), "叠层薄纱、不透明内层、透明外搭", "将透明暴露改为服装材质层次。"),
    ("pose", ("seductive pose",), "elegant editorial pose", "Convert seductive pose into editorial pose."),
    ("pose", ("provocative pose",), "confident fashion pose", "Convert provocative pose into fashion pose."),
    ("pose", ("arching back",), "graceful upright posture", "Avoid sexualized body posture."),
    ("pose", ("bending over",), "leaning slightly forward", "Soften pose while preserving perspective."),
    ("pose", ("spreading legs", "spread legs"), "seated balanced pose", "Avoid explicit pose framing."),
    ("pose", ("legs apart",), "stable stance", "Use neutral stance language."),
    ("pose", ("foot toward camera", "one foot reaching camera"), "shoes angled slightly toward viewer", "Convert foot focus into balanced footwear perspective."),
    ("pose", ("body pressed",), "close group composition", "Convert body-contact wording into group composition."),
    ("pose", ("intimate pose",), "warm natural group pose", "Avoid intimate framing."),
    ("camera", ("camera below knees",), "slight low-angle cinematic view", "Convert risky low angle into controlled cinematic view."),
    ("camera", ("worm-eye focusing legs",), "controlled low-angle full-body composition", "Avoid leg-focused low angle."),
    ("camera", ("POV body shot",), "editorial portrait composition", "Avoid body-focused POV framing."),
    ("camera", ("chest close-up",), "upper-body fashion portrait", "Convert chest focus into portrait/fashion framing."),
    ("camera", ("foot close-up",), "full-body framing with visible footwear", "Avoid foot-focused composition."),
    ("camera", ("extreme low angle under body",), "low-angle heroic framing", "Avoid under-body camera framing."),
    ("camera", ("voyeuristic",), "documentary / candid / natural", "Remove voyeuristic framing."),
    ("camera", ("猫眼视角", "镜头低于膝部", "脚伸向镜头", "低机位强调腿部", "低机位强调胸部", "低机位强调臀部", "低机位强调脚部"), "轻微低机位电影镜头、控制透视、完整构图、不形成身体局部凝视", "将高风险镜头转为受控电影构图。"),
    ("skin", ("oily body",), "natural skin highlights", "Convert oily body wording into neutral lighting."),
    ("skin", ("glossy body",), "polished skin under soft lighting", "Convert body gloss into portrait lighting."),
    ("skin", ("glossy skin",), "polished skin under soft lighting", "Convert skin gloss into lighting language."),
    ("skin", ("sweaty",), "subtle stage-light sheen", "Avoid sweat/body emphasis."),
    ("skin", ("wet skin",), "rain-lit highlights", "Convert skin wetness into lighting."),
    ("skin", ("shiny breasts",), "fabric highlights", "Move highlights from body to fabric."),
    ("skin", ("smooth erotic skin",), "refined natural skin texture", "Convert erotic skin wording into neutral material detail."),
    ("skin", ("微弱健康油光", "油光", "湿润皮肤"), "自然健康的皮肤光泽", "将皮肤质感转为自然光泽语言。"),
    ("ip", ("exact copy of",), "original design inspired by", "Avoid exact IP copying."),
    ("ip", ("replicate this official poster exactly",), "create an original poster inspired by", "Avoid exact poster replication."),
    ("ip", ("identical to",), "similar cinematic archetype / original character", "Avoid identity copying."),
    ("text", ("readable random text",), "small blurred signage", "Avoid random readable text."),
    ("text", ("exact brand logo",), "generic fictional signage", "Avoid unauthorized real brand logo."),
    ("text", ("real company logo",), "brand-like but fictional mark", "Avoid real company logo misuse."),
    ("text", ("large Chinese text",), "subtle graphic title area", "Reduce random text risk."),
    ("text", ("clear text on poster",), "clean minimal text, legible only if necessary", "Keep text intentional and minimal."),
    ("text", ("随机文字", "招牌文字", "背景红字"), "模糊背景标识，不清晰可读", "降低背景文字乱码和品牌误用风险。"),
]

ADAPTER_MATURE_CONTEXT_TERMS = (
    "sexy", "seductive", "sultry", "provocative", "cleavage", "breasts", "transparent", "see-through",
    "stockings", "high heels", "swimwear", "tight", "low angle", "bedroom", "bathroom", "lingerie",
    "性感", "诱惑", "挑逗", "低胸", "透明", "透视", "丝袜", "高跟", "泳装", "低机位", "卧室", "浴室",
)

ADAPTER_PERSON_TERMS = (
    "woman", "women", "girl", "person", "people", "portrait", "model", "cosplayer", "character",
    "女性", "女人", "女孩", "人物", "角色", "人像", "模特", "肖像",
)

ADAPTER_SEXUAL_TERMS = (
    "sexy", "seductive", "sultry", "provocative", "erotic", "nude", "naked", "fetish", "cleavage",
    "breasts", "lingerie", "see-through", "transparent", "性感", "诱惑", "挑逗", "色情", "裸露", "胸部", "乳房",
)

ADAPTER_EXPLICIT_TERMS = (
    "explicit sexual", "sexual act", "porn", "genitals", "non-consensual", "deepfake nude",
    "明确色情", "性交", "性行为", "性器官", "非同意亲密", "偷拍",
)

ADAPTER_GRAPHIC_VIOLENCE_TERMS = (
    "gore", "dismemberment", "graphic wound", "torture", "肢解", "血腥特写", "伤口特写", "酷刑",
)

ADAPTER_REAL_PERSON_RISK_TERMS = (
    "celebrity nude", "real person nude", "deepfake", "private celebrity", "真实人物色情", "名人裸照", "换脸色情",
)

ADAPTER_HARD_BLOCK_MINOR_TERMS = (
    "minor", "minors", "child", "children", "young girl", "girl", "teen", "teenage", "schoolgirl", "loli", "childlike",
    "未成年", "儿童", "孩子", "小孩", "少女", "女孩", "幼态", "学生妹",
)

ADAPTER_SCORE_RULES = [
    ("age_young", 2, ("young", "girl", "年轻", "女孩")),
    ("minor_coded", 5, ("teen", "schoolgirl", "teenage", "loli", "少女", "学生妹", "幼态")),
    ("sexualized_language", 3, ("sexy", "seductive", "sultry", "provocative", "性感", "诱惑", "挑逗", "擦边")),
    ("body_focus", 3, ("cleavage", "breasts", "huge chest", "body close-up", "事业线", "胸部", "乳房", "身体局部")),
    ("transparent_exposure", 3, ("transparent", "see-through", "barely covered", "透视", "透明", "若隐若现")),
    ("fetish_framing", 1, ("stockings", "high heels", "丝袜", "高跟", "足部")),
    ("low_angle", 2, ("low angle", "below knees", "worm-eye", "cat-eye", "低机位", "猫眼视角", "低于膝部")),
    ("foot_foreground", 3, ("foot toward camera", "one foot reaching", "脚伸向镜头", "鞋尖朝向镜头")),
    ("private_scene", 2, ("bedroom", "bathroom", "bed", "hotel room", "卧室", "浴室", "床", "酒店房间")),
    ("nudity", 6, ("nude", "naked", "裸露", "裸体", "没穿衣服")),
]

ADAPTER_INTENT_TERMS = {
    "subject": (
        "woman", "women", "man", "person", "people", "portrait", "model", "cosplayer", "character",
        "product", "package", "architecture", "interior", "animal", "landscape",
        "女性", "女人", "男人", "人物", "角色", "人像", "模特", "产品", "包装", "建筑", "室内", "动物", "风景",
    ),
    "identity": (
        "clearly adult", "mature adult", "editorial", "fashion", "cosplay", "warrior", "mage", "business",
        "historical", "fantasy", "cyberpunk", "adult", "professional", "student-inspired",
        "明确成年", "成年人", "时尚", "角色定妆", "战士", "法师", "职场", "古风", "奇幻", "赛博",
    ),
    "action": (
        "standing", "sitting", "walking", "running", "leaning", "posing", "holding", "looking at camera",
        "站立", "坐姿", "走路", "奔跑", "轻微前倾", "摆拍", "手持", "看向镜头",
    ),
    "clothing": (
        "gown", "dress", "robe", "suit", "blazer", "armor", "costume", "bodice", "neckline", "fabric",
        "translucent outer layer", "opaque base", "layered", "silk", "chiffon", "鞋", "礼服", "长裙",
        "汉服", "西装", "盔甲", "服装", "胸衣轮廓", "剪裁", "叠层薄纱", "不透明内层", "面料",
    ),
    "scene": (
        "studio", "street", "bedroom", "room", "city", "forest", "convention", "expo", "stage",
        "office", "interior", "outdoor", "rain", "night", "室内", "街道", "城市", "森林", "漫展", "展会",
        "舞台", "办公室", "户外", "雨夜", "夜景",
    ),
    "camera": (
        "close-up", "full-body", "upper-body", "low angle", "low-angle", "slight low-angle", "wide angle", "telephoto",
        "depth of field", "portrait composition", "balanced composition", "controlled perspective",
        "特写", "全身", "半身", "低机位", "轻微低机位", "广角", "长焦", "景深", "完整构图", "受控电影机位",
    ),
    "style": (
        "photo", "portrait", "photography", "cinematic", "editorial", "fashion", "3D", "CGI", "illustration",
        "poster", "anime", "commercial", "minimal", "电影", "摄影", "写真", "时尚", "编辑", "插画",
        "海报", "动漫", "商业", "极简",
    ),
}


def _adapter_contains_any(text: str, terms: tuple[str, ...]) -> bool:
    haystack = str(text or "").lower()
    return any(str(term or "").lower() in haystack for term in terms)


def _adapter_risk_text(text: str) -> str:
    """Remove explicit negative safety constraints before positive risk scans."""
    cleaned = str(text or "")
    replacements = (
        (r"无未成年人|无未成年|没有未成年人|没有未成年|不含未成年人|不含未成年|无儿童|没有儿童", " "),
        (r"\bno\s+minors?\b|\bwithout\s+minors?\b|\bno\s+children\b", " "),
        (r"无裸露|没有裸露|不裸露|无裸体|没有裸体|非裸露|非露骨|非色情", " "),
        (r"\bno\s+nudity\b|\bno\s+nude\b|\bno\s+naked\b|\bnon[-\s]?explicit\b|\bnot\s+explicit\b", " "),
        (r"不透明", "opaque"),
        (r"控制透视|艺术透视|镜头透视|透视关系|透视畸变", "controlled perspective"),
        (r"不形成身体局部强调|不形成身体局部凝视|非身体局部强调|非身体局部凝视", " "),
    )
    for pattern, replacement in replacements:
        cleaned = re.sub(pattern, replacement, cleaned, flags=re.I)
    return cleaned


def _adapter_phrase_pattern(phrase: str) -> re.Pattern:
    escaped = re.escape(str(phrase or ""))
    if re.search(r"[A-Za-z0-9]", phrase or ""):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.I)
    return re.compile(escaped, re.I)


def _adapter_match_is_safe_context(category: str, phrase: str, text: str, start: int, end: int) -> bool:
    if category != "exposure":
        return False
    clean_phrase = str(phrase or "").lower()
    window = str(text or "")[max(0, start - 12): min(len(str(text or "")), end + 12)]
    lowered_window = window.lower()
    if clean_phrase in {"transparent", "透视", "透明"}:
        if any(marker in lowered_window for marker in ("not transparent", "opaque", "non-transparent", "不透明")):
            return True
    if phrase in {"透视", "透明"}:
        if any(marker in window for marker in ("控制透视", "艺术透视", "镜头透视", "透视关系", "透视畸变")):
            return True
        risky_markers = ("透视装", "透视衣", "透视服", "透明衣", "透明服", "透明裙", "透明材质", "透明外衣", "若隐若现", "几乎遮不住", "暴露", "裸露", "肌肤", "身体")
        return not any(marker in window for marker in risky_markers)
    return False


def _classify_adapter_task_type(text: str) -> dict[str, Any]:
    scored = []
    for item in ADAPTER_TASK_TYPES:
        score = sum(1 for keyword in item["keywords"] if keyword.lower() in str(text or "").lower())
        if score:
            scored.append((score, item))
    if not scored:
        return {
            "id": "general_image",
            "label": "通用图像",
            "template_hint": "clear image prompt, balanced composition, visual structure, lighting, material detail",
        }
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = scored[0][1]
    return {
        "id": selected["id"],
        "label": selected["label"],
        "template_hint": selected["template_hint"],
    }


def _score_adapter_prompt(text: str) -> tuple[int, list[str]]:
    score = 0
    flags: list[str] = []
    risk_text = _adapter_risk_text(text)
    for flag, points, terms in ADAPTER_SCORE_RULES:
        if _adapter_contains_any(risk_text, terms):
            score += points
            flags.append(flag)
    if _adapter_contains_any(text, ("clearly adult", "明确成年", "成年人", "adult woman", "adult women")):
        score -= 2
        flags.append("adult_framing_present")
    if _adapter_contains_any(text, ("non-explicit", "非露骨", "非色情")):
        score -= 1
        flags.append("non_explicit_present")
    if _adapter_contains_any(text, ("editorial", "fashion", "cosplay event", "cinematic", "时尚", "电影", "角色定妆")):
        score -= 1
        flags.append("safe_visual_context_present")
    return max(0, score), flags


def _adapter_risk_level(score: int) -> str:
    if score <= 2:
        return "low"
    if score <= 6:
        return "medium"
    if score <= 10:
        return "high"
    return "severe"


def _adapter_unique_matches(text: str, terms: tuple[str, ...], limit: int = 4) -> list[str]:
    source = str(text or "")
    haystack = source.lower()
    matches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = str(term or "").strip()
        if not clean or clean.lower() in seen:
            continue
        has_match = bool(_adapter_phrase_pattern(clean).search(source)) if re.search(r"[A-Za-z0-9]", clean) else clean.lower() in haystack
        if has_match:
            matches.append(clean)
            seen.add(clean.lower())
        if len(matches) >= limit:
            break
    return matches


def _adapter_extract_aspect_ratio(text: str) -> str:
    source = str(text or "")
    match = re.search(r"(?<!\d)(\d{1,2}\s*[:：]\s*\d{1,2})(?!\d)", source)
    if match:
        return re.sub(r"\s+", "", match.group(1)).replace("：", ":")
    lowered = source.lower()
    if any(term in lowered for term in ("vertical", "portrait orientation", "9:16", "竖版", "竖屏")):
        return "9:16"
    if any(term in lowered for term in ("horizontal", "landscape orientation", "16:9", "横版", "横屏")):
        return "16:9"
    if any(term in lowered for term in ("square", "1:1", "方图", "正方形")):
        return "1:1"
    return ""


def _extract_adapter_intent(original_text: str, rewritten_seed: str, task_type: dict[str, Any]) -> dict[str, Any]:
    source = " ".join(part for part in [rewritten_seed, original_text] if part)
    subject = _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["subject"])
    if not subject and task_type.get("id") != "general_image":
        subject = [str(task_type.get("label") or task_type.get("id") or "").strip()]
    return {
        "aspect_ratio": _adapter_extract_aspect_ratio(original_text),
        "subject": subject,
        "identity": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["identity"]),
        "action": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["action"]),
        "clothing": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["clothing"]),
        "scene": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["scene"]),
        "camera": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["camera"]),
        "style": _adapter_unique_matches(source, ADAPTER_INTENT_TERMS["style"]),
    }


def _should_apply_adapter_replacement(category: str, source_text: str) -> bool:
    risk_text = _adapter_risk_text(source_text)
    if category == "age":
        if _adapter_contains_any(risk_text, ("loli", "teen-looking", "schoolgirl", "childlike", "少女", "幼态", "学生妹")):
            return True
        return _adapter_contains_any(risk_text, ADAPTER_MATURE_CONTEXT_TERMS)
    return True


def _apply_adapter_replacements(text: str) -> tuple[str, list[dict[str, str]]]:
    rewritten = str(text or "")
    changed: list[dict[str, str]] = []
    entries = sorted(ADAPTER_REPLACEMENTS, key=lambda item: max(len(term) for term in item[1]), reverse=True)
    for category, terms, replacement, reason in entries:
        if not _should_apply_adapter_replacement(category, rewritten):
            continue
        for term in terms:
            pattern = _adapter_phrase_pattern(term)
            if not pattern.search(rewritten):
                continue
            replaced = False

            def replace_match(match: re.Match) -> str:
                nonlocal replaced
                if _adapter_match_is_safe_context(category, term, rewritten, match.start(), match.end()):
                    return match.group(0)
                replaced = True
                return replacement

            rewritten = pattern.sub(replace_match, rewritten)
            if replaced:
                changed.append({
                    "from": term,
                    "to": replacement,
                    "category": category,
                    "reason": reason,
                })
    return rewritten.strip(), changed


def _adapter_warnings(text: str, score: int, flags: list[str], task_type: dict[str, Any], changed_terms: list[dict[str, str]]) -> tuple[list[str], bool]:
    warnings: list[str] = []
    should_block = False
    risk_text = _adapter_risk_text(text)
    has_people = _adapter_contains_any(risk_text, ADAPTER_PERSON_TERMS)
    has_mature_context = _adapter_contains_any(risk_text, ADAPTER_MATURE_CONTEXT_TERMS)
    has_sexual = _adapter_contains_any(risk_text, ADAPTER_SEXUAL_TERMS)
    has_explicit = _adapter_contains_any(risk_text, ADAPTER_EXPLICIT_TERMS)
    has_graphic_violence = _adapter_contains_any(risk_text, ADAPTER_GRAPHIC_VIOLENCE_TERMS)
    has_real_person_risk = _adapter_contains_any(risk_text, ADAPTER_REAL_PERSON_RISK_TERMS)
    has_hard_block_minor = _adapter_contains_any(risk_text, ADAPTER_HARD_BLOCK_MINOR_TERMS)

    if has_people and has_mature_context and not _adapter_contains_any(text, ("clearly adult", "明确成年", "成年人", "adult woman", "adult women")):
        warnings.append("人物提示词包含成熟穿搭、亲密姿态或镜头风险，已要求明确成年。")
    if "body_focus" in flags:
        warnings.append("检测到身体局部焦点，已转向服装剪裁、造型轮廓和完整构图。")
    if "transparent_exposure" in flags:
        warnings.append("检测到透明/透视服装表达，已转为叠层面料和不透明内层。")
    if "low_angle" in flags or "foot_foreground" in flags:
        warnings.append("检测到低机位或腿脚前景表达，已要求受控电影机位和非局部凝视。")
    if "private_scene" in flags and has_sexual:
        warnings.append("私密场景叠加性化表达风险较高，已转为非露骨室内/生活方式摄影语境。")
    if task_type.get("id") == "children_family" and has_sexual:
        warnings.append("儿童/家庭场景不能包含任何性化、暴露或亲密暗示。")
    if has_hard_block_minor and (has_mature_context or has_sexual or has_explicit):
        warnings.append("未成年或幼态词与性化/暴露表达组合，不能通过换词作为原意生成。")
        should_block = True
    if has_explicit:
        warnings.append("检测到明确色情、非同意或偷拍相关表达，将交给安全改写转为非露骨替代主题。")
    if has_graphic_violence:
        warnings.append("检测到真实血腥、肢解、酷刑或伤口特写风险，需要改成非图形化动作场景。")
    if has_real_person_risk:
        warnings.append("检测到真实人物色情化、深度伪造或私密场景风险，将交给安全改写转为原创角色。")
    if score >= 7:
        warnings.append("风险分较高，已按时尚/电影/角色定妆语境大幅改写。")
    elif score >= 3:
        warnings.append("提示词包含中等风险组合，已进行风险词替换和约束补全。")
    if changed_terms:
        warnings.append(f"已按词典替换 {len(changed_terms)} 处高风险表达。")
    return warnings, should_block


def analyze_prompt_adapter(text: str) -> dict[str, Any]:
    original_text = str(text or "").strip()
    task_type = _classify_adapter_task_type(original_text)
    risk_score, flags = _score_adapter_prompt(original_text)
    rewritten_seed, changed_terms = _apply_adapter_replacements(original_text)
    intent = _extract_adapter_intent(original_text, rewritten_seed, task_type)
    warnings, should_block = _adapter_warnings(original_text, risk_score, flags, task_type, changed_terms)
    return {
        "task_type": task_type,
        "intent": intent,
        "risk_score": risk_score,
        "risk_level": _adapter_risk_level(risk_score),
        "risk_flags": flags,
        "changed_terms": changed_terms,
        "warnings": warnings,
        "rewritten_seed": rewritten_seed,
        "blocked": should_block,
    }


def _build_adapter_fallback_prompt(analysis: dict[str, Any]) -> str:
    seed = str(analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    intent = analysis.get("intent") if isinstance(analysis.get("intent"), dict) else {}
    hint = str(task_type.get("template_hint") or "").strip()
    return _build_structured_adapter_prompt(seed, analysis, hint=hint, language="zh")


def _build_adapter_fallback_prompts(analysis: dict[str, Any]) -> dict[str, str]:
    seed = str(analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    hint = str(task_type.get("template_hint") or "").strip()
    return {
        "zh_prompt": _build_structured_adapter_prompt(seed, analysis, hint=hint, language="zh"),
        "en_prompt": _build_structured_adapter_prompt(seed, analysis, hint=hint, language="en"),
    }


def _adapter_intent_items(intent: dict[str, Any], key: str, fallback: str = "") -> str:
    value = intent.get(key)
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(items[:5]) if items else fallback
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _is_structured_adapter_prompt(text: str) -> bool:
    cleaned = str(text or "")
    return all(re.search(rf"\[{index}\.\s*[^\]]+\]", cleaned) for index in range(1, len(SAFE_REWRITE_STRUCTURED_SECTIONS) + 1))


def _build_structured_adapter_prompt(source_text: str, analysis: dict[str, Any], hint: str = "", language: str = "en") -> str:
    source = str(source_text or analysis.get("rewritten_seed") or "").strip()
    task_type = analysis.get("task_type") if isinstance(analysis.get("task_type"), dict) else {}
    intent = analysis.get("intent") if isinstance(analysis.get("intent"), dict) else {}
    task_label = str(task_type.get("label") or task_type.get("id") or "通用图像").strip()
    task_hint = str(hint or task_type.get("template_hint") or "").strip()
    if language == "zh":
        aspect_ratio = _adapter_intent_items(intent, "aspect_ratio", "按原提示词指定画幅")
        subject = _adapter_intent_items(intent, "subject", "原提示词主体")
        identity = _adapter_intent_items(intent, "identity", "如涉及人物需明确成年")
        action = _adapter_intent_items(intent, "action", "自然、克制、平衡的姿态")
        clothing = _adapter_intent_items(intent, "clothing", "服装结构、面料层次、轮廓、配饰与造型")
        scene = _adapter_intent_items(intent, "scene", "原提示词场景与世界观背景")
        camera = _adapter_intent_items(intent, "camera", "完整构图、受控透视")
        style = _adapter_intent_items(intent, "style", "电影感 / 编辑感图像风格")
        sections = [
            ("1. 画布", f"{aspect_ratio}；高质量图像生成；适合作为壁纸、角色定妆照或主视觉。"),
            ("2. 图像类型", f"{task_label}。{style}。{task_hint}".strip("。")),
            ("3. 主体", f"{subject}；{identity}；如涉及成熟造型、时尚姿态、袜装、贴身服装或低机位镜头，人物必须明确成年。"),
            ("4. 角色 / 世界观", source or "保留原始角色身份、世界观、时代线索、色彩倾向与艺术意图。"),
            ("5. 姿态 / 动作", f"{action}；姿态动态但克制、自然、平衡，强调角色气场，不形成身体局部凝视。"),
            ("6. 服装 / 造型", f"{clothing}；强调服装剪裁、面料层次、颜色协调、配饰细节与角色身份感。"),
            ("7. 构图 / 镜头", f"{camera}；主体完整入镜，控制透视，避免切头切脚、偷窥感或身体局部强调。"),
            ("8. 场景 / 背景", f"{scene}；背景元素服务主体，层次清晰但不抢主体，标识或文字非必要时模糊且不可读。"),
            ("9. 光线 / 色彩", "电影级布光，主体与背景清晰分离，控制高光、阴影、对比度与高级调色，可加入轻微胶片颗粒。"),
            ("10. 材质 / 渲染", "皮肤自然，发丝、布料、金属、皮革等材质细节清晰；具备真实反射、粗糙度变化与高质量成片质感。"),
            ("11. 约束", "Safety constraints: non-explicit, no nudity, no minors, no watermark. 非露骨、无裸露、无未成年人、无水印；避免恋物化构图、身体局部凝视和无意义乱码。"),
        ]
    else:
        aspect_ratio = _adapter_intent_items(intent, "aspect_ratio", "Use the requested aspect ratio")
        subject = _adapter_intent_items(intent, "subject", "the requested main subject")
        identity = _adapter_intent_items(intent, "identity", "clearly adult subject if people are involved")
        action = _adapter_intent_items(intent, "action", "natural, restrained, balanced pose")
        clothing = _adapter_intent_items(intent, "clothing", "costume, fabric layers, silhouette, accessories, and styling")
        scene = _adapter_intent_items(intent, "scene", "the requested scene and worldbuilding context")
        camera = _adapter_intent_items(intent, "camera", "balanced full composition with controlled perspective")
        style = _adapter_intent_items(intent, "style", "cinematic/editorial image generation style")
        sections = [
            ("1. Canvas", f"{aspect_ratio}; high-quality image generation; polished wallpaper / character lookbook / key visual format when appropriate."),
            ("2. Image Type", f"{task_label}. {task_hint or style}."),
            ("3. Subject", f"{subject}; {identity}; clearly adult when any mature styling, fashion pose, stockings, tight clothing, or low-angle camera is involved."),
            ("4. Role / Worldbuilding", source or "Preserve the original role, setting, story cues, color palette, and artistic intent."),
            ("5. Pose / Action", f"{action}; dynamic but restrained, balanced and natural, emphasizing character presence rather than body-part focus."),
            ("6. Clothing / Styling", f"{clothing}; emphasize garment construction, layered fabric, tailoring, color harmony, accessories, and costume craftsmanship."),
            ("7. Composition / Camera", f"{camera}; complete subject framing, controlled perspective, no cropped head/feet, no voyeuristic or body-part-focused angle."),
            ("8. Scene / Background", f"{scene}; background elements support the subject, with signage or text blurred unless intentionally required."),
            ("9. Lighting / Color", "Cinematic lighting, clear subject separation, controlled highlights and shadows, refined color grade, optional subtle film grain."),
            ("10. Material / Rendering", "Natural skin texture, detailed hair, realistic fabric/metal/leather response, PBR-like material detail when suitable, high visual clarity."),
            ("11. Constraints", "Safety constraints: non-explicit, no nudity, no minors, no watermark. Also avoid fetish framing, body-part-focused composition, and unreadable random text unless intentionally blurred."),
        ]
    return "\n\n".join(f"[{title}]\n{body}" for title, body in sections).strip()


def _ensure_structured_safe_rewrite(text: str, analysis: dict[str, Any]) -> str:
    cleaned = _clean_safe_rewrite_output(text)
    if _is_structured_adapter_prompt(cleaned):
        return cleaned
    return _build_structured_adapter_prompt(cleaned, analysis)


def _extract_safe_rewrite_prompts(text: str, analysis: dict[str, Any]) -> dict[str, str]:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(_extract_first_json_block(cleaned))
        if isinstance(data, dict):
            zh_prompt = str(data.get("zh_prompt") or data.get("chinese_prompt") or data.get("中文提示") or "").strip()
            en_prompt = str(data.get("en_prompt") or data.get("english_prompt") or data.get("英文提示") or "").strip()
            if zh_prompt or en_prompt:
                fallback = _build_adapter_fallback_prompts(analysis)
                zh_prompt = zh_prompt or fallback["zh_prompt"]
                en_prompt = en_prompt or fallback["en_prompt"]
                return {
                    "zh_prompt": zh_prompt if _is_structured_adapter_prompt(zh_prompt) else _build_structured_adapter_prompt(zh_prompt, analysis, language="zh"),
                    "en_prompt": en_prompt if _is_structured_adapter_prompt(en_prompt) else _build_structured_adapter_prompt(en_prompt, analysis, language="en"),
                }
    except Exception:
        pass

    zh_match = re.search(r"(?:中文提示|改写后的中文提示|zh_prompt)\s*[:：]\s*(.+?)(?=\n\s*(?:英文提示|English Prompt|en_prompt)\s*[:：]|\Z)", cleaned, re.I | re.S)
    en_match = re.search(r"(?:英文提示|English Prompt|en_prompt)\s*[:：]\s*(.+)$", cleaned, re.I | re.S)
    fallback = _build_adapter_fallback_prompts(analysis)
    zh_prompt = _clean_safe_rewrite_output(zh_match.group(1) if zh_match else cleaned) or fallback["zh_prompt"]
    en_prompt = _clean_safe_rewrite_output(en_match.group(1) if en_match else "") or fallback["en_prompt"]
    return {
        "zh_prompt": zh_prompt if _is_structured_adapter_prompt(zh_prompt) else _build_structured_adapter_prompt(zh_prompt, analysis, language="zh"),
        "en_prompt": en_prompt if _is_structured_adapter_prompt(en_prompt) else _build_structured_adapter_prompt(en_prompt, analysis, language="en"),
    }


def _clean_safe_rewrite_output(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith(("text", "prompt")):
            cleaned = cleaned.split("\n", 1)[-1].strip()
    prefixes = (
        "Rewritten prompt:",
        "Rewritten Prompt:",
        "Safe rewritten prompt:",
        "Safe prompt:",
        "改写后的提示词：",
        "安全审核版提示词：",
        "提示词：",
    )
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                changed = True
    return cleaned.strip()


def _ensure_safe_rewrite_constraints(text: str) -> str:
    cleaned = _clean_safe_rewrite_output(text)
    lower = cleaned.lower()
    required_markers = ("non-explicit", "no nudity", "no minors", "no watermark")
    if all(marker in lower for marker in required_markers):
        return cleaned
    return _append_sentence_once(cleaned, SAFE_REWRITE_CONSTRAINT)
