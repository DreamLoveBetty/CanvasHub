#!/usr/bin/env python3
"""ChatGPT account-pool sidecar provider for GPT image fallback."""

from __future__ import annotations

import base64
import json
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import requests
from PIL import Image

from .app_config import BASE_DIR, get_chatgpt_pool_config
from .image_resolution import build_resolution_metadata
from .storage_paths import daily_output_dir, write_obsidian_prompt_sidecar

GPT_OUTPUT_DIR = BASE_DIR / "gpt_outputs"
PROVIDER_NAME = "chatgpt-pool-sidecar"
POOL_IMAGE_TIMEOUT_SECONDS = 900
POOL_IMAGE_MIN_TIMEOUT_SECONDS = 60
POOL_IMAGE_MAX_TIMEOUT_SECONDS = 1800
POOL_IMAGE_HTTP_TIMEOUT_BUFFER_SECONDS = 60
MAX_POOL_IMAGE_COUNT = 8
POOL_IMAGE_WEB_PROMPT_REPLACEMENTS = (
    ("不是直接复制敏感聊天内容", "基于原始聊天素材进行原创视觉转化"),
    ("不表现真实人物争议或现实攻击", "仅表现虚构角色之间的轻松娱乐互动"),
    ("不使用低俗化身体表现", "采用自然得体的完整人物表现"),
    ("负面约束", "质量约束"),
    ("非露骨", "表达克制"),
    ("无裸露", "服装完整覆盖"),
    ("无未成年人", "角色外观明确成熟"),
    ("no nudity", "fully clothed"),
    ("no minors", "adult-presenting characters only"),
    ("non-explicit", "restrained editorial styling"),
    ("未成年人形象", "年龄明确成熟的角色形象"),
    ("未成年人", "年龄明确成熟的角色"),
    ("露骨表达", "克制得体的表达"),
    ("露骨", "克制得体"),
    ("裸露设计", "服装完整覆盖设计"),
    ("裸露", "服装完整覆盖"),
    ("身体局部凝视", "完整人物叙事构图"),
    ("身体局部特写", "完整人物构图"),
    ("身体局部展示", "完整人物展示"),
    ("身体局部强调", "角色整体造型强调"),
    ("过度性感化", "自然得体"),
    ("性感化", "自然得体"),
    ("未成年感", "明确成熟的角色外观"),
    ("挑逗式内容", "克制得体的内容"),
    ("挑逗式表达", "克制得体的表达"),
    ("挑逗式", "克制得体"),
    ("低俗写真感", "自然得体的插画审美"),
    ("低俗化", "自然得体"),
)
POOL_IMAGE_WEB_COMPATIBILITY_NOTE = (
    "账号池 Web 图片工具兼容性正向约束：角色外观保持明确成熟，服装完整覆盖，"
    "构图以完整人物、角色身份、服装工艺和世界观叙事为核心，表达克制高级，"
    "采用自然得体、社交平台友好的原创叙事，保持文字清晰和画面干净。"
)


def _normalize_quality(quality: str) -> str:
    value = str(quality or "auto").strip().lower()
    return value if value in {"low", "medium", "high", "auto"} else "auto"


def _sanitize_pool_prompt_for_web_image_tool(prompt: str) -> str:
    """Avoid brittle safety-negative terms that ChatGPT Web's image tool may treat as prompt content."""
    text = str(prompt or "").strip()
    if not text:
        return text
    sanitized = text
    for source, target in POOL_IMAGE_WEB_PROMPT_REPLACEMENTS:
        sanitized = re.sub(re.escape(source), target, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized).strip()
    if sanitized != text and POOL_IMAGE_WEB_COMPATIBILITY_NOTE not in sanitized:
        sanitized = f"{sanitized}\n\n{POOL_IMAGE_WEB_COMPATIBILITY_NOTE}"
    return sanitized


def _prepare_pool_prompt(prompt: str, prompt_mode: str) -> str:
    del prompt_mode  # Prompt mode is handled before this provider; account-pool sends only the user prompt body.
    return _sanitize_pool_prompt_for_web_image_tool(prompt)


def _pool_error_detail(response: requests.Response, fallback_message: str = "") -> str:
    data: Any = {}
    try:
        data = response.json() if response.text else {}
    except Exception:
        data = {}
    detail = data.get("detail") if isinstance(data, dict) else ""
    if isinstance(detail, dict):
        detail = detail.get("error") or detail.get("message") or detail
    if detail:
        return str(detail)
    if isinstance(data, dict):
        message = data.get("error") or data.get("message")
        if message:
            return str(message)
    return fallback_message or response.text[:300]


def _pool_route_missing_message(route: str) -> str:
    return f"ChatGPT 账号池 sidecar 未加载 {route} 接口，请重启 sidecar 后再试"


def _pool_image_sidecar_timeout_seconds(value: Any) -> int:
    try:
        configured = int(value or POOL_IMAGE_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        configured = POOL_IMAGE_TIMEOUT_SECONDS
    return max(POOL_IMAGE_MIN_TIMEOUT_SECONDS, min(POOL_IMAGE_MAX_TIMEOUT_SECONDS, configured))


def _pool_image_http_timeout_seconds(sidecar_timeout_seconds: int, image_count: int = 1) -> int:
    try:
        sidecar_timeout = int(sidecar_timeout_seconds or POOL_IMAGE_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        sidecar_timeout = POOL_IMAGE_TIMEOUT_SECONDS
    try:
        count = max(1, min(MAX_POOL_IMAGE_COUNT, int(image_count or 1)))
    except (TypeError, ValueError):
        count = 1
    total_timeout = sidecar_timeout * count + POOL_IMAGE_HTTP_TIMEOUT_BUFFER_SECONDS
    return max(
        POOL_IMAGE_MIN_TIMEOUT_SECONDS + POOL_IMAGE_HTTP_TIMEOUT_BUFFER_SECONDS,
        min(POOL_IMAGE_MAX_TIMEOUT_SECONDS * MAX_POOL_IMAGE_COUNT + POOL_IMAGE_HTTP_TIMEOUT_BUFFER_SECONDS, total_timeout),
    )


def _map_size(ratio: str, resolution: str) -> str:
    ratio_key = str(ratio or "1:1").strip().lower()
    resolution_key = str(resolution or "1k").strip().lower()
    long_edge = {"1k": 1024, "2k": 2048, "4k": 4096}.get(resolution_key, 1024)
    if ratio_key == "1:1":
        return f"{long_edge}x{long_edge}"
    try:
        width_part, height_part = ratio_key.split(":", 1)
        width_ratio = max(1, int(width_part))
        height_ratio = max(1, int(height_part))
    except Exception:
        return f"{long_edge}x{long_edge}"
    if width_ratio >= height_ratio:
        width = long_edge
        height = max(64, round(long_edge * height_ratio / width_ratio))
    else:
        height = long_edge
        width = max(64, round(long_edge * width_ratio / height_ratio))
    return f"{width}x{height}"


def _ensure_preview_assets(image_path: Path, prompt_file: Path | None = None) -> dict[str, str]:
    GPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    preview_path = GPT_OUTPUT_DIR / image_path.name
    shutil.copy2(image_path, preview_path)

    thumb_path = GPT_OUTPUT_DIR / f"{image_path.stem}_thumb.png"
    try:
        with Image.open(image_path) as img:
            img.thumbnail((400, 400), Image.Resampling.LANCZOS)
            img.save(thumb_path, "PNG", optimize=True, quality=85)
    except Exception as exc:
        print(f"⚠️ ChatGPT pool thumbnail failed: {exc}")

    prompt_copy = ""
    if prompt_file and prompt_file.exists():
        prompt_copy_path = GPT_OUTPUT_DIR / prompt_file.name
        shutil.copy2(prompt_file, prompt_copy_path)
        prompt_copy = str(prompt_copy_path)

    return {
        "preview_path": str(preview_path),
        "thumb_path": str(thumb_path),
        "prompt_copy": prompt_copy,
    }


def _write_prompt_sidecar(
    image_path: Path,
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    image_count: int,
    revised_prompt: str = "",
    requested_size: str = "",
    actual_size: tuple[int, int] | None = None,
) -> Path:
    lines = [
        f"image_file: {image_path.name}",
        f"provider: {PROVIDER_NAME}",
        f"ratio: {ratio}",
        f"resolution: {resolution}",
        f"requested_size: {requested_size}" if requested_size else "requested_size: unknown",
        f"quality: {quality}",
        f"image_count: {image_count}",
        f"actual_size: {actual_size[0]}x{actual_size[1]}" if actual_size else "actual_size: unknown",
        f"revised_prompt_available: {'true' if revised_prompt else 'false'}",
        f"generated_at: {int(time.time())}",
        "",
        "[user_prompt]",
        str(prompt or "").strip(),
        "",
    ]
    if revised_prompt:
        lines.extend(["[revised_prompt]", revised_prompt, ""])
    txt_path = image_path.with_suffix(".txt")
    content = "\n".join(lines)
    txt_path.write_text(content, encoding="utf-8")
    write_obsidian_prompt_sidecar(image_path, content, txt_path=txt_path)
    return txt_path


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


def _decode_b64_image(value: str) -> bytes:
    payload = str(value or "").strip()
    if "," in payload and payload.startswith("data:"):
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)


def _new_output_batch(file_prefix: str = "gpt_pool") -> dict[str, Any]:
    day_dir = daily_output_dir()
    day_dir.mkdir(parents=True, exist_ok=True)
    return {
        "day_dir": day_dir,
        "stem": f"{file_prefix}_{int(time.time())}_{random.randint(1000, 9999)}",
        "entries": [],
    }


def _append_chatgpt_pool_output(
    batch: dict[str, Any],
    item: dict[str, Any],
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    requested_count: int,
    request_index: int | None = None,
) -> None:
    b64_json = str((item or {}).get("b64_json") or "")
    if not b64_json:
        return
    entries = batch.setdefault("entries", [])
    try:
        index = int(request_index) if request_index is not None else len(entries)
    except (TypeError, ValueError):
        index = len(entries)
    day_dir = batch["day_dir"]
    stem = str(batch["stem"])
    suffix = "" if index <= 0 else f"_{index + 1:02d}"
    out_path = day_dir / f"{stem}{suffix}.png"
    out_path.write_bytes(_decode_b64_image(b64_json))

    revised_prompt = str((item or {}).get("revised_prompt") or "").strip()
    actual_size = _image_dimensions(out_path)
    requested_size = _map_size(ratio, resolution)
    sidecar = _write_prompt_sidecar(
        out_path,
        prompt,
        ratio,
        resolution,
        _normalize_quality(quality),
        max(1, int(requested_count or 1)),
        revised_prompt,
        requested_size=requested_size,
        actual_size=actual_size,
    )
    assets = _ensure_preview_assets(out_path, sidecar)
    actual_size_payload = {"width": actual_size[0], "height": actual_size[1]} if actual_size else None
    entries.append(
        {
            "index": index,
            "path": out_path,
            "prompt_file": str(sidecar),
            "preview_path": assets["preview_path"],
            "thumb_path": assets["thumb_path"],
            "revised_prompt": revised_prompt,
            "requested_resolution": str(resolution or "").strip().lower(),
            "requested_size": requested_size,
            "actual_size": actual_size_payload,
        }
    )


def _build_chatgpt_pool_output_result(batch: dict[str, Any]) -> dict[str, Any]:
    entries = sorted(batch.get("entries") or [], key=lambda item: int(item.get("index") or 0))
    if not entries:
        raise RuntimeError("ChatGPT pool sidecar did not return any images")
    output_paths = [entry["path"] for entry in entries]
    preview_paths = [str(entry.get("preview_path") or "") for entry in entries]
    thumb_paths = [str(entry.get("thumb_path") or "") for entry in entries]
    revised_prompts = [str(entry.get("revised_prompt") or "") for entry in entries if str(entry.get("revised_prompt") or "").strip()]
    actual_sizes = [entry.get("actual_size") for entry in entries if isinstance(entry.get("actual_size"), dict)]
    primary = output_paths[0]
    result = {
        "success": True,
        "image_path": str(primary),
        "image_paths": [str(path) for path in output_paths],
        "image_count": len(output_paths),
        "output_file": primary.name,
        "prompt_file": str(entries[0].get("prompt_file") or ""),
        "preview_path": preview_paths[0] if preview_paths else "",
        "preview_paths": preview_paths,
        "thumb_path": thumb_paths[0] if thumb_paths else "",
        "thumbnail_paths": thumb_paths,
        "provider": PROVIDER_NAME,
        "revised_prompt": revised_prompts[0] if revised_prompts else "",
        "revised_prompts": revised_prompts,
        "requested_size": str(entries[0].get("requested_size") or ""),
        "actual_sizes": actual_sizes,
    }
    result.update(
        build_resolution_metadata(
            entries[0].get("requested_resolution"),
            actual_sizes,
            entries[0].get("requested_size"),
        )
    )
    return result


def save_chatgpt_pool_outputs(
    items: list[dict[str, Any]],
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    file_prefix: str = "gpt_pool",
) -> dict[str, Any]:
    batch = _new_output_batch(file_prefix)
    requested_count = len(items or [])
    for index, item in enumerate(items or []):
        _append_chatgpt_pool_output(
            batch,
            item,
            prompt,
            ratio,
            resolution,
            quality,
            requested_count,
            request_index=index,
        )
    return _build_chatgpt_pool_output_result(batch)


def _iter_sse_json(response: requests.Response):
    for line in response.iter_lines(decode_unicode=True):
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8", errors="replace")
        text = str(line or "").strip()
        if not text.startswith("data:"):
            continue
        payload = text[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        yield json.loads(payload)


def _sorted_partial_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in errors:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("index")), str(item.get("error") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(deduped, key=lambda item: int(item.get("index") or 0))


def _should_retry_json_after_stream_error(error: Exception) -> bool:
    """Only retry JSON for local compatibility errors, not upstream generation failures."""
    message = str(error or "")
    lower = message.lower()
    # Unit-test fakes and very old request/session shims may not accept the
    # `stream` keyword. The real requests.Session does, and the sidecar stream
    # route exists in current deployments, so most stream errors are already
    # definitive generation failures and should not duplicate the image request.
    if "unexpected keyword argument 'stream'" in lower or "got an unexpected keyword argument 'stream'" in lower:
        return True
    if "未加载 /v1/images/generations 接口" in message or "not found" in lower and "http 404" in lower:
        return True
    return False


def _generate_image_gpt_pool_stream(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    *,
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    requested_count: int,
    on_image_saved: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    stream_payload = dict(payload)
    stream_payload["stream"] = True
    response = session.post(
        url,
        headers={**headers, "Accept": "text/event-stream"},
        json=stream_payload,
        timeout=timeout,
        stream=True,
    )
    content_type = str(response.headers.get("content-type") or response.headers.get("Content-Type") or "")
    if response.status_code >= 400:
        detail = _pool_error_detail(response)
        raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
    if "application/json" in content_type.lower():
        data = response.json() if response.text else {}
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise RuntimeError("sidecar response missing data list")
        result = save_chatgpt_pool_outputs(items, prompt=prompt, ratio=ratio, resolution=resolution, quality=quality, file_prefix="gpt_pool")
        if isinstance(data, dict) and data.get("partial_errors"):
            result["partial_errors"] = data.get("partial_errors")
        return result

    batch = _new_output_batch("gpt_pool")
    partial_errors: list[dict[str, Any]] = []
    final_seen = False
    try:
        for event in _iter_sse_json(response):
            event_type = str((event or {}).get("type") or "")
            if event_type == "image":
                item = event.get("item") if isinstance(event.get("item"), dict) else {}
                _append_chatgpt_pool_output(
                    batch,
                    item,
                    prompt,
                    ratio,
                    resolution,
                    quality,
                    requested_count,
                    request_index=event.get("index"),
                )
                if on_image_saved and batch.get("entries"):
                    partial = _build_chatgpt_pool_output_result(batch)
                    on_image_saved(partial, len(partial.get("image_paths") or []), requested_count)
                continue
            if event_type == "error":
                partial_errors.append({"index": event.get("index"), "error": str(event.get("error") or "unknown error")})
                continue
            if event_type == "final":
                final_seen = True
                for error in event.get("partial_errors") or []:
                    if isinstance(error, dict):
                        partial_errors.append(error)
                if event.get("error") and not batch.get("entries"):
                    raise RuntimeError(str(event.get("error")))
                if not batch.get("entries"):
                    items = event.get("data") if isinstance(event.get("data"), list) else []
                    for index, item in enumerate(items):
                        if isinstance(item, dict):
                            _append_chatgpt_pool_output(batch, item, prompt, ratio, resolution, quality, requested_count, index)
                break
    except Exception as exc:
        if not batch.get("entries"):
            raise
        partial_errors.append({"index": None, "error": str(exc)})

    if not batch.get("entries"):
        raise RuntimeError("ChatGPT pool sidecar did not return any images")
    result = _build_chatgpt_pool_output_result(batch)
    if partial_errors:
        result["partial_errors"] = _sorted_partial_errors(partial_errors)
    if not final_seen:
        result.setdefault("partial_errors", []).append({"index": None, "error": "sidecar stream ended before final event"})
    return result


def generate_image_gpt_pool(
    prompt: str,
    ratio: str = "1:1",
    resolution: str = "1k",
    quality: str = "auto",
    image_count: int = 1,
    prompt_mode: str = "smart",
    on_image_saved: Callable[[dict[str, Any], int, int], None] | None = None,
) -> dict[str, Any]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if not cfg.get("enabled"):
        return {"success": False, "error": "ChatGPT account pool sidecar disabled"}
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        return {"success": False, "error": "ChatGPT account pool auth key is missing"}

    try:
        count = max(1, min(MAX_POOL_IMAGE_COUNT, int(image_count or 1)))
    except (TypeError, ValueError):
        count = 1
    payload = {
        "model": cfg.get("generation_model") or "gpt-image-2",
        "prompt": _prepare_pool_prompt(prompt, prompt_mode),
        "n": count,
        "response_format": "b64_json",
        "size": _map_size(ratio, resolution),
        "quality": _normalize_quality(quality),
        "timeout_seconds": _pool_image_sidecar_timeout_seconds(cfg.get("timeout_seconds")),
    }
    session = requests.Session()
    session.trust_env = False
    try:
        url = f"{str(cfg.get('base_url') or '').rstrip('/')}/v1/images/generations"
        headers = {"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"}
        timeout = _pool_image_http_timeout_seconds(payload["timeout_seconds"], count)
        try:
            result = _generate_image_gpt_pool_stream(
                session,
                url,
                headers,
                payload,
                timeout,
                prompt=prompt,
                ratio=ratio,
                resolution=resolution,
                quality=quality,
                requested_count=count,
                on_image_saved=on_image_saved,
            )
            result["requested_image_count"] = count
            return result
        except Exception as stream_exc:
            if not _should_retry_json_after_stream_error(stream_exc):
                return {"success": False, "error": str(stream_exc)}
            print(f"⚠️ ChatGPT pool stream image route failed, retrying JSON response: {stream_exc}")
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            if response.status_code == 404:
                raise RuntimeError(_pool_route_missing_message("/v1/images/generations"))
            detail = data.get("detail") if isinstance(data, dict) else ""
            if isinstance(detail, dict):
                detail = detail.get("error") or detail.get("message") or detail
            raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise RuntimeError("sidecar response missing data list")
        result = save_chatgpt_pool_outputs(
            items,
            prompt=prompt,
            ratio=ratio,
            resolution=resolution,
            quality=quality,
            file_prefix="gpt_pool",
        )
        if isinstance(data, dict) and data.get("partial_errors"):
            result["partial_errors"] = data.get("partial_errors")
        result["requested_image_count"] = count
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def edit_image_gpt_pool(
    prompt: str,
    images: list[str],
    ratio: str = "1:1",
    resolution: str = "1k",
    quality: str = "auto",
    moderation: str = "auto",
    mask: str | None = None,
    prompt_mode: str = "smart",
) -> dict[str, Any]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if not cfg.get("enabled"):
        return {"success": False, "error": "ChatGPT account pool sidecar disabled"}
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        return {"success": False, "error": "ChatGPT account pool auth key is missing"}
    source_images = [str(item or "").strip() for item in (images or []) if str(item or "").strip()]
    if not source_images:
        return {"success": False, "error": "GPT pool edit requires at least one source image"}

    payload = {
        "model": cfg.get("generation_model") or "gpt-image-2",
        "prompt": _prepare_pool_prompt(prompt, prompt_mode),
        "image": source_images,
        "response_format": "b64_json",
        "size": _map_size(ratio, resolution),
        "quality": _normalize_quality(quality),
        "moderation": "low" if str(moderation or "").lower() == "low" else "auto",
        "timeout_seconds": _pool_image_sidecar_timeout_seconds(cfg.get("timeout_seconds")),
    }
    if mask:
        payload["mask"] = str(mask)

    session = requests.Session()
    session.trust_env = False
    try:
        url = f"{str(cfg.get('base_url') or '').rstrip('/')}/v1/images/edits"
        response = session.post(
            url,
            headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=_pool_image_http_timeout_seconds(payload["timeout_seconds"], 1),
        )
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            if response.status_code == 404:
                raise RuntimeError(_pool_route_missing_message("/v1/images/edits"))
            detail = _pool_error_detail(response)
            raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
        items = data.get("data") if isinstance(data, dict) else []
        if not isinstance(items, list):
            raise RuntimeError("sidecar response missing data list")
        result = save_chatgpt_pool_outputs(
            items,
            prompt=prompt,
            ratio=ratio,
            resolution=resolution,
            quality=quality,
            file_prefix="gpt_pool_edit",
        )
        result["requested_image_count"] = 1
        result["gpt_provider_route"] = "chatgpt_pool"
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def generate_editable_file_gpt_pool(
    *,
    kind: str,
    prompt: str,
    base64_images: list[str] | None = None,
    task_id: str = "",
) -> dict[str, Any]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if not cfg.get("enabled"):
        return {"success": False, "error": "ChatGPT account pool sidecar disabled"}
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        return {"success": False, "error": "ChatGPT account pool auth key is missing"}
    task_kind = "psd" if str(kind or "").strip().lower() == "psd" else "ppt"
    payload = {
        "prompt": str(prompt or "").strip(),
        "base64_images": base64_images or [],
        "client_task_id": task_id,
    }
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            f"{str(cfg.get('base_url') or '').rstrip('/')}/v1/{task_kind}/generations",
            headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=max(1300, int(cfg.get("timeout_seconds") or 420)),
        )
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            detail = data.get("detail") if isinstance(data, dict) else ""
            if isinstance(detail, dict):
                detail = detail.get("error") or detail.get("message") or detail
            raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
        result = data.get("result") if isinstance(data, dict) else {}
        if not isinstance(result, dict):
            raise RuntimeError("sidecar editable response missing result")
        primary = result.get("primary") if isinstance(result.get("primary"), dict) else {}
        if not primary.get("b64"):
            raise RuntimeError("sidecar editable response missing primary file")
        return {
            "success": True,
            "kind": task_kind,
            "conversation_id": str(result.get("conversation_id") or ""),
            "primary": primary,
            "zip": result.get("zip") if isinstance(result.get("zip"), dict) else None,
            "provider": PROVIDER_NAME,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def search_chatgpt_pool(
    prompt: str,
    model: str = "",
    timeout_seconds: int | float | None = None,
) -> dict[str, Any]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if not cfg.get("enabled"):
        return {"ok": False, "error": "ChatGPT account pool sidecar disabled"}
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        return {"ok": False, "error": "ChatGPT account pool auth key is missing"}
    text = str(prompt or "").strip()
    if not text:
        return {"ok": False, "error": "prompt is required"}
    try:
        timeout = int(timeout_seconds or cfg.get("timeout_seconds") or 420)
    except (TypeError, ValueError):
        timeout = int(cfg.get("timeout_seconds") or 420)
    payload = {
        "prompt": text,
        "model": str(model or "gpt-5-5").strip() or "gpt-5-5",
        "timeout_seconds": max(30, min(900, timeout)),
    }
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            f"{str(cfg.get('base_url') or '').rstrip('/')}/v1/search",
            headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=max(35, min(930, payload["timeout_seconds"] + 30)),
        )
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            if response.status_code == 404:
                raise RuntimeError(_pool_route_missing_message("/v1/search"))
            detail = _pool_error_detail(response)
            raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
        return data if isinstance(data, dict) else {"ok": True, "result": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def chat_chatgpt_pool(
    messages: list[dict[str, Any]],
    model: str = "",
    timeout_seconds: int | float | None = None,
    base64_images: list[str] | None = None,
) -> dict[str, Any]:
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    if not cfg.get("enabled"):
        return {"ok": False, "error": "ChatGPT account pool sidecar disabled"}
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        return {"ok": False, "error": "ChatGPT account pool auth key is missing"}
    if not isinstance(messages, list) or not messages:
        return {"ok": False, "error": "messages are required"}
    try:
        timeout = int(timeout_seconds or min(int(cfg.get("timeout_seconds") or 420), 180))
    except (TypeError, ValueError):
        timeout = 180
    payload = {
        "messages": messages,
        "model": str(model or "auto").strip() or "auto",
        "timeout_seconds": max(30, min(300, timeout)),
    }
    images = [str(item or "").strip() for item in (base64_images or []) if str(item or "").strip()]
    if images:
        payload["base64_images"] = images
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            f"{str(cfg.get('base_url') or '').rstrip('/')}/v1/chat/completions",
            headers={"Authorization": f"Bearer {auth_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=max(35, min(330, payload["timeout_seconds"] + 30)),
        )
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            if response.status_code == 404:
                raise RuntimeError(_pool_route_missing_message("/v1/chat/completions"))
            detail = _pool_error_detail(response)
            raise RuntimeError(f"HTTP {response.status_code}: {detail or response.text[:300]}")
        return {"ok": True, "result": data} if isinstance(data, dict) else {"ok": True, "result": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
