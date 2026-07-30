#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite-backed prompt blocks, split rules, and color schemes."""

from __future__ import annotations

import colorsys
import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .app_config import APP_DATA_DIR


DB_PATH = APP_DATA_DIR / "prompt_library.db"
DB_TIMEOUT = 30
SCHEMA_VERSION = 4
TAG_SPLIT_RE = re.compile(r"[,，;；\n]+")
RULE_MODULE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
COLOR_SCHEME_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_STORE_INIT_LOCK = threading.RLock()
_INITIALIZED_STORE_PATHS: set[str] = set()

COMMON_MODULES = [
    ("goal", "生成目标", "说明图片要解决的问题和最终交付物。"),
    ("subject", "主体", "描述主要人物、物体、环境或核心视觉。"),
    ("scene", "场景环境", "地点、时代、背景元素与环境关系。"),
    ("composition", "构图", "景别、主体位置、留白与空间层次。"),
    ("camera", "视角与镜头", "机位、焦段、景深、透视与运镜。"),
    ("lighting", "光线", "光源方向、软硬、明暗关系和氛围。"),
    ("color", "色彩", "主色、辅助色、冷暖、饱和度和色彩关系。"),
    ("style", "视觉风格", "摄影、插画、3D、电影感或其他媒介风格。"),
    ("material", "材质细节", "皮肤、布料、金属、玻璃、岩石等材质表现。"),
    ("quality", "质量要求", "清晰度、完成度、一致性与输出质量。"),
    ("constraints", "负面约束", "禁止元素、易错点和不得改变的内容。"),
]

TYPE_SPECS: list[dict[str, Any]] = [
    {
        "id": "portrait", "label": "人像人物", "icon": "person",
        "modules": [
            ("identity", "身份", "年龄、职业、角色身份与人物关系。"),
            ("appearance", "外貌", "脸型、五官、肤质、发色与稳定特征。"),
            ("pose", "动作姿态", "身体姿态、手势、重心与动作。"),
            ("expression", "表情视线", "情绪、眼神、视线方向与互动感。"),
            ("clothing", "服装造型", "服装版型、配色、面料和搭配。"),
            ("makeup_hair", "妆发", "发型、妆容、质感和细节。"),
            ("accessories", "配饰", "首饰、鞋履、道具和装饰。"),
            ("anatomy_constraints", "人体约束", "比例、手指、肢体和完整构图约束。"),
        ],
    },
    {
        "id": "landscape", "label": "风景自然", "icon": "landscape",
        "modules": [
            ("landform", "地貌", "山川、平原、峡谷、海岸或其他地形。"),
            ("season", "季节", "季节特征、植被状态和环境变化。"),
            ("weather", "天气", "晴雨、雾雪、风暴与空气状态。"),
            ("time_of_day", "时间", "清晨、正午、黄昏、夜晚及天光。"),
            ("vegetation", "植被", "植物种类、密度、颜色和生长状态。"),
            ("water", "水体", "河流、湖泊、海面、倒影和水流。"),
            ("atmosphere", "大气效果", "云雾、尘埃、光束和空气透视。"),
            ("depth", "前中后景", "空间层次、视觉引导和远近关系。"),
        ],
    },
    {
        "id": "product", "label": "商品电商", "icon": "product",
        "modules": [
            ("product_structure", "商品结构", "外形、比例、组件和必须保持的结构。"),
            ("craft", "材质工艺", "表面材质、加工方式和工艺细节。"),
            ("selling_points", "核心卖点", "需要被视觉强化的功能和利益点。"),
            ("placement", "商品摆放", "角度、支撑、组合方式和空间位置。"),
            ("commercial_lighting", "商业布光", "主光、轮廓光、反射和高光控制。"),
            ("brand_constraints", "品牌限制", "品牌色、Logo、包装和不得变化的细节。"),
        ],
    },
    {
        "id": "food", "label": "美食餐饮", "icon": "food",
        "modules": [
            ("ingredients", "食材", "主要食材、配料、新鲜度和切面。"),
            ("doneness", "熟度状态", "熟度、汁水、温度和烹饪痕迹。"),
            ("plating", "摆盘", "器皿、构图、份量和装饰。"),
            ("food_texture", "食物质感", "酥脆、绵密、流心、油润等口感视觉。"),
            ("steam", "温度气息", "热气、冷凝、水珠和环境温度感。"),
        ],
    },
    {
        "id": "architecture", "label": "建筑外观", "icon": "building",
        "modules": [
            ("architectural_style", "建筑风格", "时代、流派和设计语言。"),
            ("massing", "建筑体量", "体块、层级、比例和轮廓。"),
            ("facade", "立面", "门窗、幕墙、纹理和结构秩序。"),
            ("site", "场地环境", "道路、景观、周边建筑和尺度参照。"),
        ],
    },
    {
        "id": "interior", "label": "室内空间", "icon": "interior",
        "modules": [
            ("space_layout", "空间布局", "功能分区、动线、开间和层高。"),
            ("furniture", "家具", "家具类型、尺度、摆放和风格。"),
            ("surface_materials", "空间材质", "墙地顶、木石金属和织物。"),
            ("soft_furnishing", "软装", "窗帘、地毯、绿植、艺术品和陈设。"),
        ],
    },
    {
        "id": "character", "label": "角色设计", "icon": "character",
        "modules": [
            ("character_identity", "角色身份", "阵营、职业、年龄和叙事职责。"),
            ("worldbuilding", "世界观", "时代、文明、科技或魔法规则。"),
            ("silhouette", "角色轮廓", "体型、视觉重心和辨识度。"),
            ("equipment", "装备道具", "武器、防具、工具和功能。"),
            ("turnaround", "设定视图", "正面、侧面、背面和表情视图要求。"),
        ],
    },
    {
        "id": "scene_concept", "label": "场景概念", "icon": "scene",
        "modules": [
            ("worldbuilding", "世界观", "文明、时代、科技、宗教和社会状态。"),
            ("geography", "地理", "地形、气候、区域关系和自然条件。"),
            ("civilization", "文明痕迹", "建筑、交通、设施和生活方式。"),
            ("environment_story", "环境叙事", "遗留物、事件痕迹和故事线索。"),
            ("scale", "尺度", "人物、建筑、地貌之间的尺度对比。"),
        ],
    },
    {
        "id": "animal", "label": "动物宠物", "icon": "animal",
        "modules": [
            ("species", "物种品种", "动物物种、品种、年龄和体型。"),
            ("fur", "毛发羽毛", "颜色、长度、密度和质感。"),
            ("animal_action", "动作神态", "姿势、运动、表情和互动。"),
            ("habitat", "栖息环境", "自然环境、家庭环境和行为背景。"),
        ],
    },
    {
        "id": "fashion", "label": "服装时尚", "icon": "fashion",
        "modules": [
            ("garment_shape", "服装版型", "廓形、剪裁、层次和结构。"),
            ("fabric", "面料", "织法、垂坠、光泽和透明度。"),
            ("craft", "工艺", "缝线、刺绣、褶皱、印花和装饰。"),
            ("styling", "整体搭配", "上下装、鞋履、配饰和色彩关系。"),
            ("lookbook_pose", "展示姿态", "Lookbook、走秀或陈列姿态。"),
        ],
    },
    {
        "id": "storyboard", "label": "影视分镜", "icon": "storyboard",
        "modules": [
            ("shot_number", "镜头信息", "镜头编号、场次和镜头目的。"),
            ("shot_size", "景别", "远景、全景、中景、近景或特写。"),
            ("camera_position", "机位", "高度、角度、方位和观察关系。"),
            ("blocking", "人物调度", "角色位置、走位和视线关系。"),
            ("action", "动作", "当前帧动作和前后动作衔接。"),
            ("camera_motion", "运镜", "推拉摇移、跟拍、手持和运动速度。"),
            ("continuity", "连续性", "角色、服装、道具、光线和空间连续。"),
        ],
    },
    {
        "id": "illustration", "label": "插画漫画", "icon": "illustration",
        "modules": [
            ("story_moment", "叙事瞬间", "当前画面发生的事件和情绪节点。"),
            ("character_relation", "角色关系", "角色身份、位置和互动。"),
            ("linework", "线条", "线稿粗细、节奏和勾线方式。"),
            ("rendering", "上色方式", "平涂、厚涂、水彩、网点或赛璐璐。"),
            ("speech_area", "对白区域", "对白框、旁白和安全留白。"),
        ],
    },
    {
        "id": "poster", "label": "海报与 KV", "icon": "poster",
        "modules": [
            ("key_visual", "核心视觉", "主视觉元素、视觉钩子和叙事中心。"),
            ("copy", "文案", "必须准确呈现的标题、副标题和信息。"),
            ("information_hierarchy", "信息层级", "标题、说明、行动信息的优先级。"),
            ("layout", "版式", "网格、对齐、留白和视觉动线。"),
            ("text_region", "文字区域", "文案安全区和不得遮挡的位置。"),
            ("brand_color", "品牌色", "品牌主色、辅助色和色彩比例。"),
            ("logo_region", "Logo 区域", "Logo 的位置、尺寸和安全空间。"),
        ],
    },
    {
        "id": "social", "label": "品牌社媒", "icon": "social",
        "modules": [
            ("platform", "发布平台", "小红书、公众号、Banner 等平台。"),
            ("visual_hook", "视觉钩子", "首屏吸引力和信息焦点。"),
            ("headline", "标题区域", "标题文案、字数和可读区域。"),
            ("brand_system", "品牌系统", "品牌色、字体、图形和调性。"),
            ("safe_area", "平台安全区", "头像、按钮和裁切影响区域。"),
        ],
    },
    {
        "id": "infographic", "label": "信息图表", "icon": "infographic",
        "modules": [
            ("data_scope", "信息范围", "需要表达的主题、数据和结论。"),
            ("information_structure", "信息结构", "章节、层级、流程和分组。"),
            ("diagram", "图形关系", "图标、节点、连线和空间关系。"),
            ("annotation", "标注文字", "必须准确显示的标签和说明。"),
            ("readability", "可读性", "字号、对比、密度和阅读顺序。"),
        ],
    },
    {
        "id": "three_d", "label": "3D 视觉", "icon": "cube",
        "modules": [
            ("model_shape", "建模形态", "几何结构、圆角、比例和体块。"),
            ("shader", "材质着色", "粗糙度、金属度、透射和表面细节。"),
            ("render_engine", "渲染表现", "写实、黏土、卡通或产品渲染方式。"),
            ("studio", "摄影棚", "背景、地面、灯组和反射环境。"),
        ],
    },
    {
        "id": "pattern", "label": "图案纹理", "icon": "pattern",
        "modules": [
            ("motif", "图案元素", "主要纹样、辅助元素和符号。"),
            ("repeat", "重复规则", "无缝平铺、镜像、旋转和排列方式。"),
            ("density", "元素密度", "疏密、尺度、节奏和留白。"),
            ("seam", "接缝要求", "边缘连续、无明显接缝和可平铺性。"),
        ],
    },
]


BUILT_IN_COLOR_SCHEMES: list[dict[str, Any]] = [
    {
        "id": "coral-sunrise", "name": "珊瑚日出", "description": "珊瑚红与明亮金黄组成有亲和力的活力暖调。",
        "colors": ["#EF476F", "#FF7F50", "#FFD166", "#FFF1D6", "#22333B"],
        "categories": ["warm", "vivid"], "scenes": ["美妆海报", "夏日活动", "生活方式"], "tags": ["暖色", "活力", "商业"],
        "prompt": "色彩方案采用珊瑚红、暖橙与明亮金黄，奶油白作为大面积留白，深青灰稳定文字和阴影；整体明快、热情、有亲和力，保持暖色主导与清晰层级。",
    },
    {
        "id": "amber-theater", "name": "琥珀剧场", "description": "深酒红、焦糖与琥珀金营造浓郁戏剧光感。",
        "colors": ["#321B1B", "#7A2525", "#C15F2A", "#E6A756", "#F5E3C3"],
        "categories": ["warm", "cinematic"], "scenes": ["电影海报", "餐饮品牌", "复古肖像"], "tags": ["暖色", "戏剧", "质感"],
        "prompt": "色彩方案以深酒红和暗棕为阴影基底，焦糖橙与琥珀金作为主要光色，浅香槟色控制高光；形成浓郁、克制的戏剧氛围和电影级明暗层次。",
    },
    {
        "id": "citrus-market", "name": "柑橘市集", "description": "橘黄、青柠和叶绿构成清爽直接的消费视觉。",
        "colors": ["#FF6B35", "#FFB703", "#D9ED92", "#52B788", "#1B4332"],
        "categories": ["warm", "vivid"], "scenes": ["食品包装", "市集活动", "社媒物料"], "tags": ["清新", "食物", "高饱和"],
        "prompt": "色彩方案使用鲜橙与金黄建立食欲和活力，以青柠浅绿过渡，叶绿和深森林绿平衡画面；色彩清爽、明亮、自然，适合年轻化消费视觉。",
    },
    {
        "id": "vintage-film", "name": "复古胶片", "description": "褪色砖红、芥末黄与灰青复现温和胶片质感。",
        "colors": ["#9E4F3F", "#D29B52", "#E7D9B4", "#6F8A82", "#303B3A"],
        "categories": ["warm", "muted", "cinematic"], "scenes": ["人文纪实", "咖啡品牌", "旅行画面"], "tags": ["复古", "胶片", "低饱和"],
        "prompt": "色彩方案采用褪色砖红、芥末黄和灰青色，搭配旧纸米白与深灰绿；降低整体饱和度和对比，保留温暖颗粒感，呈现自然、怀旧的胶片色彩。",
    },
    {
        "id": "porcelain-mist", "name": "青瓷薄雾", "description": "雾青、浅瓷白和墨绿组成安静通透的东方冷调。",
        "colors": ["#DDEBE7", "#A7C7C0", "#5F8F86", "#2F5D57", "#F7F8F4"],
        "categories": ["cool", "muted"], "scenes": ["东方美学", "护肤产品", "静物摄影"], "tags": ["冷色", "东方", "克制"],
        "prompt": "色彩方案以雾青和浅青瓷色为主，墨绿用于细节与文字，柔和瓷白承担留白；整体低饱和、通透、安静，强调东方审美和细腻材质。",
    },
    {
        "id": "deep-sea-neon", "name": "深海电光", "description": "深海蓝与高亮青绿形成锐利的数字视觉。",
        "colors": ["#071A2B", "#0B3C5D", "#00A8A8", "#4DEEEA", "#D8FFFF"],
        "categories": ["cool", "vivid", "cinematic"], "scenes": ["科技发布", "游戏视觉", "音乐封面"], "tags": ["科技", "霓虹", "高对比"],
        "prompt": "色彩方案以深海蓝和藏青作为大面积暗部，高亮青绿与电光蓝用于发光边缘和关键焦点，冰白点亮信息；整体冷峻、锐利，具有深海般纵深与数字霓虹质感。",
    },
    {
        "id": "alpine-lake", "name": "高山湖泊", "description": "湖蓝、松针绿和雪白构成清冽自然的层次。",
        "colors": ["#EAF4F4", "#A8DADC", "#4D908E", "#2D6A4F", "#1D3557"],
        "categories": ["cool", "muted"], "scenes": ["户外品牌", "风景摄影", "健康生活"], "tags": ["自然", "清冽", "户外"],
        "prompt": "色彩方案使用雪白与浅湖蓝表现空气感，中层采用灰青色，松针绿和深山蓝稳住远景与文字；整体清冽、自然、层次分明，避免过度饱和。",
    },
    {
        "id": "arctic-tech", "name": "极地科技", "description": "冰白、冷灰蓝与深靛蓝适合清晰精密的信息表达。",
        "colors": ["#F5F9FC", "#C9D8E6", "#7EA3C4", "#24527A", "#102A43"],
        "categories": ["cool", "neutral"], "scenes": ["科技产品", "数据界面", "企业视觉"], "tags": ["理性", "专业", "科技"],
        "prompt": "色彩方案以冰白和冷灰蓝构成干净背景，中蓝建立信息层级，深靛蓝用于核心文字和结构；整体理性、精密、清晰，呈现可信赖的现代科技气质。",
    },
    {
        "id": "concrete-silver", "name": "水泥银灰", "description": "多层次银灰搭配炭黑，呈现冷静的工业秩序。",
        "colors": ["#F2F3F4", "#CACFD2", "#909497", "#515A5A", "#1C2833"],
        "categories": ["neutral", "muted"], "scenes": ["建筑画册", "工业产品", "极简版式"], "tags": ["中性", "工业", "极简"],
        "prompt": "色彩方案使用从银白到水泥灰的连续层次，并以炭黑建立最大对比；不引入明显色相，突出结构、材质和留白，整体冷静、精确、具有工业秩序。",
    },
    {
        "id": "graphite-mono", "name": "石墨单色", "description": "石墨黑、纸白和中间灰构成高识别度的单色系统。",
        "colors": ["#111111", "#343434", "#737373", "#BDBDBD", "#F4F4F2"],
        "categories": ["neutral"], "scenes": ["时尚大片", "字体海报", "作品集"], "tags": ["黑白", "单色", "高对比"],
        "prompt": "色彩方案限定为石墨黑、炭灰、中灰、浅灰和纸白，通过明度而非色相建立层级；保持轮廓利落、留白明确，呈现经典、克制的高对比单色视觉。",
    },
    {
        "id": "morandi-garden", "name": "莫兰迪花园", "description": "灰粉、鼠尾草与雾蓝组合出温柔平衡的低饱和色域。",
        "colors": ["#C9A9A6", "#D8C7B5", "#A8B5A2", "#8FA3AD", "#545B62"],
        "categories": ["neutral", "muted"], "scenes": ["家居软装", "女性品牌", "生活摄影"], "tags": ["柔和", "低饱和", "生活感"],
        "prompt": "色彩方案采用灰粉、浅灰褐、鼠尾草绿与雾蓝，深灰仅用于必要的视觉锚点；统一降低饱和度和反差，营造温柔、耐看、平衡的生活美学。",
    },
    {
        "id": "cream-black-gold", "name": "奶油黑金", "description": "柔和象牙白、墨黑与克制金色形成高级商业对比。",
        "colors": ["#F7F1E3", "#D6C6A5", "#B08D57", "#34312D", "#111111"],
        "categories": ["neutral", "warm"], "scenes": ["奢侈品", "珠宝静物", "高端邀请函"], "tags": ["高级", "金色", "商业"],
        "prompt": "色彩方案以象牙白和柔和米色承担大面积背景，墨黑建立清晰结构，古金色仅用于小面积高光和关键细节；整体克制、精致，避免金色泛滥。",
    },
    {
        "id": "urban-red-blue", "name": "都市红蓝", "description": "信号红与深蓝在冷灰背景上形成直接的现代张力。",
        "colors": ["#E63946", "#F1FAEE", "#A8DADC", "#457B9D", "#1D3557"],
        "categories": ["neutral", "vivid"], "scenes": ["品牌海报", "体育视觉", "信息图表"], "tags": ["现代", "对比", "品牌"],
        "prompt": "色彩方案使用信号红作为小面积强焦点，深蓝构成稳定主色，浅灰蓝与暖白负责背景和信息分区；整体清晰、现代、有节奏，保持红蓝面积比例克制。",
    },
    {
        "id": "violet-noir", "name": "紫夜金属", "description": "暗紫、蓝黑与冷银高光呈现神秘的夜间质感。",
        "colors": ["#12101C", "#2D1E46", "#654A8E", "#A7A3C2", "#E8E7F0"],
        "categories": ["cool", "cinematic"], "scenes": ["香水广告", "音乐视觉", "夜景时尚"], "tags": ["神秘", "夜色", "金属"],
        "prompt": "色彩方案以蓝黑和暗紫构成大面积夜色，中紫控制层次，冷银灰与微亮白塑造金属高光；整体神秘、精致、具有电影夜景的纵深感。",
    },
    {
        "id": "desert-cinema", "name": "荒漠电影", "description": "沙岩、铁锈与深青阴影组成宽银幕式的大地色。",
        "colors": ["#E2C290", "#C67C4E", "#8C3F2B", "#35524A", "#172A2A"],
        "categories": ["warm", "muted", "cinematic"], "scenes": ["旅行电影", "汽车广告", "叙事概念图"], "tags": ["大地色", "宽银幕", "叙事"],
        "prompt": "色彩方案以沙岩浅褐和铁锈红表现受光区域，深青绿与近黑青色压住阴影；降低高光饱和度，保留冷暖对照，形成辽阔、粗粝的宽银幕电影感。",
    },
]


class ColorSchemeNotFoundError(ValueError):
    """Raised when a requested active color scheme does not exist."""


def _now() -> int:
    return int(time.time())


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json(value: Any, fallback: Any) -> str:
    if value is None:
        value = fallback
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, type(fallback)):
        return value
    try:
        parsed = json.loads(str(value or ""))
        return parsed if isinstance(parsed, type(fallback)) else fallback
    except Exception:
        return fallback


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = TAG_SPLIT_RE.split(value)
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip().lstrip("#")[:32]
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result[:30]


def _bool(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    return int(str(value or "").strip().lower() in {"1", "true", "yes", "on"})


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={DB_TIMEOUT * 1000}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _module_payload(key: str, label: str, hint: str, *, required: bool = False, kind: str = "common") -> dict[str, Any]:
    return {"key": key, "label": label, "hint": hint, "required": required, "kind": kind, "enabled": True}


def built_in_templates() -> list[dict[str, Any]]:
    common = [_module_payload(*item, required=item[0] in {"goal", "subject"}) for item in COMMON_MODULES]
    result = []
    for index, spec in enumerate(TYPE_SPECS):
        specific = [_module_payload(*item, kind="specific") for item in spec["modules"]]
        result.append({
            "id": f"template_{spec['id']}",
            "primary_type": spec["id"],
            "name": spec["label"],
            "icon": spec.get("icon") or "prompt",
            "description": f"{spec['label']}提示词拆分规则",
            "modules": [*common, *specific],
            "options": {"granularity": "balanced", "max_blocks": 18},
            "sort_order": index,
            "system": True,
        })
    return result


def _initialize_prompt_library_store() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS prompt_library_meta (
                key TEXT PRIMARY KEY,
                value TEXT DEFAULT '',
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS prompt_blocks (
                block_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                module_type TEXT NOT NULL,
                content TEXT NOT NULL,
                compact_content TEXT DEFAULT '',
                english_content TEXT DEFAULT '',
                applicable_types_json TEXT DEFAULT '[]',
                tags_json TEXT DEFAULT '[]',
                favorite INTEGER DEFAULT 0,
                version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                deleted_at INTEGER DEFAULT 0,
                source TEXT DEFAULT 'prompt_library',
                source_rule_id TEXT DEFAULT '',
                source_rule_version INTEGER DEFAULT 0,
                source_rule_snapshot_json TEXT DEFAULT '{}',
                legacy_source_id TEXT DEFAULT '',
                created_at INTEGER,
                updated_at INTEGER,
                last_used_at INTEGER DEFAULT 0,
                use_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_prompt_blocks_module ON prompt_blocks(module_type);
            CREATE INDEX IF NOT EXISTS idx_prompt_blocks_favorite ON prompt_blocks(favorite);
            CREATE INDEX IF NOT EXISTS idx_prompt_blocks_updated ON prompt_blocks(updated_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_blocks_legacy ON prompt_blocks(legacy_source_id) WHERE legacy_source_id <> '';

            CREATE TABLE IF NOT EXISTS prompt_templates (
                template_id TEXT PRIMARY KEY,
                primary_type TEXT NOT NULL,
                name TEXT NOT NULL,
                icon TEXT DEFAULT 'prompt',
                description TEXT DEFAULT '',
                schema_json TEXT DEFAULT '{}',
                sort_order INTEGER DEFAULT 0,
                system INTEGER DEFAULT 0,
                base_template_id TEXT DEFAULT '',
                version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                deleted_at INTEGER DEFAULT 0,
                created_at INTEGER,
                updated_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_prompt_templates_type ON prompt_templates(primary_type);

            CREATE TABLE IF NOT EXISTS prompt_color_schemes (
                color_scheme_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                colors_json TEXT DEFAULT '[]',
                categories_json TEXT DEFAULT '[]',
                scenes_json TEXT DEFAULT '[]',
                tags_json TEXT DEFAULT '[]',
                prompt TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                formula TEXT DEFAULT '',
                base_color TEXT DEFAULT '',
                contrast TEXT DEFAULT 'balanced',
                temperature TEXT DEFAULT 'auto',
                neutral_balance INTEGER DEFAULT 1,
                use_ratio INTEGER DEFAULT 1,
                favorite INTEGER DEFAULT 0,
                system INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                deleted_at INTEGER DEFAULT 0,
                legacy_source_id TEXT DEFAULT '',
                created_at INTEGER,
                updated_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_prompt_color_schemes_favorite ON prompt_color_schemes(favorite);
            CREATE INDEX IF NOT EXISTS idx_prompt_color_schemes_system ON prompt_color_schemes(system, sort_order);
            CREATE INDEX IF NOT EXISTS idx_prompt_color_schemes_status ON prompt_color_schemes(status);

            CREATE TABLE IF NOT EXISTS prompt_color_scheme_migrations (
                migration_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target_id TEXT DEFAULT '',
                imported_at INTEGER
            );
            """
        )
        block_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(prompt_blocks)").fetchall()
        }
        if "status" not in block_columns:
            conn.execute("ALTER TABLE prompt_blocks ADD COLUMN status TEXT DEFAULT 'active'")
        if "deleted_at" not in block_columns:
            conn.execute("ALTER TABLE prompt_blocks ADD COLUMN deleted_at INTEGER DEFAULT 0")
        if "source_rule_id" not in block_columns:
            conn.execute("ALTER TABLE prompt_blocks ADD COLUMN source_rule_id TEXT DEFAULT ''")
        if "source_rule_version" not in block_columns:
            conn.execute("ALTER TABLE prompt_blocks ADD COLUMN source_rule_version INTEGER DEFAULT 0")
        if "source_rule_snapshot_json" not in block_columns:
            conn.execute("ALTER TABLE prompt_blocks ADD COLUMN source_rule_snapshot_json TEXT DEFAULT '{}'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_blocks_status ON prompt_blocks(status)")
        template_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(prompt_templates)").fetchall()
        }
        if "base_template_id" not in template_columns:
            conn.execute("ALTER TABLE prompt_templates ADD COLUMN base_template_id TEXT DEFAULT ''")
        if "version" not in template_columns:
            conn.execute("ALTER TABLE prompt_templates ADD COLUMN version INTEGER DEFAULT 1")
        if "status" not in template_columns:
            conn.execute("ALTER TABLE prompt_templates ADD COLUMN status TEXT DEFAULT 'active'")
        if "deleted_at" not in template_columns:
            conn.execute("ALTER TABLE prompt_templates ADD COLUMN deleted_at INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_templates_status ON prompt_templates(status)")
        now = _now()
        conn.execute(
            "INSERT OR REPLACE INTO prompt_library_meta(key, value, updated_at) VALUES('schema_version', ?, ?)",
            (str(SCHEMA_VERSION), now),
        )
        for template in built_in_templates():
            conn.execute(
                """
                INSERT INTO prompt_templates(
                    template_id, primary_type, name, icon, description,
                    schema_json, sort_order, system, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                    primary_type=excluded.primary_type,
                    name=excluded.name,
                    icon=excluded.icon,
                    description=excluded.description,
                    schema_json=excluded.schema_json,
                    sort_order=excluded.sort_order,
                    system=1,
                    status='active',
                    deleted_at=0,
                    updated_at=excluded.updated_at
                """,
                (
                    template["id"], template["primary_type"], template["name"], template["icon"],
                    template["description"], _json({"modules": template["modules"], "options": template["options"]}, {}),
                    int(template["sort_order"]), now, now,
                ),
            )
        built_in_color_ids = {str(scheme["id"]) for scheme in BUILT_IN_COLOR_SCHEMES}
        for sort_order, scheme in enumerate(BUILT_IN_COLOR_SCHEMES):
            existing_scheme = conn.execute(
                "SELECT system FROM prompt_color_schemes WHERE color_scheme_id=?",
                (scheme["id"],),
            ).fetchone()
            if existing_scheme and not bool(existing_scheme["system"]):
                print(f"⚠️ 内置色彩方案 ID 与用户方案冲突，已保留用户数据：{scheme['id']}")
                continue
            colors = [str(color).upper() for color in scheme["colors"]]
            categories = list(scheme["categories"])
            formula = (
                "monochromatic" if "neutral" in categories
                else "split_complementary" if "vivid" in categories
                else "analogous"
            )
            conn.execute(
                """
                INSERT INTO prompt_color_schemes(
                    color_scheme_id, name, description, colors_json,
                    categories_json, scenes_json, tags_json, prompt,
                    industry, formula, base_color, contrast, temperature,
                    neutral_balance, use_ratio, favorite, system, sort_order,
                    status, deleted_at, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, 'balanced', 'auto', 1, 1, 0, 1, ?, 'active', 0, ?, ?)
                ON CONFLICT(color_scheme_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    colors_json=excluded.colors_json,
                    categories_json=excluded.categories_json,
                    scenes_json=excluded.scenes_json,
                    tags_json=excluded.tags_json,
                    prompt=excluded.prompt,
                    formula=excluded.formula,
                    base_color=excluded.base_color,
                    system=1,
                    sort_order=excluded.sort_order,
                    status='active',
                    deleted_at=0,
                    updated_at=excluded.updated_at
                """,
                (
                    scheme["id"], scheme["name"], scheme["description"], _json(colors, []),
                    _json(categories, []), _json(scheme["scenes"], []), _json(scheme["tags"], []),
                    scheme["prompt"], formula, colors[0], sort_order, now, now,
                ),
            )
        if built_in_color_ids:
            placeholders = ",".join("?" for _ in built_in_color_ids)
            conn.execute(
                f"""
                UPDATE prompt_color_schemes
                SET status='deleted', deleted_at=?, updated_at=?
                WHERE system=1 AND status='active'
                  AND color_scheme_id NOT IN ({placeholders})
                """,
                (now, now, *sorted(built_in_color_ids)),
            )
        else:
            conn.execute(
                """
                UPDATE prompt_color_schemes
                SET status='deleted', deleted_at=?, updated_at=?
                WHERE system=1 AND status='active'
                """,
                (now, now),
            )


def init_prompt_library_store(
    legacy_style_presets_file: Path | None = None,
) -> None:
    store_key = str(DB_PATH.expanduser().resolve())
    with _STORE_INIT_LOCK:
        if store_key not in _INITIALIZED_STORE_PATHS or not DB_PATH.exists():
            _initialize_prompt_library_store()
            _INITIALIZED_STORE_PATHS.add(store_key)
        if legacy_style_presets_file:
            migrate_legacy_style_presets(legacy_style_presets_file)


def _row_block(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["block_id"],
        "name": row["name"],
        "module_type": row["module_type"],
        "content": row["content"],
        "compact_content": row["compact_content"],
        "english_content": row["english_content"],
        "applicable_types": _loads(row["applicable_types_json"], []),
        "tags": _loads(row["tags_json"], []),
        "favorite": bool(row["favorite"]),
        "version": int(row["version"] or 1),
        "status": row["status"] or "active",
        "deleted_at": int(row["deleted_at"] or 0),
        "source": row["source"],
        "source_rule_id": row["source_rule_id"],
        "source_rule_version": int(row["source_rule_version"] or 0),
        "source_rule_snapshot": _loads(row["source_rule_snapshot_json"], {}),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
        "last_used_at": int(row["last_used_at"] or 0),
        "use_count": int(row["use_count"] or 0),
    }


def _row_template(row: sqlite3.Row) -> dict[str, Any]:
    schema = _loads(row["schema_json"], {})
    return {
        "id": row["template_id"],
        "primary_type": row["primary_type"],
        "name": row["name"],
        "icon": row["icon"],
        "description": row["description"],
        "modules": schema.get("modules") if isinstance(schema.get("modules"), list) else [],
        "options": schema.get("options") if isinstance(schema.get("options"), dict) else {},
        "sort_order": int(row["sort_order"] or 0),
        "system": bool(row["system"]),
        "base_template_id": row["base_template_id"],
        "version": int(row["version"] or 1),
        "status": row["status"] or "active",
        "deleted_at": int(row["deleted_at"] or 0),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def _string_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if isinstance(value, str):
        raw_items = TAG_SPLIT_RE.split(value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = str(raw or "").strip()[:max_length]
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= max_items:
            break
    return result


def _normalize_color_scheme_id(value: Any, *, required: bool = False) -> str:
    color_scheme_id = str(value or "").strip()
    if not color_scheme_id and not required:
        return ""
    if not COLOR_SCHEME_ID_RE.fullmatch(color_scheme_id):
        raise ValueError("色彩方案 ID 无效")
    return color_scheme_id


def _normalize_colors(value: Any) -> list[str]:
    raw_colors = value if isinstance(value, (list, tuple)) else []
    colors = [str(color or "").strip().upper() for color in raw_colors[:5]]
    if len(colors) < 3 or any(not HEX_COLOR_RE.fullmatch(color) for color in colors):
        raise ValueError("色彩方案至少需要 3 个有效的 HEX 色值")
    while len(colors) < 5:
        colors.append(colors[-1])
    return colors


def _infer_color_categories(colors: list[str]) -> list[str]:
    values: list[tuple[float, float, float]] = []
    for color in colors:
        channels = tuple(int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
        hue, lightness, saturation = colorsys.rgb_to_hls(*channels)
        values.append((hue * 360, saturation * 100, lightness * 100))
    average_saturation = sum(value[1] for value in values) / max(1, len(values))
    warm = sum(1 for hue, _, _ in values if hue <= 75 or hue >= 330)
    cool = sum(1 for hue, _, _ in values if 150 <= hue <= 285)
    categories = ["warm" if warm > cool else "cool" if cool > warm else "neutral"]
    if average_saturation >= 58:
        categories.append("vivid")
    if average_saturation <= 42:
        categories.append("muted")
    lightness_values = [value[2] for value in values]
    if min(lightness_values) <= 22 and max(lightness_values) >= 78 and average_saturation >= 32:
        categories.append("cinematic")
    return categories


def _row_color_scheme(row: sqlite3.Row) -> dict[str, Any]:
    system = bool(row["system"])
    return {
        "id": row["color_scheme_id"],
        "name": row["name"],
        "description": row["description"],
        "colors": _loads(row["colors_json"], []),
        "categories": _loads(row["categories_json"], []),
        "scenes": _loads(row["scenes_json"], []),
        "tags": _loads(row["tags_json"], []),
        "prompt": row["prompt"],
        "industry": row["industry"],
        "formula": row["formula"],
        "base_color": row["base_color"],
        "contrast": row["contrast"] or "balanced",
        "temperature": row["temperature"] or "auto",
        "neutral_balance": bool(row["neutral_balance"]),
        "use_ratio": bool(row["use_ratio"]),
        "custom": not system,
        "favorite": bool(row["favorite"]),
        "system": system,
        "sort_order": int(row["sort_order"] or 0),
        "status": row["status"] or "active",
        "deleted_at": int(row["deleted_at"] or 0),
        "created_at": int(row["created_at"] or 0),
        "updated_at": int(row["updated_at"] or 0),
    }


def _normalize_color_scheme_payload(data: dict[str, Any], existing: sqlite3.Row | None = None) -> dict[str, Any]:
    current = _row_color_scheme(existing) if existing else {}

    def field(name: str, fallback: Any = None) -> Any:
        return data[name] if name in data else current.get(name, fallback)

    name = str(field("name") or "").strip()[:100]
    if not name:
        raise ValueError("请输入色彩方案名称")
    colors = _normalize_colors(field("colors", []))
    prompt = str(field("prompt") or "").strip()[:4000]
    if not prompt:
        raise ValueError("请输入色彩方案提示词")
    base_color = str(field("base_color") or colors[0]).strip().upper()
    if not HEX_COLOR_RE.fullmatch(base_color):
        raise ValueError("基色必须使用完整的 HEX 格式")
    category_source = data.get("categories") if "categories" in data else ([] if "colors" in data else current.get("categories"))
    categories = _string_list(category_source, max_items=12, max_length=32)
    if not categories:
        categories = _infer_color_categories(colors)
    contrast = str(field("contrast") or "balanced").strip().lower()
    if contrast not in {"soft", "balanced", "high"}:
        contrast = "balanced"
    temperature = str(field("temperature") or "auto").strip().lower()
    if temperature not in {"auto", "warm", "cool"}:
        temperature = "auto"
    return {
        "name": name,
        "description": str(field("description") or "手动创建的自定义配色方案。").strip()[:500],
        "colors": colors,
        "categories": categories,
        "scenes": _string_list(field("scenes"), max_items=8, max_length=80),
        "tags": _string_list(field("tags"), max_items=12, max_length=32),
        "prompt": prompt,
        "industry": str(field("industry") or "").strip()[:64],
        "formula": str(field("formula") or "").strip()[:64],
        "base_color": base_color,
        "contrast": contrast,
        "temperature": temperature,
        "neutral_balance": bool(_bool(field("neutral_balance", True))),
        "use_ratio": bool(_bool(field("use_ratio", True))),
    }


def _write_custom_color_scheme(
    conn: sqlite3.Connection,
    color_scheme_id: str,
    payload: dict[str, Any],
    *,
    existing: sqlite3.Row | None,
    legacy_source_id: str = "",
) -> sqlite3.Row:
    now = _now()
    favorite = int(existing["favorite"] or 0) if existing else 0
    created_at = int(existing["created_at"] or now) if existing else now
    sort_order = int(existing["sort_order"] or 0) if existing else 0
    conn.execute(
        """
        INSERT INTO prompt_color_schemes(
            color_scheme_id, name, description, colors_json, categories_json,
            scenes_json, tags_json, prompt, industry, formula, base_color,
            contrast, temperature, neutral_balance, use_ratio, favorite,
            system, sort_order, status, deleted_at, legacy_source_id,
            created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 'active', 0, ?, ?, ?)
        ON CONFLICT(color_scheme_id) DO UPDATE SET
            name=excluded.name,
            description=excluded.description,
            colors_json=excluded.colors_json,
            categories_json=excluded.categories_json,
            scenes_json=excluded.scenes_json,
            tags_json=excluded.tags_json,
            prompt=excluded.prompt,
            industry=excluded.industry,
            formula=excluded.formula,
            base_color=excluded.base_color,
            contrast=excluded.contrast,
            temperature=excluded.temperature,
            neutral_balance=excluded.neutral_balance,
            use_ratio=excluded.use_ratio,
            status='active',
            deleted_at=0,
            updated_at=excluded.updated_at
        """,
        (
            color_scheme_id, payload["name"], payload["description"], _json(payload["colors"], []),
            _json(payload["categories"], []), _json(payload["scenes"], []), _json(payload["tags"], []),
            payload["prompt"], payload["industry"], payload["formula"], payload["base_color"],
            payload["contrast"], payload["temperature"], int(payload["neutral_balance"]),
            int(payload["use_ratio"]), favorite, sort_order, legacy_source_id, created_at, now,
        ),
    )
    return conn.execute(
        "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
        (color_scheme_id,),
    ).fetchone()


def list_color_schemes() -> list[dict[str, Any]]:
    init_prompt_library_store()
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM prompt_color_schemes
            WHERE status='active'
            ORDER BY system ASC,
                CASE WHEN system=0 THEN updated_at END DESC,
                sort_order ASC,
                name ASC
            """
        ).fetchall()
    return [_row_color_scheme(row) for row in rows]


def save_color_scheme(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("请求体格式错误")
    init_prompt_library_store()
    requested_id = _normalize_color_scheme_id(data.get("id") or data.get("color_scheme_id"))
    color_scheme_id = requested_id or _id("color")
    with _db() as conn:
        # Keep the status check and UPSERT in one write transaction. Otherwise
        # a concurrent delete could commit between them and be resurrected.
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
            (color_scheme_id,),
        ).fetchone()
        if existing and bool(existing["system"]):
            raise ValueError("内置色彩方案不能修改")
        if existing and str(existing["status"] or "active") != "active":
            raise ColorSchemeNotFoundError("色彩方案已删除，不能继续修改")
        payload = _normalize_color_scheme_payload(data, existing)
        row = _write_custom_color_scheme(conn, color_scheme_id, payload, existing=existing)
    return _row_color_scheme(row)


def delete_color_scheme(color_scheme_id: str) -> dict[str, Any]:
    clean_id = _normalize_color_scheme_id(color_scheme_id, required=True)
    init_prompt_library_store()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=? AND status='active'",
            (clean_id,),
        ).fetchone()
        if not row:
            raise ColorSchemeNotFoundError("色彩方案不存在")
        if bool(row["system"]):
            raise ValueError("内置色彩方案不能删除")
        deleted_at = _now()
        conn.execute(
            "UPDATE prompt_color_schemes SET status='deleted', deleted_at=?, updated_at=? WHERE color_scheme_id=?",
            (deleted_at, deleted_at, clean_id),
        )
        deleted = conn.execute(
            "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
            (clean_id,),
        ).fetchone()
    return _row_color_scheme(deleted)


def set_color_scheme_favorite(color_scheme_id: str, favorite: Any) -> dict[str, Any]:
    clean_id = _normalize_color_scheme_id(color_scheme_id, required=True)
    if not isinstance(favorite, bool):
        raise ValueError("favorite 必须是布尔值")
    init_prompt_library_store()
    with _db() as conn:
        cursor = conn.execute(
            """
            UPDATE prompt_color_schemes
            SET favorite=?
            WHERE color_scheme_id=? AND status='active'
            """,
            (int(favorite), clean_id),
        )
        if not cursor.rowcount:
            raise ColorSchemeNotFoundError("色彩方案不存在")
        row = conn.execute(
            "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
            (clean_id,),
        ).fetchone()
    return _row_color_scheme(row)


def migrate_legacy_color_schemes(custom_schemes: Any, favorite_ids: Any) -> dict[str, Any]:
    if not isinstance(custom_schemes, list) or not isinstance(favorite_ids, list):
        raise ValueError("迁移数据格式错误")
    custom_items = custom_schemes
    favorite_items = favorite_ids
    if len(custom_items) > 1000 or len(favorite_items) > 2000:
        raise ValueError("迁移数据过多")
    init_prompt_library_store()
    imported_custom_schemes = 0
    imported_favorites = 0
    skipped_items = 0
    failed_custom_schemes = 0
    failed_favorites = 0
    unresolved_custom_ids: set[str] = set()
    with _db() as conn:
        # Serialize the check-and-insert migration with normal saves so legacy
        # payloads can never overwrite a concurrently-created scheme.
        conn.execute("BEGIN IMMEDIATE")
        for raw in custom_items:
            if not isinstance(raw, dict):
                skipped_items += 1
                failed_custom_schemes += 1
                continue
            try:
                legacy_id = _normalize_color_scheme_id(
                    raw.get("id") or raw.get("color_scheme_id"),
                    required=True,
                )
                payload = _normalize_color_scheme_payload(raw)
            except ValueError:
                skipped_items += 1
                failed_custom_schemes += 1
                continue
            payload_digest = hashlib.sha256(_json(payload, {}).encode("utf-8")).hexdigest()[:16]
            migration_key = f"custom:{legacy_id}:{payload_digest}"
            if conn.execute(
                "SELECT 1 FROM prompt_color_scheme_migrations WHERE migration_key=?",
                (migration_key,),
            ).fetchone():
                skipped_items += 1
                continue
            existing = conn.execute(
                "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
                (legacy_id,),
            ).fetchone()
            if existing:
                if str(existing["status"] or "active") != "active":
                    conn.execute(
                        """
                        INSERT INTO prompt_color_scheme_migrations(
                            migration_key, source, target_id, imported_at
                        ) VALUES(?, 'local_storage_v1', ?, ?)
                        """,
                        (migration_key, legacy_id, _now()),
                    )
                    skipped_items += 1
                    continue
                if bool(existing["system"]):
                    unresolved_custom_ids.add(legacy_id)
                    skipped_items += 1
                    failed_custom_schemes += 1
                    continue
                existing_payload = _normalize_color_scheme_payload({}, existing)
                if existing_payload != payload:
                    unresolved_custom_ids.add(legacy_id)
                    skipped_items += 1
                    failed_custom_schemes += 1
                    continue
            else:
                _write_custom_color_scheme(
                    conn,
                    legacy_id,
                    payload,
                    existing=None,
                    legacy_source_id=legacy_id,
                )
                imported_custom_schemes += 1
            conn.execute(
                """
                INSERT INTO prompt_color_scheme_migrations(
                    migration_key, source, target_id, imported_at
                ) VALUES(?, 'local_storage_v1', ?, ?)
                """,
                (migration_key, legacy_id, _now()),
            )

        for raw_id in favorite_items:
            try:
                color_scheme_id = _normalize_color_scheme_id(raw_id, required=True)
            except ValueError:
                skipped_items += 1
                failed_favorites += 1
                continue
            migration_key = f"favorite:{color_scheme_id}"
            if conn.execute(
                "SELECT 1 FROM prompt_color_scheme_migrations WHERE migration_key=?",
                (migration_key,),
            ).fetchone():
                skipped_items += 1
                continue
            if color_scheme_id in unresolved_custom_ids:
                skipped_items += 1
                failed_favorites += 1
                continue
            existing = conn.execute(
                "SELECT * FROM prompt_color_schemes WHERE color_scheme_id=?",
                (color_scheme_id,),
            ).fetchone()
            if not existing:
                skipped_items += 1
                failed_favorites += 1
                continue
            conn.execute(
                """
                INSERT INTO prompt_color_scheme_migrations(
                    migration_key, source, target_id, imported_at
                ) VALUES(?, 'local_storage_v1', ?, ?)
                """,
                (migration_key, color_scheme_id, _now()),
            )
            if str(existing["status"] or "active") != "active":
                skipped_items += 1
                continue
            if not bool(existing["favorite"]):
                conn.execute(
                    "UPDATE prompt_color_schemes SET favorite=1 WHERE color_scheme_id=?",
                    (color_scheme_id,),
                )
                imported_favorites += 1

    return {
        "imported_custom_schemes": imported_custom_schemes,
        "imported_favorites": imported_favorites,
        "skipped_items": skipped_items,
        "failed_custom_schemes": failed_custom_schemes,
        "failed_favorites": failed_favorites,
        "migration_complete": failed_custom_schemes == 0 and failed_favorites == 0,
        "color_schemes": list_color_schemes(),
    }


def list_prompt_templates() -> list[dict[str, Any]]:
    init_prompt_library_store()
    with _db() as conn:
        rows = conn.execute("SELECT * FROM prompt_templates WHERE status='active' ORDER BY system DESC, sort_order ASC, updated_at DESC, name ASC").fetchall()
    return [_row_template(row) for row in rows]


def _normalize_rule_modules(value: Any) -> list[dict[str, Any]]:
    raw_modules = value if isinstance(value, list) else []
    modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_modules[:40]:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if not RULE_MODULE_KEY_RE.fullmatch(key):
            raise ValueError(f"模块 Key 无效：{key or '空值'}")
        if key in seen:
            raise ValueError(f"模块 Key 重复：{key}")
        seen.add(key)
        kind = str(raw.get("kind") or "custom").strip().lower()
        if kind not in {"common", "specific", "custom"}:
            kind = "custom"
        modules.append({
            "key": key,
            "label": str(raw.get("label") or key).strip()[:80] or key,
            "hint": str(raw.get("hint") or "").strip()[:500],
            "required": bool(raw.get("required")),
            "kind": kind,
            "enabled": raw.get("enabled") is not False,
        })
    if not modules:
        raise ValueError("拆分规则至少需要一个模块")
    if not any(module["enabled"] for module in modules):
        raise ValueError("拆分规则至少需要启用一个模块")
    return modules


def _normalize_rule_options(value: Any) -> dict[str, Any]:
    options = value if isinstance(value, dict) else {}
    granularity = str(options.get("granularity") or "balanced").strip().lower()
    if granularity not in {"compact", "balanced", "detailed"}:
        granularity = "balanced"
    try:
        max_blocks = int(options.get("max_blocks") or 18)
    except (TypeError, ValueError):
        max_blocks = 18
    return {"granularity": granularity, "max_blocks": max(3, min(30, max_blocks))}


def resolve_prompt_template(rule_id: str = "", primary_type: str = "") -> dict[str, Any] | None:
    init_prompt_library_store()
    clean_rule_id = str(rule_id or "").strip()
    clean_primary_type = str(primary_type or "").strip()
    with _db() as conn:
        if clean_rule_id:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=? AND status='active'",
                (clean_rule_id,),
            ).fetchone()
        elif clean_primary_type:
            row = conn.execute(
                "SELECT * FROM prompt_templates WHERE primary_type=? AND system=1 AND status='active' ORDER BY sort_order LIMIT 1",
                (clean_primary_type,),
            ).fetchone()
        else:
            row = None
    return _row_template(row) if row else None


def save_prompt_template(data: dict[str, Any]) -> dict[str, Any]:
    init_prompt_library_store()
    template_id = str(data.get("id") or data.get("template_id") or "").strip()
    requested_base_id = str(data.get("base_template_id") or data.get("source_rule_id") or "").strip()
    now = _now()
    with _db() as conn:
        existing = conn.execute("SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)).fetchone() if template_id else None
        if template_id and not existing:
            raise ValueError("拆分规则不存在")
        if existing and bool(existing["system"]):
            raise ValueError("内置拆分规则不能直接修改，请先创建自定义副本")
        if existing and str(existing["status"] or "active") != "active":
            raise ValueError("拆分规则不存在")
        source = existing
        if not source:
            if not requested_base_id:
                raise ValueError("请选择要自定义的基础规则")
            source = conn.execute(
                "SELECT * FROM prompt_templates WHERE template_id=? AND status='active'",
                (requested_base_id,),
            ).fetchone()
            if not source:
                raise ValueError("基础拆分规则不存在")
        source_payload = _row_template(source)
        primary_type = str(source["primary_type"] or "").strip()
        base_template_id = str(source["base_template_id"] or "").strip() or str(source["template_id"] or "").strip()
        default_name = source_payload["name"] if existing else f"{source_payload['name']} · 自定义"
        name = str(data.get("name") or default_name).strip()[:120]
        if not name:
            raise ValueError("请输入拆分规则名称")
        description = str(data.get("description") or "").strip()[:500]
        modules = _normalize_rule_modules(data.get("modules") if isinstance(data.get("modules"), list) else source_payload["modules"])
        options = _normalize_rule_options(data.get("options") if isinstance(data.get("options"), dict) else source_payload.get("options"))
        schema_json = _json({"modules": modules, "options": options}, {})
        if not template_id:
            template_id = _id("rule")
            created_at = now
            version = 1
            max_sort = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM prompt_templates").fetchone()[0]
            sort_order = int(max_sort or 0) + 1
            icon = str(source["icon"] or "prompt")
        else:
            created_at = int(existing["created_at"] or now)
            version = int(existing["version"] or 1) + 1
            sort_order = int(existing["sort_order"] or 0)
            icon = str(existing["icon"] or source["icon"] or "prompt")
        conn.execute(
            """
            INSERT INTO prompt_templates(
                template_id, primary_type, name, icon, description, schema_json,
                sort_order, system, base_template_id, version, status, deleted_at,
                created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 'active', 0, ?, ?)
            ON CONFLICT(template_id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                schema_json=excluded.schema_json,
                version=excluded.version,
                status='active',
                deleted_at=0,
                updated_at=excluded.updated_at
            """,
            (
                template_id, primary_type, name, icon, description, schema_json,
                sort_order, base_template_id, version, created_at, now,
            ),
        )
        row = conn.execute("SELECT * FROM prompt_templates WHERE template_id=?", (template_id,)).fetchone()
    return _row_template(row)


def delete_prompt_template(template_id: str) -> dict[str, Any]:
    init_prompt_library_store()
    clean_id = str(template_id or "").strip()
    with _db() as conn:
        row = conn.execute("SELECT * FROM prompt_templates WHERE template_id=? AND status='active'", (clean_id,)).fetchone()
        if not row:
            raise ValueError("拆分规则不存在")
        if bool(row["system"]):
            raise ValueError("内置拆分规则不能删除")
        deleted_at = _now()
        conn.execute(
            "UPDATE prompt_templates SET status='deleted', deleted_at=?, updated_at=? WHERE template_id=?",
            (deleted_at, deleted_at, clean_id),
        )
        deleted = conn.execute("SELECT * FROM prompt_templates WHERE template_id=?", (clean_id,)).fetchone()
    return _row_template(deleted)


def list_prompt_blocks(
    *, query: str = "", module_type: str = "", primary_type: str = "",
    favorite: bool = False, limit: int = 500, offset: int = 0,
) -> dict[str, Any]:
    init_prompt_library_store()
    clauses = ["status='active'"]
    params: list[Any] = []
    if module_type:
        clauses.append("module_type=?")
        params.append(module_type)
    if primary_type:
        clauses.append("(applicable_types_json='[]' OR applicable_types_json LIKE ?)")
        params.append(f'%"{primary_type}"%')
    if favorite:
        clauses.append("favorite=1")
    clean_query = str(query or "").strip()
    if clean_query:
        token = f"%{clean_query}%"
        clauses.append("(name LIKE ? OR content LIKE ? OR compact_content LIKE ? OR english_content LIKE ? OR tags_json LIKE ?)")
        params.extend([token, token, token, token, token])
    where = " AND ".join(clauses)
    with _db() as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM prompt_blocks WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT * FROM prompt_blocks
            WHERE {where}
            ORDER BY favorite DESC, use_count DESC, COALESCE(last_used_at, 0) DESC, updated_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, max(1, min(1000, int(limit or 500))), max(0, int(offset or 0))],
        ).fetchall()
    return {"items": [_row_block(row) for row in rows], "total": total}


def save_prompt_block(data: dict[str, Any]) -> dict[str, Any]:
    init_prompt_library_store()
    name = str(data.get("name") or data.get("label") or "").strip()[:120]
    content = str(data.get("content") or data.get("text") or "").strip()
    module_type = str(data.get("module_type") or data.get("type") or "custom").strip()[:64]
    if not name:
        raise ValueError("素材块名称不能为空")
    if not content:
        raise ValueError("素材块内容不能为空")
    block_id = str(data.get("id") or data.get("block_id") or _id("block")).strip()
    now = _now()
    with _db() as conn:
        existing = conn.execute("SELECT * FROM prompt_blocks WHERE block_id=?", (block_id,)).fetchone()
        version = int(existing["version"] or 1) + 1 if existing and content != str(existing["content"] or "") else int(existing["version"] or 1) if existing else 1
        created_at = int(existing["created_at"] or now) if existing else int(data.get("created_at") or now)
        last_used_at = int(existing["last_used_at"] or 0) if existing else int(data.get("last_used_at") or 0)
        use_count = int(existing["use_count"] or 0) if existing else int(data.get("use_count") or 0)
        legacy_source_id = str(existing["legacy_source_id"] or "") if existing else str(data.get("legacy_source_id") or "")
        source_rule_id = str(data.get("source_rule_id") if "source_rule_id" in data else (existing["source_rule_id"] if existing else ""))[:120]
        source_rule_version = int(data.get("source_rule_version") if "source_rule_version" in data else (existing["source_rule_version"] if existing else 0) or 0)
        source_rule_snapshot = data.get("source_rule_snapshot") if isinstance(data.get("source_rule_snapshot"), dict) else (_loads(existing["source_rule_snapshot_json"], {}) if existing else {})
        conn.execute(
            """
            INSERT INTO prompt_blocks(
                block_id, name, module_type, content, compact_content, english_content,
                applicable_types_json, tags_json, favorite, version, status, deleted_at,
                source, source_rule_id, source_rule_version, source_rule_snapshot_json,
                legacy_source_id, created_at, updated_at, last_used_at, use_count
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(block_id) DO UPDATE SET
                name=excluded.name,
                module_type=excluded.module_type,
                content=excluded.content,
                compact_content=excluded.compact_content,
                english_content=excluded.english_content,
                applicable_types_json=excluded.applicable_types_json,
                tags_json=excluded.tags_json,
                favorite=excluded.favorite,
                version=excluded.version,
                status='active',
                deleted_at=0,
                source=excluded.source,
                source_rule_id=excluded.source_rule_id,
                source_rule_version=excluded.source_rule_version,
                source_rule_snapshot_json=excluded.source_rule_snapshot_json,
                updated_at=excluded.updated_at
            """,
            (
                block_id, name, module_type, content,
                str(data.get("compact_content") or "")[:50000],
                str(data.get("english_content") or "")[:50000],
                _json(_tags(data.get("applicable_types")), []),
                _json(_tags(data.get("tags")), []),
                _bool(data.get("favorite")), version,
                str(data.get("source") or "prompt_library")[:80],
                source_rule_id, source_rule_version, _json(source_rule_snapshot, {}), legacy_source_id,
                created_at, now, last_used_at, use_count,
            ),
        )
        row = conn.execute("SELECT * FROM prompt_blocks WHERE block_id=?", (block_id,)).fetchone()
    return _row_block(row)


def delete_prompt_block(block_id: str) -> dict[str, Any]:
    block_id = str(block_id or "").strip()
    init_prompt_library_store()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM prompt_blocks WHERE block_id=? AND status='active'",
            (block_id,),
        ).fetchone()
        if not row:
            raise ValueError("素材块不存在")
        deleted_at = _now()
        conn.execute(
            "UPDATE prompt_blocks SET status='deleted', deleted_at=?, updated_at=? WHERE block_id=?",
            (deleted_at, deleted_at, block_id),
        )
        deleted = conn.execute("SELECT * FROM prompt_blocks WHERE block_id=?", (block_id,)).fetchone()
    return _row_block(deleted)


def mark_prompt_block_used(block_id: str) -> dict[str, Any]:
    block_id = str(block_id or "").strip()
    init_prompt_library_store()
    with _db() as conn:
        conn.execute(
            "UPDATE prompt_blocks SET use_count=use_count+1, last_used_at=? WHERE block_id=? AND status='active'",
            (_now(), block_id),
        )
        row = conn.execute(
            "SELECT * FROM prompt_blocks WHERE block_id=? AND status='active'",
            (block_id,),
        ).fetchone()
        if not row:
            raise ValueError("素材块不存在")
    return _row_block(row)


def _read_legacy(path: Path | None, root_key: str) -> list[dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8") or "{}")
        items = payload.get(root_key) if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    except Exception:
        return []


def migrate_legacy_style_presets(legacy_style_presets_file: Path | None) -> int:
    presets = _read_legacy(legacy_style_presets_file, "presets")
    imported_blocks = 0
    for item in presets:
        legacy_id = str(item.get("id") or "").strip()
        content = str(item.get("prompt_style") or item.get("promptTemplate") or item.get("positive_style") or "").strip()
        if not legacy_id or not content:
            continue
        with _db() as conn:
            exists = conn.execute("SELECT 1 FROM prompt_blocks WHERE legacy_source_id=?", (legacy_id,)).fetchone()
        if exists:
            continue
        save_prompt_block({
            "name": str(item.get("name") or item.get("title") or "历史风格")[:120],
            "module_type": "style",
            "content": content,
            "tags": item.get("tags") or [],
            "applicable_types": [],
            "source": "legacy_style_presets",
            "legacy_source_id": legacy_id,
            "created_at": int(item.get("created_at") or _now()),
        })
        imported_blocks += 1
    return imported_blocks
