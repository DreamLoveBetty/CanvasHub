#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Independent remote prompt-source sync for the desktop gallery workspace."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image

from .app_config import APP_DATA_DIR
from .storage_paths import SOURCE_IMAGE_DIR, source_image_roots
from .thumb_cache import thumb_url_for_media_url


DB_PATH = APP_DATA_DIR / "prompt_sources.db"
SETTINGS_PATH = APP_DATA_DIR / "settings.json"
HTTP_TIMEOUT = 30
DB_TIMEOUT = 30
MAX_IMAGE_BYTES = 35 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_RUN_CANCEL_EVENTS: dict[str, threading.Event] = {}
_RUN_CANCEL_LOCK = threading.Lock()


class PromptSourceSyncCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class PromptSourceSpec:
    slug: str
    name: str
    folder: str
    repo_url: str
    raw_base: str
    parser: Callable[["PromptSourceSpec"], list[dict[str, Any]]]


def init_prompt_source_store() -> None:
    SOURCE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_source_items (
                item_id TEXT PRIMARY KEY,
                source_slug TEXT NOT NULL,
                title TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                tags_json TEXT DEFAULT '[]',
                repo_url TEXT DEFAULT '',
                source_url TEXT DEFAULT '',
                local_dir TEXT DEFAULT '',
                image_paths_json TEXT DEFAULT '[]',
                cover_path TEXT DEFAULT '',
                upstream_key TEXT DEFAULT '',
                prompt_hash TEXT DEFAULT '',
                stale INTEGER DEFAULT 0,
                created_at INTEGER,
                updated_at INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_source_items_source ON prompt_source_items(source_slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_source_items_updated ON prompt_source_items(updated_at)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prompt_source_runs (
                run_id TEXT PRIMARY KEY,
                source_slug TEXT DEFAULT '',
                status TEXT DEFAULT 'running',
                started_at INTEGER,
                finished_at INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                item_count INTEGER DEFAULT 0,
                image_count INTEGER DEFAULT 0,
                error_count INTEGER DEFAULT 0,
                phase TEXT DEFAULT '',
                current_source TEXT DEFAULT '',
                current_source_name TEXT DEFAULT '',
                source_index INTEGER DEFAULT 0,
                total_sources INTEGER DEFAULT 0,
                processed_items INTEGER DEFAULT 0,
                total_items INTEGER DEFAULT 0,
                processed_images INTEGER DEFAULT 0,
                total_images INTEGER DEFAULT 0,
                progress_percent INTEGER DEFAULT 0
            )
            """
        )
        for column, definition in {
            "phase": "TEXT DEFAULT ''",
            "current_source": "TEXT DEFAULT ''",
            "current_source_name": "TEXT DEFAULT ''",
            "source_index": "INTEGER DEFAULT 0",
            "total_sources": "INTEGER DEFAULT 0",
            "processed_items": "INTEGER DEFAULT 0",
            "total_items": "INTEGER DEFAULT 0",
            "processed_images": "INTEGER DEFAULT 0",
            "total_images": "INTEGER DEFAULT 0",
            "progress_percent": "INTEGER DEFAULT 0",
        }.items():
            _ensure_column(conn, "prompt_source_runs", column, definition)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prompt_source_runs_started ON prompt_source_runs(started_at)")
        conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
    conn.execute(f"PRAGMA busy_timeout={DB_TIMEOUT * 1000}")
    return conn


@contextmanager
def _db() -> sqlite3.Connection:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _cancel_orphan_running_runs(conn: sqlite3.Connection) -> None:
    with _RUN_CANCEL_LOCK:
        active_ids = set(_RUN_CANCEL_EVENTS.keys())
    rows = conn.execute("SELECT run_id FROM prompt_source_runs WHERE status='running'").fetchall()
    stale_ids = [str(row[0] or "") for row in rows if str(row[0] or "") not in active_ids]
    if not stale_ids:
        return
    now = _now()
    for run_id in stale_ids:
        conn.execute(
            """
            UPDATE prompt_source_runs
            SET status='canceled', finished_at=?, phase='已停止', message=?
            WHERE run_id=? AND status='running'
            """,
            (now, "同步进程已结束，自动标记停止", run_id),
        )


def cancel_orphan_prompt_source_runs() -> int:
    init_prompt_source_store()
    with _db() as conn:
        before = conn.total_changes
        _cancel_orphan_running_runs(conn)
        return conn.total_changes - before


def _now() -> int:
    return int(time.time())


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _settings_value(*keys: str) -> Any:
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        return None
    for key in keys:
        value: Any = settings
        ok = True
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value.get(part)
            else:
                ok = False
                break
        if ok:
            return value
    return None


def _prompt_source_proxy_config() -> dict[str, Any]:
    url = (
        os.environ.get("PROMPT_SOURCE_PROXY_URL")
        or str(_settings_value(
            "prompt_source_proxy_url",
            "promptSourceProxyUrl",
            "prompt_source.proxy_url",
            "promptSource.proxyUrl",
        ) or "")
    ).strip()
    enabled_raw = os.environ.get("PROMPT_SOURCE_PROXY_ENABLED")
    if enabled_raw is None:
        enabled_raw = _settings_value(
            "prompt_source_proxy_enabled",
            "promptSourceProxyEnabled",
            "prompt_source.proxy_enabled",
            "promptSource.proxyEnabled",
        )
    enabled = bool(url) if enabled_raw is None else _truthy(enabled_raw)
    return {"enabled": enabled, "url": url}


def _prompt_source_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    proxy = _prompt_source_proxy_config()
    if proxy.get("enabled") and proxy.get("url"):
        session.proxies = {"http": proxy["url"], "https": proxy["url"]}
    return session


def _register_cancel_event(run_id: str) -> threading.Event:
    event = threading.Event()
    with _RUN_CANCEL_LOCK:
        _RUN_CANCEL_EVENTS[run_id] = event
    return event


def _get_cancel_event(run_id: str) -> threading.Event | None:
    with _RUN_CANCEL_LOCK:
        return _RUN_CANCEL_EVENTS.get(run_id)


def _clear_cancel_event(run_id: str) -> None:
    with _RUN_CANCEL_LOCK:
        _RUN_CANCEL_EVENTS.pop(run_id, None)


def _check_cancel(run_id: str = "") -> None:
    event = _get_cancel_event(run_id) if run_id else None
    if event and event.is_set():
        raise PromptSourceSyncCancelled("用户已停止同步")


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,，;；\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = []
    result: list[str] = []
    seen: set[str] = set()
    for item in parts:
        tag = str(item or "").strip().lstrip("#")[:32]
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(tag)
    return result[:16]


def _sha1(value: str, size: int = 16) -> str:
    return hashlib.sha1(value.encode("utf-8", errors="ignore")).hexdigest()[:size]


def _safe_name(value: str, fallback: str = "item") -> str:
    clean = re.sub(r"[\\/:*?\"<>|\r\n]+", " ", str(value or "")).strip()
    clean = re.sub(r"\s+", " ", clean)[:72].strip(" .")
    return clean or fallback


def _fetch_text(base_url: str, file: str) -> str:
    session = _prompt_source_session()
    try:
        response = session.get(f"{base_url.rstrip('/')}/{file.lstrip('/')}", timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text
    finally:
        session.close()


def _absolute_url(base_url: str, url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):
        return raw
    return f"{base_url.rstrip('/')}/{raw.lstrip('./')}"


def _is_prompt_example_image(url: str) -> bool:
    parsed = urllib.parse.urlparse(str(url or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in {"img.shields.io", "shields.io", "api.star-history.com"}:
        return False
    if path.endswith(".svg") or "badge" in path:
        return False
    return True


def _split_before_heading(markdown: str, prefix: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if line.startswith(prefix) and current:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _first(value: str, pattern: str, dotall: bool = False) -> str:
    flags = re.M | (re.S if dotall else 0)
    match = re.search(pattern, value, flags)
    return match.group(1).strip() if match else ""


def _markdown_images(base_url: str, block: str) -> list[str]:
    seen: set[str] = set()
    images: list[str] = []
    for pattern in (r'<img[^>]+src="([^"]+)"', r"!\[[^\]]*]\(([^)]+)\)"):
        for match in re.findall(pattern, block, re.S):
            image = _absolute_url(base_url, match)
            if image and _is_prompt_example_image(image) and image not in seen:
                seen.add(image)
                images.append(image)
    return images


def _tags_from_heading(value: str) -> list[str]:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff/&、与 ]", "", str(value or ""))
    return _tags(re.split(r"\s*(?:/|&|、|与)\s*", cleaned))


PROMPT_TAXONOMY_RULES: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "style": [
        ("写实摄影", ("摄影", "照片级", "写实", "photography", "photo", "photorealistic", "realistic")),
        ("插画动漫", ("插画", "动漫", "漫画", "illustration", "anime", "manga", "cartoon")),
        ("3D渲染", ("3d", "渲染", "render", "blender", "c4d")),
        ("平面设计", ("平面", "字体", "排版", "typography", "graphic design", "logo")),
        ("电影质感", ("电影", "影视", "镜头", "cinematic", "film", "movie")),
        ("古风复古", ("古风", "历史", "武侠", "复古", "ancient", "retro", "vintage", "wuxia", "history")),
        ("极简高级", ("极简", "简约", "minimal", "minimalist", "clean")),
    ],
    "subject": [
        ("人物角色", ("人像", "头像", "角色", "肖像", "个人资料", "portrait", "character", "avatar", "headshot", "face")),
        ("产品商品", ("产品", "商品", "电商", "product", "ecommerce", "e-commerce")),
        ("UI界面", ("ui", "ux", "界面", "interface", "app", "web")),
        ("建筑空间", ("建筑", "空间", "室内", "architecture", "interior", "room")),
        ("食物饮品", ("食物", "食品", "饮品", "美食", "food", "drink")),
        ("自然风景", ("风景", "自然", "户外", "landscape", "nature", "outdoor")),
        ("品牌文字", ("品牌", "标志", "文字", "logo", "brand", "text render", "typography")),
    ],
    "type": [
        ("海报广告", ("海报", "广告", "poster", "ad creative", "advertising")),
        ("社媒封面", ("社交媒体", "帖子", "缩略图", "social media", "social poster", "thumbnail", "youtube")),
        ("电商展示", ("电商主图", "产品营销", "产品展示", "e-commerce", "ecommerce", "product poster")),
        ("头像资料", ("头像", "个人资料", "profile", "avatar", "headshot")),
        ("信息图文档", ("信息图", "文档", "教育", "infographic", "document", "education")),
        ("游戏素材", ("游戏", "素材", "game", "game_ui", "game scifi")),
        ("故事板漫画", ("故事板", "漫画", "storyboard", "comic")),
        ("编辑转换", ("图像编辑", "风格迁移", "一致性", "edit", "editing", "transform", "consistency")),
        ("视频动画", ("视频", "动画", "短视频", "video", "animation", "short_video")),
        ("对比参考", ("对比", "比较", "comparison", "community examples")),
    ],
}


def _prompt_taxonomy(title: str, prompt: str, tags: list[str], source_name: str = "") -> dict[str, list[str]]:
    metadata_haystack = " ".join([title, source_name, *tags]).lower()
    prompt_haystack = " ".join([metadata_haystack, prompt]).lower()
    result: dict[str, list[str]] = {}
    for group, rules in PROMPT_TAXONOMY_RULES.items():
        haystack = prompt_haystack if group == "style" else metadata_haystack
        matched: list[str] = []
        for label, keywords in rules:
            if any(keyword.lower() in haystack for keyword in keywords):
                matched.append(label)
        result[group] = matched[:3]
    return result


def _taxonomy_facets(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    facets: dict[str, list[dict[str, Any]]] = {}
    for group, rules in PROMPT_TAXONOMY_RULES.items():
        order = {label: index for index, (label, _) in enumerate(rules)}
        counts: dict[str, int] = {}
        for item in items:
            for label in set((item.get("taxonomy") or {}).get(group) or []):
                counts[label] = counts.get(label, 0) + 1
        facets[group] = [
            {"value": label, "label": label, "count": count}
            for label, count in sorted(counts.items(), key=lambda pair: (order.get(pair[0], 999), pair[0]))
        ]
    return facets


def _repo_blob_url(spec: PromptSourceSpec, file: str = "README.md") -> str:
    return f"{spec.repo_url.rstrip('/')}/blob/main/{file.lstrip('/')}"


def parse_gpt_image_2_cases(spec: PromptSourceSpec) -> list[dict[str, Any]]:
    raw = _fetch_text(spec.raw_base, "data/ingested_tweets.json")
    data = json.loads(raw)
    cases: dict[str, str] = {}
    files = [
        "README.md",
        "cases/ad-creative.md",
        "cases/character.md",
        "cases/comparison.md",
        "cases/ecommerce.md",
        "cases/portrait.md",
        "cases/poster.md",
        "cases/ui.md",
    ]
    for file in files:
        markdown = _fetch_text(spec.raw_base, file)
        for match in re.findall(r"(?s)### Case \d+: \[[^\]]+]\(([^)]+)\).*?\*\*Prompt:\*\*\s*\r?\n\s*```[\w-]*\r?\n(.*?)\r?\n```", markdown):
            cases[match[0]] = match[1].strip()

    items: list[dict[str, Any]] = []
    for record in data.get("records") or []:
        tweet_url = str(record.get("tweet_url") or "")
        prompt = cases.get(tweet_url, "")
        image_dir = str(record.get("image_dir") or "")
        if not prompt or not image_dir:
            continue
        items.append({
            "title": record.get("title") or "GPT Image 2 Case",
            "prompt": prompt,
            "tags": _tags(re.sub(r"(?i)\s+Cases$", "", str(record.get("category") or "")).split("&")),
            "source_url": tweet_url or spec.repo_url,
            "images": [f"{spec.raw_base}/{image_dir.strip('/')}/output.jpg"],
            "upstream_key": tweet_url or image_dir,
        })
    return items


def parse_awesome_gpt_image(spec: PromptSourceSpec) -> list[dict[str, Any]]:
    markdown = _fetch_text(spec.raw_base, "README.zh-CN.md")
    items: list[dict[str, Any]] = []
    for section in _split_before_heading(markdown, "## "):
        tags = _tags_from_heading(_first(section, r"^##\s+(.+)$"))
        for block in _split_before_heading(section, "### "):
            heading = _first(block, r"^###\s+(.+)$")
            title = re.sub(r"\[([^\]]+)]\([^)]+\)", r"\1", heading).strip()
            prompt = _first(block, r"\*\*提示词:\*\*\s*\r?\n\s*```[\w-]*\r?\n(.*?)\r?\n```", dotall=True)
            if not title or not prompt:
                continue
            items.append({
                "title": title,
                "prompt": prompt,
                "tags": tags,
                "source_url": _repo_blob_url(spec, "README.zh-CN.md"),
                "images": _markdown_images(spec.raw_base, block),
                "upstream_key": title,
            })
    return items


def parse_awesome_gpt4o_image(spec: PromptSourceSpec) -> list[dict[str, Any]]:
    markdown = _fetch_text(spec.raw_base, "README.zh-CN.md")
    items: list[dict[str, Any]] = []
    for block in _split_before_heading(markdown, "### "):
        title = _first(block, r"^###\s+(.+)$")
        prompt = _first(block, r"- \*\*提示词文本：\*\*\s*`(.*?)`", dotall=True)
        if not title or not prompt:
            continue
        items.append({
            "title": title,
            "prompt": prompt,
            "tags": ["gpt4o"],
            "source_url": _repo_blob_url(spec, "README.zh-CN.md"),
            "images": _markdown_images(spec.raw_base, block),
            "upstream_key": title,
        })
    return items


def parse_youmind(spec: PromptSourceSpec) -> list[dict[str, Any]]:
    markdown = _fetch_text(spec.raw_base, "README_zh.md")
    model_tag = "nano-banana-pro" if "banana" in spec.slug else "gpt-image-2"
    items: list[dict[str, Any]] = []
    for block in _split_before_heading(markdown, "### "):
        title = _first(block, r"^###\s+No\.\s*\d+:\s*(.+)$")
        prompt = _first(block, r"#### .*?提示词\s*\r?\n\s*```[\w-]*\r?\n(.*?)\r?\n```", dotall=True)
        if not title or not prompt:
            continue
        tags = [model_tag]
        if " - " in title:
            tags.extend(_tags_from_heading(title.split(" - ", 1)[0]))
        items.append({
            "title": title,
            "prompt": prompt,
            "tags": tags,
            "source_url": _repo_blob_url(spec, "README_zh.md"),
            "images": _markdown_images(spec.raw_base, block),
            "upstream_key": title,
        })
    return items


def parse_davidwu_gpt_image2(spec: PromptSourceSpec) -> list[dict[str, Any]]:
    raw = _fetch_text(spec.raw_base, "prompts.json")
    data = json.loads(raw)
    items: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return items
    for record in data:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title_cn") or record.get("title_en") or "").strip()
        prompt = str(record.get("prompt") or "").strip()
        image = _absolute_url(spec.raw_base, str(record.get("image") or ""))
        if not title or not prompt or not image:
            continue
        tags = _tags([
            record.get("category_cn"),
            record.get("category"),
            "需要参考图" if record.get("needs_ref") else "",
        ])
        items.append({
            "title": title,
            "prompt": prompt,
            "tags": tags,
            "source_url": spec.repo_url,
            "images": [image],
            "upstream_key": str(record.get("id") or title),
        })
    return items


SOURCES: list[PromptSourceSpec] = [
    PromptSourceSpec(
        slug="gpt-image-2",
        name="GPT Image 2",
        folder="GPT Image 2",
        repo_url="https://github.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts",
        raw_base="https://raw.githubusercontent.com/EvoLinkAI/awesome-gpt-image-2-API-and-Prompts/main",
        parser=parse_gpt_image_2_cases,
    ),
    PromptSourceSpec(
        slug="awesome-gpt-image",
        name="Awesome GPT Image",
        folder="Awesome GPT Image",
        repo_url="https://github.com/ZeroLu/awesome-gpt-image",
        raw_base="https://raw.githubusercontent.com/ZeroLu/awesome-gpt-image/main",
        parser=parse_awesome_gpt_image,
    ),
    PromptSourceSpec(
        slug="gpt-4o-image",
        name="GPT-4o Image",
        folder="GPT-4o Image",
        repo_url="https://github.com/ImgEdify/Awesome-GPT4o-Image-Prompts",
        raw_base="https://raw.githubusercontent.com/ImgEdify/Awesome-GPT4o-Image-Prompts/main",
        parser=parse_awesome_gpt4o_image,
    ),
    PromptSourceSpec(
        slug="youmind-gpt-image-2",
        name="YouMind GPT Image 2",
        folder="YouMind GPT Image 2",
        repo_url="https://github.com/YouMind-OpenLab/awesome-gpt-image-2",
        raw_base="https://raw.githubusercontent.com/YouMind-OpenLab/awesome-gpt-image-2/main",
        parser=parse_youmind,
    ),
    PromptSourceSpec(
        slug="youmind-nano-banana-pro",
        name="YouMind Nano Banana Pro",
        folder="YouMind Nano Banana Pro",
        repo_url="https://github.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts",
        raw_base="https://raw.githubusercontent.com/YouMind-OpenLab/awesome-nano-banana-pro-prompts/main",
        parser=parse_youmind,
    ),
    PromptSourceSpec(
        slug="davidwu-gpt-image2-prompts",
        name="DavidWu GPT Image2 Prompts",
        folder="DavidWu GPT Image2 Prompts",
        repo_url="https://github.com/davidwuw0811-boop/awesome-gpt-image2-prompts",
        raw_base="https://raw.githubusercontent.com/davidwuw0811-boop/awesome-gpt-image2-prompts/main",
        parser=parse_davidwu_gpt_image2,
    ),
]
SOURCE_BY_SLUG = {source.slug: source for source in SOURCES}


def _image_meta(path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "fileSizeBytes": path.stat().st_size if path.exists() else 0,
        "format": path.suffix.lower().lstrip(".").upper(),
    }
    try:
        with Image.open(path) as img:
            width, height = img.size
            img_format = (img.format or meta["format"]).upper()
        meta.update({
            "width": int(width),
            "height": int(height),
            "imageWidth": int(width),
            "imageHeight": int(height),
            "dimensions": f"{int(width)} × {int(height)}",
            "format": "JPG" if img_format == "JPEG" else img_format,
            "orientation": "square" if abs(width - height) / max(width, height) <= 0.02 else ("landscape" if width > height else "portrait"),
            "megapixels": round((int(width) * int(height)) / 1_000_000, 2),
        })
    except Exception:
        pass
    return meta


def _download_image(url: str, target_base: Path, run_id: str = "") -> tuple[Path | None, str, str]:
    _check_cancel(run_id)
    for existing in sorted(target_base.parent.glob(f"{target_base.name}.*")):
        if existing.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        existing_sha = existing.with_suffix(existing.suffix + ".sha256")
        if existing.exists() and existing_sha.exists():
            return existing, existing_sha.read_text(encoding="utf-8").strip(), ""
    parsed_ext = Path(urllib.parse.urlparse(url).path).suffix.lower()
    ext = parsed_ext if parsed_ext in IMAGE_EXTENSIONS else ".jpg"
    target = target_base.with_suffix(ext)
    sha_path = target.with_suffix(target.suffix + ".sha256")
    if target.exists() and sha_path.exists():
        return target, sha_path.read_text(encoding="utf-8").strip(), ""

    session = _prompt_source_session()
    try:
        response = session.get(url, timeout=HTTP_TIMEOUT, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"
        elif "jpeg" in content_type or "jpg" in content_type:
            ext = ".jpg"
        target = target_base.with_suffix(ext)
        sha_path = target.with_suffix(target.suffix + ".sha256")
        tmp = target.with_suffix(target.suffix + ".tmp")
        digest = hashlib.sha256()
        total = 0
        with open(tmp, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                _check_cancel(run_id)
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    tmp.unlink(missing_ok=True)
                    return None, "", "图片超过大小限制"
                digest.update(chunk)
                f.write(chunk)
    finally:
        session.close()
    try:
        with Image.open(tmp) as img:
            img.verify()
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return None, "", f"图片校验失败：{exc}"
    tmp.replace(target)
    sha = digest.hexdigest()
    sha_path.write_text(sha, encoding="utf-8")
    return target, sha, ""


def _write_sidecars(item_dir: Path, item: dict[str, Any], image_path: Path | None, image_url: str, image_sha: str) -> None:
    prompt = str(item.get("prompt") or "").strip()
    source_payload = {
        "source_slug": item.get("source_slug"),
        "title": item.get("title"),
        "prompt": prompt,
        "tags": item.get("tags") or [],
        "repo_url": item.get("repo_url"),
        "source_url": item.get("source_url"),
        "source_image_url": image_url,
        "image_sha256": image_sha,
        "synced_at": _now(),
    }
    (item_dir / "source.json").write_text(json.dumps(source_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (item_dir / "prompt.md").write_text(prompt + "\n", encoding="utf-8")
    if image_path:
        txt = [
            f"source_kind: remote_prompt",
            f"prompt_source: {item.get('source_slug') or ''}",
            f"prompt_item_id: {item.get('item_id') or ''}",
            f"source_repo: {item.get('repo_url') or ''}",
            f"source_url: {item.get('source_url') or ''}",
            f"source_image_url: {image_url}",
            f"image_sha256: {image_sha}",
            f"imported_at: {_now()}",
            "",
            "[user_prompt]",
            prompt,
            "",
        ]
        image_path.with_suffix(".txt").write_text("\n".join(txt), encoding="utf-8")


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    source = SOURCE_BY_SLUG.get(item.get("source_slug") or "")
    image_paths = [str(path) for path in _json_list(item.get("image_paths_json")) if str(path or "").strip()]
    cover_path = str(item.get("cover_path") or (image_paths[0] if image_paths else ""))
    tags = _tags(_json_list(item.get("tags_json")) or item.get("tags_json"))
    taxonomy = _prompt_taxonomy(
        str(item.get("title") or ""),
        str(item.get("prompt") or ""),
        tags,
        source.name if source else str(item.get("source_slug") or ""),
    )
    image_url = source_image_url(cover_path) if cover_path else ""
    asset = {
        "id": item.get("item_id"),
        "asset_id": item.get("item_id"),
        "itemId": item.get("item_id"),
        "sourceSlug": item.get("source_slug"),
        "sourceName": source.name if source else item.get("source_slug"),
        "title": item.get("title") or "远程提示词",
        "prompt": item.get("prompt") or "",
        "tags": tags,
        "taxonomy": taxonomy,
        "promptTaxonomy": taxonomy,
        "repoUrl": item.get("repo_url") or (source.repo_url if source else ""),
        "sourceUrl": item.get("source_url") or "",
        "localDir": item.get("local_dir") or "",
        "imagePaths": image_paths,
        "coverPath": cover_path,
        "imageUrl": image_url,
        "imagePath": image_url,
        "thumbUrl": thumb_url_for_media_url(image_url) if image_url else "",
        "file": Path(cover_path).name if cover_path else "",
        "provider": "remote",
        "providerLabel": source.name if source else "远程源",
        "sourceKind": "remote_source",
        "hasTaskRecord": False,
        "createdAt": item.get("created_at") or 0,
        "updatedAt": item.get("updated_at") or 0,
        "params": {
            "source_kind": "remote_prompt",
            "prompt_source": item.get("source_slug") or "",
            "source_repo": item.get("repo_url") or "",
            "source_url": item.get("source_url") or "",
        },
        "favorite": False,
        "hidden": False,
        "stale": bool(item.get("stale")),
    }
    if cover_path:
        local_path = SOURCE_IMAGE_DIR / cover_path
        if local_path.exists():
            asset.update(_image_meta(local_path))
    return asset


def source_image_url(rel_path: str) -> str:
    return f"/source_image/{urllib.parse.quote(str(rel_path or '').replace('\\', '/'), safe='/')}"


def resolve_source_image(rel_path: str) -> Path | None:
    clean = urllib.parse.unquote(str(rel_path or "")).replace("\\", "/").lstrip("/")
    if not clean:
        return None
    parts = clean.split("/", 1)
    requested_key = parts[0] if len(parts) == 2 else ""
    requested_rel = parts[1] if len(parts) == 2 else clean
    for root_key, root_path in source_image_roots():
        candidate_rel = requested_rel if requested_key == root_key else clean
        candidate = (root_path / candidate_rel).resolve()
        root = root_path.resolve()
        try:
            candidate.relative_to(root)
        except Exception:
            continue
        if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS:
            return candidate
    return None


def list_prompt_sources() -> dict[str, Any]:
    init_prompt_source_store()
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        counts = {
            row["source_slug"]: row
            for row in conn.execute(
                """
                SELECT source_slug, COUNT(*) AS item_count,
                       SUM(CASE WHEN stale = 0 THEN 1 ELSE 0 END) AS active_item_count,
                       SUM(CASE WHEN stale != 0 THEN 1 ELSE 0 END) AS stale_item_count,
                       SUM(json_array_length(COALESCE(NULLIF(image_paths_json, ''), '[]'))) AS image_count,
                       MAX(updated_at) AS updated_at
                FROM prompt_source_items
                GROUP BY source_slug
                """
            ).fetchall()
        }
        run_rows = conn.execute("SELECT * FROM prompt_source_runs ORDER BY started_at DESC").fetchall()
        runs: dict[str, sqlite3.Row] = {}
        for run_row in run_rows:
            slug = str(run_row["source_slug"] or "")
            if slug and slug not in runs:
                runs[slug] = run_row
        latest_run = dict(run_rows[0]) if run_rows else None
    sources = []
    for source in SOURCES:
        row = counts.get(source.slug)
        run = runs.get(source.slug)
        sources.append({
            "slug": source.slug,
            "name": source.name,
            "folder": source.folder,
            "repoUrl": source.repo_url,
            "localPath": str(SOURCE_IMAGE_DIR / source.folder),
            "itemCount": int(row["item_count"] if row else 0),
            "activeItemCount": int(row["active_item_count"] if row and row["active_item_count"] is not None else 0),
            "staleItemCount": int(row["stale_item_count"] if row and row["stale_item_count"] is not None else 0),
            "imageCount": int(row["image_count"] if row and row["image_count"] is not None else 0),
            "updatedAt": int(row["updated_at"] if row and row["updated_at"] else 0),
            "lastRun": dict(run) if run else None,
        })
    roots = [{"key": key, "path": str(path)} for key, path in source_image_roots()]
    return {
        "sources": sources,
        "root": str(SOURCE_IMAGE_DIR),
        "roots": roots,
        "compatRoots": [item for item in roots if item["key"] != "main"],
        "latestRun": latest_run,
    }


def list_prompt_source_items(
    source_slug: str = "",
    query: str = "",
    tag: str = "",
    style: str = "",
    subject: str = "",
    item_type: str = "",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    init_prompt_source_store()
    safe_limit = max(1, min(int(limit or 200), 1000))
    safe_offset = max(0, int(offset or 0))
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM prompt_source_items ORDER BY stale ASC, updated_at DESC").fetchall()
    items = [_row_to_item(row) for row in rows]
    source_filter = str(source_slug or "").strip()
    query_filter = str(query or "").strip().lower()
    tag_filter = str(tag or "").strip().lstrip("#").lower()
    base_filtered = []
    for item in items:
        if source_filter and item.get("sourceSlug") != source_filter:
            continue
        item_tags = _tags(item.get("tags"))
        if tag_filter and tag_filter not in [tag.lower() for tag in item_tags]:
            continue
        if query_filter:
            haystack = " ".join([
                item.get("title") or "",
                item.get("prompt") or "",
                item.get("sourceName") or "",
                item.get("file") or "",
                " ".join(item_tags),
            ]).lower()
            if query_filter not in haystack:
                continue
        base_filtered.append(item)
    facets = _taxonomy_facets(base_filtered)
    taxonomy_filters = {
        "style": str(style or "").strip(),
        "subject": str(subject or "").strip(),
        "type": str(item_type or "").strip(),
    }
    filtered = []
    for item in base_filtered:
        taxonomy = item.get("taxonomy") or {}
        if any(value and value not in (taxonomy.get(group) or []) for group, value in taxonomy_filters.items()):
            continue
        filtered.append(item)
    known_tags = sorted({tag for item in filtered for tag in _tags(item.get("tags"))}, key=str.lower)
    return {
        "items": filtered[safe_offset:safe_offset + safe_limit],
        "total": len(filtered),
        "limit": safe_limit,
        "offset": safe_offset,
        "tags": known_tags,
        "taxonomyFacets": facets,
        "taxonomyFilters": taxonomy_filters,
    }


def _create_run(source_slug: str) -> str:
    init_prompt_source_store()
    run_id = f"run_{int(time.time())}_{_sha1(source_slug + str(time.time()), 8)}"
    _register_cancel_event(run_id)
    with _db() as conn:
        conn.execute(
            "INSERT INTO prompt_source_runs (run_id, source_slug, status, started_at) VALUES (?, ?, 'running', ?)",
            (run_id, source_slug, _now()),
        )
    return run_id


def stop_prompt_source_sync(run_id: str) -> dict[str, Any]:
    clean = str(run_id or "").strip()
    if not clean:
        raise ValueError("缺少同步任务 ID")
    run = get_prompt_source_run(clean)
    if not run:
        raise ValueError("同步任务不存在")
    if run.get("status") != "running":
        return {"ok": True, "run_id": clean, "status": run.get("status") or "finished"}
    event = _get_cancel_event(clean)
    if not event:
        _finish_run(
            clean,
            "canceled",
            "同步进程不在当前服务中，已标记停止",
            int(run.get("item_count") or 0),
            int(run.get("image_count") or 0),
            int(run.get("error_count") or 0),
        )
        return {"ok": True, "run_id": clean, "status": "canceled"}
    event.set()
    _update_run_progress(clean, phase="停止中", message="正在停止远程源同步")
    return {"ok": True, "run_id": clean, "status": "stopping"}


def _update_run_progress(run_id: str, **updates: Any) -> None:
    if not updates:
        return
    allowed = {
        "phase",
        "current_source",
        "current_source_name",
        "source_index",
        "total_sources",
        "processed_items",
        "total_items",
        "processed_images",
        "total_images",
        "item_count",
        "image_count",
        "error_count",
        "message",
        "progress_percent",
    }
    clean = {key: value for key, value in updates.items() if key in allowed}
    if not clean:
        return
    assignments = ", ".join(f"{key}=?" for key in clean)
    with _db() as conn:
        conn.execute(
            f"UPDATE prompt_source_runs SET {assignments} WHERE run_id=?",
            [*clean.values(), run_id],
        )


def _progress_percent(source_index: int, total_sources: int, processed_items: int, total_items: int, done: bool = False) -> int:
    if done:
        return 100
    total_sources = max(1, int(total_sources or 1))
    source_index = max(1, min(int(source_index or 1), total_sources))
    base = (source_index - 1) / total_sources
    source_fraction = 0.08
    if total_items:
        source_fraction = min(0.98, max(0.08, processed_items / max(1, total_items)))
    return max(1, min(99, round((base + source_fraction / total_sources) * 100)))


def _finish_run(run_id: str, status: str, message: str = "", item_count: int = 0, image_count: int = 0, error_count: int = 0) -> None:
    with _db() as conn:
        conn.execute(
            """
            UPDATE prompt_source_runs
            SET status=?, finished_at=?, message=?, item_count=?, image_count=?, error_count=?,
                phase=?, processed_items=?, total_items=?, processed_images=?, total_images=?, progress_percent=?
            WHERE run_id=?
            """,
            (
                status,
                _now(),
                message[:1000],
                int(item_count),
                int(image_count),
                int(error_count),
                "完成" if status == "succeeded" else ("已停止" if status == "canceled" else "结束"),
                int(item_count),
                int(item_count),
                int(image_count),
                int(image_count),
                100,
                run_id,
            ),
        )


def get_prompt_source_run(run_id: str) -> dict[str, Any] | None:
    init_prompt_source_store()
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM prompt_source_runs WHERE run_id=?", (str(run_id or ""),)).fetchone()
    return dict(row) if row else None


def start_prompt_source_sync(source_slug: str = "all") -> dict[str, Any]:
    clean = str(source_slug or "all").strip() or "all"
    if clean != "all" and clean not in SOURCE_BY_SLUG:
        raise ValueError("未知远程源")
    init_prompt_source_store()
    with _db() as conn:
        conn.row_factory = sqlite3.Row
        running = conn.execute(
            "SELECT * FROM prompt_source_runs WHERE status='running' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    if running:
        running_id = str(running["run_id"] or "")
        if _get_cancel_event(running_id):
            return {"ok": True, "run_id": running_id, "source": running["source_slug"] or clean, "already_running": True}
        _finish_run(
            running_id,
            "canceled",
            "同步进程不在当前服务中，已标记停止",
            int(running["item_count"] or 0),
            int(running["image_count"] or 0),
            int(running["error_count"] or 0),
        )
    run_id = _create_run(clean)
    thread = threading.Thread(target=_sync_run_worker, args=(run_id, clean), daemon=True)
    thread.start()
    return {"ok": True, "run_id": run_id, "source": clean}


def _sync_run_worker(run_id: str, source_slug: str) -> None:
    try:
        sources = SOURCES if source_slug == "all" else [SOURCE_BY_SLUG[source_slug]]
        total_sources = len(sources)
        _check_cancel(run_id)
        _update_run_progress(
            run_id,
            phase="准备同步",
            total_sources=total_sources,
            source_index=0,
            progress_percent=1,
            message="准备拉取远程源",
        )
        item_count = 0
        image_count = 0
        error_count = 0
        messages = []
        for source_index, source in enumerate(sources, start=1):
            try:
                _check_cancel(run_id)
                _update_run_progress(
                    run_id,
                    phase="拉取列表",
                    current_source=source.slug,
                    current_source_name=source.name,
                    source_index=source_index,
                    total_sources=total_sources,
                    processed_items=0,
                    total_items=0,
                    processed_images=0,
                    total_images=0,
                    progress_percent=_progress_percent(source_index, total_sources, 0, 0),
                    message=f"正在解析 {source.name}",
                )
                result = sync_prompt_source(source, run_id=run_id, source_index=source_index, total_sources=total_sources)
                _check_cancel(run_id)
                item_count += result.get("item_count", 0)
                image_count += result.get("image_count", 0)
                error_count += result.get("error_count", 0)
                messages.append(f"{source.name}: {result.get('item_count', 0)} 条 / {result.get('image_count', 0)} 图")
                _update_run_progress(
                    run_id,
                    item_count=item_count,
                    image_count=image_count,
                    error_count=error_count,
                    message="；".join(messages),
                )
            except PromptSourceSyncCancelled:
                raise
            except Exception as exc:
                error_count += 1
                messages.append(f"{source.name}: {exc}")
                _update_run_progress(
                    run_id,
                    phase="来源失败",
                    item_count=item_count,
                    image_count=image_count,
                    error_count=error_count,
                    message="；".join(messages),
                    progress_percent=_progress_percent(source_index, total_sources, 1, 1),
                )
        _finish_run(run_id, "failed" if error_count and not item_count else "succeeded", "；".join(messages), item_count, image_count, error_count)
    except PromptSourceSyncCancelled:
        current = get_prompt_source_run(run_id) or {}
        _finish_run(
            run_id,
            "canceled",
            "用户已停止同步",
            int(current.get("item_count") or 0),
            int(current.get("image_count") or 0),
            int(current.get("error_count") or 0),
        )
    except Exception as exc:
        _finish_run(run_id, "failed", str(exc), 0, 0, 1)
    finally:
        _clear_cancel_event(run_id)


def sync_prompt_source(
    source: PromptSourceSpec,
    run_id: str = "",
    source_index: int = 1,
    total_sources: int = 1,
) -> dict[str, int]:
    init_prompt_source_store()
    _check_cancel(run_id)
    source_dir = SOURCE_IMAGE_DIR / source.folder
    source_dir.mkdir(parents=True, exist_ok=True)
    parsed = source.parser(source)
    _check_cancel(run_id)
    total_items = len(parsed)
    total_images = sum(min(8, len(item.get("images") or [])) for item in parsed if str(item.get("prompt") or "").strip())
    if run_id:
        _update_run_progress(
            run_id,
            phase="下载图片",
            current_source=source.slug,
            current_source_name=source.name,
            source_index=source_index,
            total_sources=total_sources,
            processed_items=0,
            total_items=total_items,
            processed_images=0,
            total_images=total_images,
            progress_percent=_progress_percent(source_index, total_sources, 0, total_items),
            message=f"{source.name}: 发现 {total_items} 条提示词，准备下载图片",
        )
    now = _now()
    item_count = 0
    image_count = 0
    error_count = 0
    active_ids: list[str] = []
    with _db() as conn:
        for raw_index, raw_item in enumerate(parsed, start=1):
            _check_cancel(run_id)
            title = str(raw_item.get("title") or "远程提示词").strip()
            prompt = str(raw_item.get("prompt") or "").strip()
            images = [url for url in raw_item.get("images") or [] if str(url or "").startswith(("http://", "https://"))]
            if run_id:
                _update_run_progress(
                    run_id,
                    phase="下载图片",
                    processed_items=raw_index - 1,
                    total_items=total_items,
                    processed_images=image_count,
                    total_images=total_images,
                    progress_percent=_progress_percent(source_index, total_sources, raw_index - 1, total_items),
                    message=f"{source.name}: 正在处理 {raw_index}/{total_items} · {title[:60]}",
                )
            if not prompt or not images:
                continue
            upstream_key = str(raw_item.get("upstream_key") or raw_item.get("source_url") or title)
            prompt_hash = _sha1(prompt, 20)
            item_id = f"remote_{source.slug}_{_sha1(upstream_key + '|' + prompt_hash, 20)}"
            item_dir = source_dir / f"{item_id}_{_safe_name(title)}"
            item_dir.mkdir(parents=True, exist_ok=True)
            image_paths: list[str] = []
            image_errors = 0
            for index, image_url in enumerate(images[:8], start=1):
                _check_cancel(run_id)
                target_base = item_dir / f"image-{index:02d}"
                try:
                    image_path, image_sha, error = _download_image(image_url, target_base, run_id=run_id)
                    if error:
                        image_errors += 1
                        continue
                    if image_path:
                        rel_path = image_path.relative_to(SOURCE_IMAGE_DIR).as_posix()
                        image_paths.append(rel_path)
                        image_count += 1
                        if run_id:
                            _update_run_progress(
                                run_id,
                                processed_items=raw_index - 1,
                                total_items=total_items,
                                processed_images=image_count,
                                total_images=total_images,
                                image_count=image_count,
                                progress_percent=_progress_percent(source_index, total_sources, raw_index - 1, total_items),
                                message=f"{source.name}: 已下载 {image_count}/{total_images or image_count} 张图片",
                            )
                        raw_item.update({
                            "item_id": item_id,
                            "source_slug": source.slug,
                            "repo_url": source.repo_url,
                        })
                        _write_sidecars(item_dir, raw_item, image_path, image_url, image_sha)
                except PromptSourceSyncCancelled:
                    raise
                except Exception:
                    image_errors += 1
                    continue
            error_count += image_errors
            if not image_paths:
                continue
            tags = _tags(raw_item.get("tags"))
            conn.execute(
                """
                INSERT INTO prompt_source_items (
                    item_id, source_slug, title, prompt, tags_json, repo_url, source_url,
                    local_dir, image_paths_json, cover_path, upstream_key, prompt_hash,
                    stale, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ON CONFLICT(item_id) DO UPDATE SET
                    title=excluded.title,
                    prompt=excluded.prompt,
                    tags_json=excluded.tags_json,
                    repo_url=excluded.repo_url,
                    source_url=excluded.source_url,
                    local_dir=excluded.local_dir,
                    image_paths_json=excluded.image_paths_json,
                    cover_path=excluded.cover_path,
                    upstream_key=excluded.upstream_key,
                    prompt_hash=excluded.prompt_hash,
                    stale=0,
                    updated_at=excluded.updated_at
                """,
                (
                    item_id,
                    source.slug,
                    title[:500],
                    prompt[:20000],
                    json.dumps(tags, ensure_ascii=False),
                    source.repo_url,
                    str(raw_item.get("source_url") or source.repo_url),
                    item_dir.relative_to(SOURCE_IMAGE_DIR).as_posix(),
                    json.dumps(image_paths, ensure_ascii=False),
                    image_paths[0],
                    upstream_key[:1000],
                    prompt_hash,
                    now,
                    now,
                ),
            )
            conn.commit()
            active_ids.append(item_id)
            item_count += 1
            if run_id:
                _update_run_progress(
                    run_id,
                    processed_items=raw_index,
                    total_items=total_items,
                    processed_images=image_count,
                    total_images=total_images,
                    item_count=item_count,
                    image_count=image_count,
                    error_count=error_count,
                    progress_percent=_progress_percent(source_index, total_sources, raw_index, total_items),
                    message=f"{source.name}: 已处理 {raw_index}/{total_items} 条，已保存 {item_count} 条",
                )
        if active_ids:
            placeholders = ",".join("?" for _ in active_ids)
            conn.execute(
                f"UPDATE prompt_source_items SET stale=1 WHERE source_slug=? AND item_id NOT IN ({placeholders})",
                [source.slug, *active_ids],
            )
        conn.commit()
    return {"item_count": item_count, "image_count": image_count, "error_count": error_count}
