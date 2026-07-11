#!/usr/bin/env python3
"""Editable file artifacts for PPT/PSD tasks."""

from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageChops

from .app_config import BASE_DIR
from .storage_paths import IMAGE_ARCHIVE_DIR


EDITABLE_FILE_TYPES = {"ppt", "psd"}
EDITABLE_ROOT = IMAGE_ARCHIVE_DIR.parent
PPT_ROOT = EDITABLE_ROOT / "PPT"
PSD_ROOT = EDITABLE_ROOT / "PSD"
LOCAL_EDITABLE_ROOT = BASE_DIR / "data" / "editable_outputs"


def normalize_editable_type(value: str) -> str:
    kind = str(value or "ppt").strip().lower()
    if kind in {"ppt", "powerpoint", "presentation"}:
        return "ppt"
    if kind in {"psd", "photoshop"}:
        return "psd"
    raise ValueError(f"unsupported editable file type: {value}")


def _slug_text(value: str, fallback: str = "untitled", limit: int = 36) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"[\x00-\x1f/\\:*?\"<>|#]+", "", text)
    text = text.strip(" ._-")
    if not text:
        text = fallback
    return text[:limit].strip(" ._-") or fallback


def infer_subject(prompt: str, explicit: str = "") -> str:
    if explicit:
        return _slug_text(explicit)
    text = re.sub(r"\s+", " ", str(prompt or "").strip())
    text = re.sub(r"^(请|帮我|生成|做|制作|设计|输出|创建|我需要你|我需要)\s*", "", text)
    return _slug_text(text, fallback="untitled", limit=36)


def editable_root(kind: str, archive_enabled: bool = True) -> Path:
    if archive_enabled:
        return PPT_ROOT if normalize_editable_type(kind) == "ppt" else PSD_ROOT
    return LOCAL_EDITABLE_ROOT / normalize_editable_type(kind).upper()


def allocate_task_dir(
    kind: str,
    prompt: str,
    subject: str = "",
    now: datetime | None = None,
    archive_enabled: bool = True,
) -> Path:
    now = now or datetime.now()
    root = editable_root(kind, archive_enabled=archive_enabled)
    root.mkdir(parents=True, exist_ok=True)
    folder_name = f"{now.strftime('%Y-%m-%d')}_{infer_subject(prompt, subject)}"
    candidate = root / folder_name
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    for index in range(2, 1000):
        numbered = root / f"{folder_name}_{index}"
        if not numbered.exists():
            numbered.mkdir(parents=True, exist_ok=True)
            return numbered
    raise RuntimeError(f"failed to allocate editable output dir for {folder_name}")


def _decode_b64(value: str) -> bytes:
    payload = str(value or "").strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(str(value or "").replace("\x00", "")).name.strip()
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|#]+", "_", name)
    return name or fallback


def _relative_path(path: Path) -> str:
    resolved = path.resolve()
    roots = [
        (EDITABLE_ROOT.resolve(), ""),
        (LOCAL_EDITABLE_ROOT.resolve(), "local"),
    ]
    for root, prefix in roots:
        try:
            rel = resolved.relative_to(root).as_posix()
            return f"{prefix}/{rel}" if prefix else rel
        except ValueError:
            continue
    raise ValueError(f"path is outside editable roots: {path}")


def editable_url(path: Path | str) -> str:
    rel = str(path)
    if isinstance(path, Path):
        rel = _relative_path(path)
    return f"/editable_file/{quote(rel, safe='/')}"


def resolve_editable_file(rel_path: str) -> Path | None:
    raw = str(rel_path or "").replace("\\", "/").lstrip("/")
    if not raw:
        return None
    root = EDITABLE_ROOT
    if raw == "local" or raw.startswith("local/"):
        raw = raw.split("/", 1)[1] if "/" in raw else ""
        root = LOCAL_EDITABLE_ROOT
    first_segment = raw.split("/", 1)[0]
    if first_segment not in {"PPT", "PSD"}:
        return None
    candidate = (root / raw).expanduser()
    try:
        resolved = candidate.resolve()
        allowed_root = root.resolve()
    except Exception:
        return None
    if resolved != allowed_root and allowed_root not in resolved.parents:
        return None
    if not resolved.is_file():
        return None
    return resolved


def _resolve_editable_directory(rel_path: str) -> Path | None:
    raw = str(rel_path or "").replace("\\", "/").lstrip("/")
    if not raw:
        return None
    root = EDITABLE_ROOT
    if raw == "local" or raw.startswith("local/"):
        raw = raw.split("/", 1)[1] if "/" in raw else ""
        root = LOCAL_EDITABLE_ROOT
    first_segment = raw.split("/", 1)[0]
    if first_segment not in {"PPT", "PSD"}:
        return None
    candidate = (root / raw).expanduser()
    try:
        resolved = candidate.resolve()
        allowed_root = root.resolve()
    except Exception:
        return None
    if resolved != allowed_root and allowed_root not in resolved.parents:
        return None
    if resolved.is_file():
        resolved = resolved.parent
    if not resolved.is_dir() or not (resolved / "manifest.json").exists():
        return None
    return resolved


def _normalize_manifest_urls(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    data = dict(manifest)
    task_dir = manifest_path.parent
    data["directory"] = str(task_dir)
    data["directory_relative"] = _relative_path(task_dir)
    data["manifest_path"] = str(manifest_path)
    data["manifest_url"] = editable_url(manifest_path)
    data["archived"] = not data["directory_relative"].startswith("local/")
    data["storage"] = "archive" if data["archived"] else "local"

    def normalize_artifact(artifact: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(artifact, dict):
            return None
        item = dict(artifact)
        path = Path(str(item.get("path") or ""))
        if not path.exists() and item.get("name"):
            path = task_dir / str(item.get("name"))
        if path.exists():
            item["path"] = str(path)
            item["relative_path"] = _relative_path(path)
            item["url"] = editable_url(path)
            item["size"] = path.stat().st_size
            item["mime_type"] = item.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return item

    primary = normalize_artifact(data.get("primary"))
    zip_artifact = normalize_artifact(data.get("zip"))
    artifacts = [item for item in [primary, zip_artifact] if item]
    if primary:
        data["primary"] = primary
    if zip_artifact:
        data["zip"] = zip_artifact
    data["artifacts"] = artifacts or data.get("artifacts") or []
    data["result_files"] = [item.get("relative_path") for item in data["artifacts"] if item.get("relative_path")]
    return data


def _find_executable(candidates: list[str]) -> str:
    for item in candidates:
        found = shutil.which(item)
        if found:
            return found
        path = Path(item)
        if path.exists():
            return str(path)
    return ""


def find_libreoffice() -> str:
    return _find_executable(
        [
            "soffice",
            "libreoffice",
            "/opt/homebrew/bin/soffice",
            "/usr/local/bin/soffice",
            "/usr/bin/libreoffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
    )


def _render_pdf_pages(pdf_path: Path, preview_dir: Path) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    try:
        import fitz  # type: ignore

        preview_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(str(pdf_path))
        for index, page in enumerate(doc, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            out = preview_dir / f"page-{index:03d}.png"
            pix.save(str(out))
            pages.append({"index": index, "path": str(out), "url": editable_url(out)})
        doc.close()
    except Exception as exc:
        print(f"⚠️ PPT PDF page preview failed: {exc}")
    return pages


def _build_ppt_preview(primary_path: Path, task_dir: Path) -> dict[str, Any]:
    preview: dict[str, Any] = {"status": "not_available", "pages": []}
    soffice = find_libreoffice()
    if not soffice:
        preview.update({"status": "missing_dependency", "message": "LibreOffice/soffice not found"})
        return preview
    pdf_dir = task_dir / "preview"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(pdf_dir), str(primary_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        pdf_candidates = sorted(pdf_dir.glob(f"{primary_path.stem}*.pdf"))
        pdf_path = pdf_candidates[0] if pdf_candidates else pdf_dir / f"{primary_path.stem}.pdf"
        if not pdf_path.exists():
            raise RuntimeError("LibreOffice did not produce PDF")
        pages = _render_pdf_pages(pdf_path, pdf_dir / "pages")
        preview.update(
            {
                "status": "ready" if pages else "pdf_ready",
                "pdf": str(pdf_path),
                "pdf_url": editable_url(pdf_path),
                "pages": pages,
                "page_count": len(pages),
                "engine": "libreoffice+pdfjs",
            }
        )
    except Exception as exc:
        preview.update({"status": "failed", "message": str(exc)[:500], "engine": "libreoffice"})
    return preview


def _extract_zip_layers(zip_path: Path | None, task_dir: Path) -> list[dict[str, Any]]:
    if not zip_path or not zip_path.exists():
        return []
    layers_dir = task_dir / "layers"
    layers: list[dict[str, Any]] = []
    try:
        layers_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            file_items = [item for item in zf.infolist() if not item.is_dir()]
            has_layers_directory = any(
                Path(item.filename.replace("\\", "/").lstrip("/")).parts[:1] == ("layers",)
                for item in file_items
            )
            for item in file_items:
                if item.is_dir():
                    continue
                normalized_name = item.filename.replace("\\", "/").lstrip("/")
                parts = Path(normalized_name).parts
                if not parts or (has_layers_directory and parts[0] != "layers"):
                    continue
                source_name = Path(normalized_name).name
                if source_name.lower() in {"original_reference.png", "composite_preview.png"}:
                    continue
                suffix = Path(source_name).suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    continue
                name = _safe_filename(source_name, f"layer-{len(layers) + 1:03d}{suffix}")
                target = layers_dir / name
                with zf.open(item) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                layers.append({"name": name, "path": str(target), "url": editable_url(target), "index": len(layers) + 1})
    except Exception as exc:
        print(f"⚠️ PSD zip layer extraction failed: {exc}")
    return layers


def _imagemagick_psd_scene_count(primary_path: Path) -> int:
    magick = _find_executable(["magick", "/opt/homebrew/bin/magick", "/usr/local/bin/magick"])
    if magick:
        command = [magick, "identify", str(primary_path)]
    else:
        identify = _find_executable(["identify", "/opt/homebrew/bin/identify", "/usr/local/bin/identify"])
        command = [identify, str(primary_path)] if identify else []
    if not command:
        raise RuntimeError("ImageMagick is required to validate PSD layers")
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    scenes = [line for line in completed.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"ImageMagick could not read PSD: {detail}")
    return len(scenes)


def validate_psd_artifacts(primary_path: Path, zip_path: Path | None) -> dict[str, Any]:
    if not primary_path.exists() or primary_path.stat().st_size < 1024:
        raise RuntimeError("PSD 文件缺失或体积异常")
    with primary_path.open("rb") as source:
        if source.read(4) != b"8BPS":
            raise RuntimeError("PSD 文件头无效，不是真实 Photoshop 文档")
    scene_count = _imagemagick_psd_scene_count(primary_path)
    if scene_count < 3:
        raise RuntimeError("PSD 至少需要 2 个真实可编辑图层")
    if not zip_path or not zip_path.exists() or not zipfile.is_zipfile(zip_path):
        raise RuntimeError("PSD 图层 ZIP 缺失或无效")

    bad_markers = ("fallback", "placeholder", "automatic extraction unavailable")
    canvas_size: tuple[int, int] | None = None
    layer_names: list[str] = []
    has_transparency = False
    with zipfile.ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/").lstrip("/") for name in archive.namelist()]
        for name in names:
            parts = Path(name).parts
            if (
                len(parts) >= 2
                and parts[0] == "layers"
                and Path(name).suffix.lower() == ".png"
                and Path(name).name.lower() not in {"original_reference.png", "composite_preview.png"}
            ):
                layer_names.append(name)
        layer_names.sort()
        if len(layer_names) < 2:
            raise RuntimeError("PSD 图层 ZIP 中至少需要 2 张 layers/ PNG")
        layer_images: list[Image.Image] = []
        for name in layer_names:
            with archive.open(name) as source:
                image = Image.open(BytesIO(source.read())).convert("RGBA")
                image.load()
            layer_images.append(image)
            if canvas_size is None:
                canvas_size = image.size
            elif image.size != canvas_size:
                raise RuntimeError("PSD 图层 PNG 画布尺寸不一致")
            alpha_min, alpha_max = image.getchannel("A").getextrema()
            has_transparency = has_transparency or alpha_min < 255 or alpha_max < 255
        if not has_transparency:
            raise RuntimeError("PSD 图层 PNG 不含真实透明像素")
        if "composite_preview.png" not in names:
            raise RuntimeError("PSD 图层 ZIP 缺少 composite_preview.png")
        with archive.open("composite_preview.png") as source:
            preview = Image.open(BytesIO(source.read())).convert("RGBA")
            preview.load()
        if canvas_size and preview.size != canvas_size:
            raise RuntimeError("PSD 组合预览尺寸与图层画布不一致")
        reconstructed = Image.new("RGBA", preview.size, (0, 0, 0, 0))
        for layer_image in layer_images:
            reconstructed = Image.alpha_composite(reconstructed, layer_image)
        expected = Image.alpha_composite(Image.new("RGBA", preview.size, (0, 0, 0, 0)), preview)
        if ImageChops.difference(reconstructed, expected).getbbox() is not None:
            raise RuntimeError("PSD 图层叠加后不能精确还原组合预览")
        for name in names:
            if Path(name).suffix.lower() not in {".txt", ".json", ".md"}:
                continue
            text = archive.read(name).decode("utf-8", "replace").lower()
            if any(marker in text for marker in bad_markers):
                raise RuntimeError(f"PSD 图层 ZIP 包含无效占位标记：{name}")
    return {
        "ok": True,
        "psd_scene_count": scene_count,
        "editable_layer_count": max(0, scene_count - 1),
        "zip_layer_count": len(layer_names),
        "canvas_size": list(canvas_size or (0, 0)),
        "has_transparency": has_transparency,
        "reconstruction_exact": True,
    }


def _build_psd_preview(primary_path: Path, zip_path: Path | None, task_dir: Path) -> dict[str, Any]:
    layers = _extract_zip_layers(zip_path, task_dir)
    preview: dict[str, Any] = {
        "status": "ready" if layers else "not_available",
        "layers": layers,
        "layer_count": len(layers),
    }
    magick = _find_executable(["magick", "convert"])
    if magick:
        out = task_dir / "preview.png"
        try:
            cmd = [magick, f"{primary_path}[0]", str(out)] if Path(magick).name == "magick" else [magick, f"{primary_path}[0]", str(out)]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if out.exists():
                preview.update({"status": "ready", "image": str(out), "image_url": editable_url(out), "engine": "imagemagick"})
        except Exception as exc:
            if not layers:
                preview.update({"status": "failed", "message": str(exc)[:500], "engine": "imagemagick"})
    return preview


def save_editable_artifacts(
    *,
    kind: str,
    prompt: str,
    primary: dict[str, Any],
    zip_artifact: dict[str, Any] | None = None,
    task_id: str = "",
    subject: str = "",
    conversation_id: str = "",
    archive_enabled: bool = True,
    strict_psd_validation: bool = False,
) -> dict[str, Any]:
    kind = normalize_editable_type(kind)
    now = datetime.now()
    task_dir = allocate_task_dir(kind, prompt, subject, now, archive_enabled=archive_enabled)
    try:
        stamp = now.strftime("%Y%m%d_%H%M%S")
        topic = infer_subject(prompt, subject)
        primary_suffix = ".pptx" if kind == "ppt" else ".psd"
        primary_name = _safe_filename(str(primary.get("filename") or ""), f"{topic}_{stamp}{primary_suffix}")
        if Path(primary_name).suffix.lower() not in ({".ppt", ".pptx"} if kind == "ppt" else {".psd"}):
            primary_name = f"{Path(primary_name).stem}{primary_suffix}"
        primary_path = task_dir / primary_name
        primary_path.write_bytes(_decode_b64(str(primary.get("b64") or primary.get("base64") or "")))

        zip_path: Path | None = None
        if zip_artifact and (zip_artifact.get("b64") or zip_artifact.get("base64")):
            zip_name = _safe_filename(str(zip_artifact.get("filename") or ""), f"{topic}_{stamp}_source.zip")
            if Path(zip_name).suffix.lower() != ".zip":
                zip_name = f"{Path(zip_name).stem}.zip"
            zip_path = task_dir / zip_name
            zip_path.write_bytes(_decode_b64(str(zip_artifact.get("b64") or zip_artifact.get("base64") or "")))

        validation: dict[str, Any] | None = None
        if kind == "psd" and strict_psd_validation:
            validation = validate_psd_artifacts(primary_path, zip_path)

        prompt_path = task_dir / "prompt.txt"
        prompt_path.write_text(str(prompt or "").strip() + "\n", encoding="utf-8")

        preview = _build_ppt_preview(primary_path, task_dir) if kind == "ppt" else _build_psd_preview(primary_path, zip_path, task_dir)
        artifacts = [
            {
                "role": "primary",
                "name": primary_path.name,
                "path": str(primary_path),
                "relative_path": _relative_path(primary_path),
                "url": editable_url(primary_path),
                "mime_type": mimetypes.guess_type(primary_path.name)[0] or "application/octet-stream",
                "size": primary_path.stat().st_size,
            }
        ]
        if zip_path:
            artifacts.append(
                {
                    "role": "source_zip",
                    "name": zip_path.name,
                    "path": str(zip_path),
                    "relative_path": _relative_path(zip_path),
                    "url": editable_url(zip_path),
                    "mime_type": "application/zip",
                    "size": zip_path.stat().st_size,
                }
            )

        manifest = {
            "version": 1,
            "task_id": task_id,
            "artifact_type": kind,
            "subject": topic,
            "prompt": str(prompt or "").strip(),
            "conversation_id": conversation_id,
            "created_at": int(time.time()),
            "directory": str(task_dir),
            "directory_relative": _relative_path(task_dir),
            "archived": bool(archive_enabled),
            "storage": "archive" if archive_enabled else "local",
            "primary": artifacts[0],
            "zip": artifacts[1] if len(artifacts) > 1 else None,
            "artifacts": artifacts,
            "preview": preview,
            "validation": validation,
            "result_files": [item["relative_path"] for item in artifacts],
            "prompt_file": str(prompt_path),
        }
        manifest_path = task_dir / "manifest.json"
        manifest["manifest_path"] = str(manifest_path)
        manifest["manifest_url"] = editable_url(manifest_path)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    except Exception:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise


def list_editable_files(
    *,
    limit: int = 200,
    query: str = "",
    kind: str = "",
    include_local: bool = True,
) -> dict[str, Any]:
    clean_kind = str(kind or "").strip().lower()
    allowed_kinds = {normalize_editable_type(clean_kind)} if clean_kind in {"ppt", "powerpoint", "presentation", "psd", "photoshop"} else EDITABLE_FILE_TYPES
    needle = str(query or "").strip().lower()
    manifests: list[dict[str, Any]] = []
    roots = [(EDITABLE_ROOT, True)]
    if include_local:
        roots.append((LOCAL_EDITABLE_ROOT, False))
    for root, _archived in roots:
        for file_kind in sorted(allowed_kinds):
            for manifest_path in (root / file_kind.upper()).glob("*/manifest.json"):
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    item = _normalize_manifest_urls(manifest if isinstance(manifest, dict) else {}, manifest_path)
                except Exception as exc:
                    print(f"⚠️ editable manifest read failed: {manifest_path}: {exc}")
                    continue
                haystack = " ".join(
                    str(value or "")
                    for value in [
                        item.get("subject"),
                        item.get("prompt"),
                        item.get("task_id"),
                        (item.get("primary") or {}).get("name"),
                        (item.get("zip") or {}).get("name"),
                    ]
                ).lower()
                if needle and needle not in haystack:
                    continue
                manifests.append(item)
    manifests.sort(key=lambda item: int(item.get("created_at") or 0), reverse=True)
    capped_limit = max(1, min(int(limit or 200), 1000))
    items = manifests[:capped_limit]
    return {
        "ok": True,
        "files": items,
        "total": len(manifests),
        "stats": {
            "total": len(manifests),
            "ppt": sum(1 for item in manifests if item.get("artifact_type") == "ppt"),
            "psd": sum(1 for item in manifests if item.get("artifact_type") == "psd"),
            "archived": sum(1 for item in manifests if item.get("archived") is not False),
            "local": sum(1 for item in manifests if item.get("archived") is False),
        },
    }


def delete_editable_item(rel_path: str) -> dict[str, Any]:
    directory = _resolve_editable_directory(rel_path)
    if not directory:
        file_path = resolve_editable_file(rel_path)
        directory = file_path.parent if file_path else None
    if not directory or not (directory / "manifest.json").exists():
        raise FileNotFoundError("editable file item not found")
    rel = _relative_path(directory)
    shutil.rmtree(directory)
    return {"ok": True, "directory_relative": rel}
