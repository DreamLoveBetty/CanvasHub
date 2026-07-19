#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQLite-backed reusable prompt blocks and type templates."""

from __future__ import annotations

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
SCHEMA_VERSION = 3
TAG_SPLIT_RE = re.compile(r"[,，;；\n]+")
RULE_MODULE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
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
