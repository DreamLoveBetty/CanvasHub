"""Shared filesystem paths for generated image archives."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
import json
import re

from .app_config import get_storage_config

_STORAGE_CONFIG = get_storage_config()
IMAGE_ARCHIVE_DIR = _STORAGE_CONFIG["image_archive_dir"].expanduser()
SOURCE_IMAGE_DIR = _STORAGE_CONFIG["source_image_dir"].expanduser()
LEGACY_DOWNLOADS_DIR = Path.home() / "Downloads"
LEGACY_OBSIDIAN_ARCHIVE_DIR = Path.home() / "Documents" / "Obsidian Vault" / "GPT Images" / "Mini-app"
LEGACY_OBSIDIAN_SOURCE_IMAGE_DIR = Path.home() / "Documents" / "Obsidian Vault" / "Source_Image"


def _existing_unique_roots(*paths: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = Path(path).expanduser()
        try:
            key = str(expanded.resolve())
        except Exception:
            key = str(expanded)
        if key in seen or not expanded.exists():
            continue
        seen.add(key)
        roots.append(expanded)
    return roots


def daily_output_dir(now: datetime | None = None) -> Path:
    """Return the archive date folder for new generated images."""
    date_part = now.strftime("%Y-%m-%d") if now else time.strftime("%Y-%m-%d")
    return IMAGE_ARCHIVE_DIR / date_part


def image_lookup_roots() -> Iterable[Path]:
    """Roots searched for existing original images, newest archive first."""
    yield from _existing_unique_roots(
        IMAGE_ARCHIVE_DIR,
        LEGACY_OBSIDIAN_ARCHIVE_DIR,
        LEGACY_DOWNLOADS_DIR,
    )


def archive_scan_roots() -> list[tuple[str, Path]]:
    """Image archive roots scanned by the gallery index.

    The first root is the configured write target. Extra roots are read-only
    compatibility locations for this maintainer's pre-publication data.
    """
    roots: list[tuple[str, Path]] = []
    for key, path in (
        ("main", IMAGE_ARCHIVE_DIR),
        ("legacy_obsidian", LEGACY_OBSIDIAN_ARCHIVE_DIR),
    ):
        if not path.exists():
            continue
        try:
            resolved = str(path.expanduser().resolve())
        except Exception:
            resolved = str(path.expanduser())
        if any(existing_resolved == resolved for _, _, existing_resolved in roots):
            continue
        roots.append((key, path.expanduser(), resolved))
    return [(key, path) for key, path, _ in roots]


def source_image_roots() -> list[tuple[str, Path]]:
    """Source-image roots used to read localized remote prompt images."""
    roots: list[tuple[str, Path]] = []
    for key, path in (
        ("main", SOURCE_IMAGE_DIR),
        ("legacy_obsidian", LEGACY_OBSIDIAN_SOURCE_IMAGE_DIR),
    ):
        if not path.exists():
            continue
        try:
            resolved = str(path.expanduser().resolve())
        except Exception:
            resolved = str(path.expanduser())
        if any(existing_resolved == resolved for _, _, existing_resolved in roots):
            continue
        roots.append((key, path.expanduser(), resolved))
    return [(key, path) for key, path, _ in roots]


def _yaml_string(value: object) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _markdown_fence_for(text: str) -> str:
    longest = 0
    for match in re.finditer(r"`+", text):
        longest = max(longest, len(match.group(0)))
    return "`" * max(3, longest + 1)


def _generated_date_from_path(path: Path) -> str:
    for parent in [path.parent, *path.parents]:
        name = parent.name
        if re.match(r"^\d{4}-\d{2}-\d{2}$", name):
            return name
    return ""


def write_obsidian_prompt_sidecar(
    image_path: Path,
    prompt_text: str,
    *,
    txt_path: Path | None = None,
) -> Path:
    """Write an Obsidian-readable markdown prompt sidecar next to an image."""
    image_path = Path(image_path)
    txt_path = Path(txt_path) if txt_path else image_path.with_suffix(".txt")
    prompt_text = str(prompt_text or "").strip()
    md_path = image_path.with_suffix(".md")
    fence = _markdown_fence_for(prompt_text)
    lines = [
        "---",
        "source: tg-mini-app-img-gen",
        "type: image_prompt",
        f"generated_date: {_yaml_string(_generated_date_from_path(image_path))}",
        f"task_id: {_yaml_string(image_path.stem)}",
        f"image: {_yaml_string(image_path.name)}",
        f"txt_file: {_yaml_string(txt_path.name)}",
        "---",
        "",
        f"![[{image_path.name}]]",
        "",
        "## Prompt",
        "",
        f"{fence}text",
        prompt_text,
        fence,
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
