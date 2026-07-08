#!/usr/bin/env python3
"""Opt-in third-party GPT image provider for true 4K generation/editing."""

from __future__ import annotations

import base64
import json
import mimetypes
import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from PIL import Image

from .app_config import BASE_DIR, get_third_party_image_config
from .image_resolution import build_resolution_metadata
from .storage_paths import daily_output_dir, write_obsidian_prompt_sidecar

GPT_OUTPUT_DIR = BASE_DIR / "gpt_outputs"
PROVIDER_NAME = "third-party-gpt-image"
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_UNTIL = 0.0
_RATE_LIMIT_MESSAGE = ""
_DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 180
_DEFAULT_DOWNLOAD_RETRIES = 2
_DOWNLOAD_CHUNK_SIZE = 256 * 1024
_DOWNLOAD_PROGRESS_INTERVAL_BYTES = 1024 * 1024
_DOWNLOAD_PROGRESS_INTERVAL_SECONDS = 1.0

ProgressCallback = Callable[[dict[str, Any]], None]


class _RetryableDownloadError(RuntimeError):
    pass


def _emit_progress(progress_callback: ProgressCallback | None, **payload: Any) -> None:
    if not progress_callback:
        return
    try:
        progress_callback(payload)
    except Exception as exc:
        print(f"⚠️ Third-party progress callback failed: {exc}")


def _normalize_quality(quality: str) -> str:
    value = str(quality or "auto").strip().lower()
    return value if value in {"low", "medium", "high", "auto"} else "auto"


def _normalize_format(value: str) -> str:
    fmt = str(value or "png").strip().lower()
    return fmt if fmt in {"png", "jpeg", "webp"} else "png"


def _download_retry_count(cfg: dict[str, Any]) -> int:
    try:
        value = int(cfg.get("download_retries", _DEFAULT_DOWNLOAD_RETRIES))
    except (TypeError, ValueError):
        value = _DEFAULT_DOWNLOAD_RETRIES
    return max(0, min(2, value))


def _ext_for_format(value: str) -> str:
    return "jpg" if _normalize_format(value) == "jpeg" else _normalize_format(value)


def _ratio_numbers(ratio: str) -> tuple[float, float]:
    try:
        w, h = str(ratio or "1:1").split(":", 1)
        width = max(1.0, float(w))
        height = max(1.0, float(h))
        if max(width, height) / min(width, height) > 3:
            return 1.0, 1.0
        return width, height
    except Exception:
        return 1.0, 1.0


def _snap16(value: float, minimum: int = 256) -> int:
    snapped = int(round(float(value) / 16.0) * 16)
    return max(minimum, snapped)


def _map_size(ratio: str, resolution: str) -> str:
    """Map local ratio/resolution to gpt-image-2 compatible size rules."""
    width_ratio, height_ratio = _ratio_numbers(ratio)
    aspect = width_ratio / height_ratio
    res = str(resolution or "1k").strip().lower()
    if res == "4k":
        long_edge = 3840
        max_pixels = 3840 * 2160
    elif res == "2k":
        long_edge = 2048
        max_pixels = 2048 * 2048
    else:
        long_edge = 1024 if abs(aspect - 1.0) < 0.01 else 1536
        max_pixels = 1024 * 1024 if abs(aspect - 1.0) < 0.01 else 1536 * 1024

    if aspect >= 1:
        height = min(long_edge / aspect, (max_pixels / aspect) ** 0.5)
        width = height * aspect
    else:
        height = min(long_edge, (max_pixels / aspect) ** 0.5)
        width = height * aspect

    width_px = min(3840, _snap16(width))
    height_px = min(3840, _snap16(height))
    while width_px * height_px > 3840 * 2160:
        if width_px >= height_px:
            width_px -= 16
            height_px = _snap16(width_px / aspect)
        else:
            height_px -= 16
            width_px = _snap16(height_px * aspect)
    return f"{width_px}x{height_px}"


def _decode_b64_image(value: str) -> bytes:
    payload = str(value or "").strip()
    if payload.startswith("data:") and "," in payload:
        payload = payload.split(",", 1)[1]
    return base64.b64decode(payload)


def _data_uri_to_file(value: str, fallback_name: str) -> tuple[str, bytes, str]:
    text = str(value or "").strip()
    mime = "image/png"
    filename = fallback_name
    if text.startswith("data:") and "," in text:
        header, payload = text.split(",", 1)
        match = re.match(r"data:([^;]+)", header)
        if match:
            mime = match.group(1)
        data = base64.b64decode(payload)
    else:
        data = base64.b64decode(text)
    ext = mimetypes.guess_extension(mime) or ".png"
    if not filename.lower().endswith(ext.lower()):
        filename = f"{Path(filename).stem}{ext}"
    return filename, data, mime


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


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
        print(f"⚠️ Third-party thumbnail failed: {exc}")

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
    size: str,
    image_count: int,
    revised_prompt: str = "",
) -> Path:
    actual = _image_dimensions(image_path)
    lines = [
        f"image_file: {image_path.name}",
        f"provider: {PROVIDER_NAME}",
        f"ratio: {ratio}",
        f"resolution: {resolution}",
        f"requested_size: {size}",
        f"quality: {quality}",
        f"image_count: {image_count}",
        f"actual_size: {actual[0]}x{actual[1]}" if actual else "actual_size: unknown",
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


def _extract_items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    items = data.get("data")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    if isinstance(items, dict):
        return [items]
    choices = data.get("choices")
    if isinstance(choices, list):
        extracted = []
        for choice in choices:
            message = choice.get("message") if isinstance(choice, dict) else {}
            content = message.get("content") if isinstance(message, dict) else ""
            if isinstance(content, str) and content.strip():
                extracted.append({"url": content.strip()})
        return extracted
    return []


def _content_length(response: requests.Response) -> int:
    value = str(response.headers.get("Content-Length") or response.headers.get("content-length") or "").strip()
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _is_retryable_download_error(exc: BaseException) -> bool:
    if isinstance(exc, _RetryableDownloadError):
        return True
    if isinstance(exc, requests.exceptions.RequestException):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "chunkedencodingerror",
            "incompleteread",
            "incomplete read",
            "connection broken",
            "connection reset",
            "protocolerror",
            "remote end closed",
            "timed out",
            "timeout",
        )
    )


def _download_error_message(exc: BaseException, attempt: int, max_attempts: int, bytes_received: int, total_bytes: int) -> str:
    total_part = f"/{total_bytes}" if total_bytes else ""
    return (
        f"第三方图片下载失败（第 {attempt}/{max_attempts} 次，已收到 {bytes_received}{total_part} 字节）: "
        f"{type(exc).__name__}: {exc}"
    )


def _download_url(
    session: requests.Session,
    url: str,
    timeout: int,
    progress_callback: ProgressCallback | None = None,
    max_retries: int = _DEFAULT_DOWNLOAD_RETRIES,
    item_index: int = 1,
    item_count: int = 1,
) -> bytes:
    source_url = str(url or "").strip()
    if not source_url:
        raise RuntimeError("第三方 API 返回了空图片下载地址")

    retry_count = max(0, min(2, int(max_retries or 0)))
    max_attempts = retry_count + 1
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        response = None
        bytes_received = 0
        total_bytes = 0
        buffer = bytearray()
        first_byte_reported = False
        last_emit_time = time.monotonic()
        last_emit_bytes = 0
        _emit_progress(
            progress_callback,
            event="download_start",
            attempt=attempt,
            max_attempts=max_attempts,
            item_index=item_index,
            item_count=item_count,
            bytes_received=0,
            total_bytes=0,
        )
        try:
            response = session.get(source_url, timeout=(15, timeout), stream=True)
            total_bytes = _content_length(response)
            if response.status_code >= 400:
                detail = str(response.text or "")[:200]
                message = f"download HTTP {response.status_code}: {detail}"
                if response.status_code == 429 or response.status_code >= 500:
                    raise _RetryableDownloadError(message)
                raise RuntimeError(message)

            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                if not chunk:
                    continue
                if not first_byte_reported:
                    first_byte_reported = True
                    _emit_progress(
                        progress_callback,
                        event="download_first_byte",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        item_index=item_index,
                        item_count=item_count,
                        bytes_received=0,
                        total_bytes=total_bytes,
                    )
                buffer.extend(chunk)
                bytes_received += len(chunk)
                now = time.monotonic()
                if (
                    bytes_received - last_emit_bytes >= _DOWNLOAD_PROGRESS_INTERVAL_BYTES
                    or now - last_emit_time >= _DOWNLOAD_PROGRESS_INTERVAL_SECONDS
                    or (total_bytes and bytes_received >= total_bytes)
                ):
                    _emit_progress(
                        progress_callback,
                        event="download_progress",
                        attempt=attempt,
                        max_attempts=max_attempts,
                        item_index=item_index,
                        item_count=item_count,
                        bytes_received=bytes_received,
                        total_bytes=total_bytes,
                    )
                    last_emit_time = now
                    last_emit_bytes = bytes_received

            if total_bytes and bytes_received < total_bytes:
                raise requests.exceptions.ChunkedEncodingError(
                    f"IncompleteRead({bytes_received} bytes read, {total_bytes - bytes_received} more expected)"
                )

            _emit_progress(
                progress_callback,
                event="download_complete",
                attempt=attempt,
                max_attempts=max_attempts,
                item_index=item_index,
                item_count=item_count,
                bytes_received=bytes_received,
                total_bytes=total_bytes,
            )
            return bytes(buffer)
        except Exception as exc:
            last_error = exc
            if attempt >= max_attempts or not _is_retryable_download_error(exc):
                raise RuntimeError(_download_error_message(exc, attempt, max_attempts, bytes_received, total_bytes)) from exc
            _emit_progress(
                progress_callback,
                event="download_retry",
                attempt=attempt,
                next_attempt=attempt + 1,
                max_attempts=max_attempts,
                item_index=item_index,
                item_count=item_count,
                bytes_received=bytes_received,
                total_bytes=total_bytes,
                error_type=type(exc).__name__,
                error=str(exc)[:240],
            )
            time.sleep(min(3, attempt))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

    raise RuntimeError(f"第三方图片下载失败：{last_error}") from last_error


def _save_outputs(
    items: list[dict[str, Any]],
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    size: str,
    output_format: str,
    file_prefix: str,
    session: requests.Session,
    timeout: int,
    progress_callback: ProgressCallback | None = None,
    download_retries: int = _DEFAULT_DOWNLOAD_RETRIES,
) -> dict[str, Any]:
    day_dir = daily_output_dir()
    day_dir.mkdir(parents=True, exist_ok=True)
    ext = _ext_for_format(output_format)
    stem = f"{file_prefix}_{int(time.time())}_{random.randint(1000, 9999)}"
    output_paths: list[Path] = []
    preview_paths: list[str] = []
    thumb_paths: list[str] = []
    prompt_file = ""
    revised_prompts: list[str] = []
    actual_sizes: list[dict[str, int]] = []

    for index, item in enumerate(items or [], start=1):
        suffix = "" if index == 1 else f"_{index:02d}"
        out_path = day_dir / f"{stem}{suffix}.{ext}"
        if item.get("b64_json"):
            image_bytes = _decode_b64_image(str(item.get("b64_json") or ""))
        elif item.get("url"):
            image_bytes = _download_url(
                session,
                str(item.get("url") or ""),
                timeout,
                progress_callback=progress_callback,
                max_retries=download_retries,
                item_index=index,
                item_count=len(items or []),
            )
        else:
            continue
        out_path.write_bytes(image_bytes)
        output_paths.append(out_path)

        revised_prompt = str(item.get("revised_prompt") or item.get("revisedPrompt") or "").strip()
        if revised_prompt:
            revised_prompts.append(revised_prompt)
        actual = _image_dimensions(out_path)
        if actual:
            actual_sizes.append({"width": actual[0], "height": actual[1]})
        sidecar = _write_prompt_sidecar(
            out_path,
            prompt=prompt,
            ratio=ratio,
            resolution=resolution,
            quality=quality,
            size=size,
            image_count=len(items or []),
            revised_prompt=revised_prompt,
        )
        if not prompt_file:
            prompt_file = str(sidecar)
        assets = _ensure_preview_assets(out_path, sidecar)
        preview_paths.append(assets["preview_path"])
        thumb_paths.append(assets["thumb_path"])

    if not output_paths:
        raise RuntimeError("第三方 API 没有返回可保存的图片")

    primary = output_paths[0]
    result = {
        "success": True,
        "image_path": str(primary),
        "image_paths": [str(path) for path in output_paths],
        "image_count": len(output_paths),
        "output_file": primary.name,
        "prompt_file": prompt_file,
        "preview_path": preview_paths[0] if preview_paths else "",
        "preview_paths": preview_paths,
        "thumb_path": thumb_paths[0] if thumb_paths else "",
        "thumbnail_paths": thumb_paths,
        "provider": PROVIDER_NAME,
        "third_party_api": True,
        "requested_size": size,
        "actual_sizes": actual_sizes,
        "revised_prompt": revised_prompts[0] if revised_prompts else "",
        "revised_prompts": revised_prompts,
    }
    result.update(build_resolution_metadata(resolution, actual_sizes, size))
    return result


def _session(cfg: dict[str, Any]) -> requests.Session:
    api_key = str(cfg.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("第三方图片 API Key 未配置，请先在设置面板填写。")
    session = requests.Session()
    session.trust_env = False
    session.headers.update({
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "tg-mini-app-img-gen/third-party-image",
    })
    return session


def _retry_after_seconds(response: requests.Response) -> int:
    value = str(response.headers.get("Retry-After") or "").strip()
    if not value:
        return _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS
    try:
        return max(30, min(1800, int(float(value))))
    except Exception:
        return _DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS


def _check_rate_limit_cooldown() -> None:
    with _RATE_LIMIT_LOCK:
        remaining = int(_RATE_LIMIT_UNTIL - time.time())
        message = _RATE_LIMIT_MESSAGE
    if remaining > 0:
        suffix = f"：{message}" if message else ""
        raise RuntimeError(f"第三方 API 正在限流冷却中，约 {remaining} 秒后再试{suffix}")


def _mark_rate_limited(response: requests.Response, message: str) -> None:
    cooldown = _retry_after_seconds(response)
    until = time.time() + cooldown
    with _RATE_LIMIT_LOCK:
        global _RATE_LIMIT_UNTIL, _RATE_LIMIT_MESSAGE
        _RATE_LIMIT_UNTIL = max(_RATE_LIMIT_UNTIL, until)
        _RATE_LIMIT_MESSAGE = message[:240]


def _endpoint(cfg: dict[str, Any], path_key: str) -> str:
    base_url = str(cfg.get("base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("第三方图片 API URL 未配置，请先在设置面板填写。")
    path = str(cfg.get(path_key) or "").strip()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base_url}{path}"


def _response_preview(text: str, limit: int = 240) -> str:
    preview = re.sub(r"\s+", " ", str(text or "")).strip()
    if not preview:
        return "<empty>"
    return preview[:limit]


def _parse_response_json(response: requests.Response) -> Any:
    if not response.text:
        return {}
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        content_type = str(response.headers.get("Content-Type") or response.headers.get("content-type") or "unknown")
        preview = _response_preview(response.text)
        if response.status_code == 429:
            _mark_rate_limited(response, preview)
        if response.status_code >= 400:
            raise RuntimeError(
                f"第三方 API HTTP {response.status_code}: 响应不是有效 JSON"
                f"（Content-Type: {content_type}，片段：{preview}）"
            ) from exc
        raise RuntimeError(
            f"第三方 API 返回了无法解析的响应"
            f"（HTTP {response.status_code}, Content-Type: {content_type}，片段：{preview}）"
        ) from exc


def _raise_http_error(response: requests.Response, data: Any) -> None:
    if response.status_code < 400:
        return
    message = ""
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("code") or "")
        elif error:
            message = str(error)
        message = message or str(data.get("message") or data.get("detail") or "")
    detail = message or response.text[:300]
    if response.status_code == 429:
        _mark_rate_limited(response, detail)
    raise RuntimeError(f"第三方 API HTTP {response.status_code}: {detail}")


def generate_image_third_party(
    prompt: str,
    ratio: str = "1:1",
    resolution: str = "4k",
    quality: str = "auto",
    image_count: int = 1,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    cfg = get_third_party_image_config()
    _check_rate_limit_cooldown()
    session = _session(cfg)
    timeout = int(cfg.get("timeout_seconds") or 900)
    download_retries = _download_retry_count(cfg)
    count = max(1, min(10, int(image_count or 1)))
    output_format = _normalize_format(cfg.get("format") or "png")
    size = _map_size(ratio, resolution)
    payload = {
        "model": cfg.get("model") or "gpt-image-2",
        "prompt": str(prompt or "").strip(),
        "n": count,
        "size": size,
        "quality": _normalize_quality(quality),
        "format": output_format,
    }
    response = session.post(
        _endpoint(cfg, "generate_path"),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=(15, timeout),
    )
    data = _parse_response_json(response)
    _raise_http_error(response, data)
    items = _extract_items(data)
    return _save_outputs(
        items,
        prompt=prompt,
        ratio=ratio,
        resolution=resolution,
        quality=_normalize_quality(quality),
        size=size,
        output_format=output_format,
        file_prefix="gpt_third_party",
        session=session,
        timeout=timeout,
        progress_callback=progress_callback,
        download_retries=download_retries,
    )


def edit_image_third_party(
    prompt: str,
    images: list[str],
    ratio: str = "1:1",
    resolution: str = "4k",
    quality: str = "auto",
    moderation: str = "auto",
    mask: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    cfg = get_third_party_image_config()
    _check_rate_limit_cooldown()
    session = _session(cfg)
    timeout = int(cfg.get("timeout_seconds") or 900)
    download_retries = _download_retry_count(cfg)
    output_format = _normalize_format(cfg.get("format") or "png")
    size = _map_size(ratio, resolution)
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for index, image in enumerate(images or [], start=1):
        filename, data, mime = _data_uri_to_file(image, f"image_{index}.png")
        files.append(("image", (filename, data, mime)))
    if not files:
        raise RuntimeError("第三方编辑需要至少一张参考图")
    if mask:
        filename, data, mime = _data_uri_to_file(mask, "mask.png")
        files.append(("mask", (filename, data, mime)))
    form = {
        "model": cfg.get("model") or "gpt-image-2",
        "prompt": str(prompt or "").strip(),
        "n": "1",
        "size": size,
        "quality": _normalize_quality(quality),
        "moderation": "low" if str(moderation or "").lower() == "low" else "auto",
    }
    response = session.post(
        _endpoint(cfg, "edit_path"),
        data=form,
        files=files,
        timeout=(15, timeout),
    )
    data = _parse_response_json(response)
    _raise_http_error(response, data)
    items = _extract_items(data)
    return _save_outputs(
        items,
        prompt=prompt,
        ratio=ratio,
        resolution=resolution,
        quality=_normalize_quality(quality),
        size=size,
        output_format=output_format,
        file_prefix="gpt_third_party_edit",
        session=session,
        timeout=timeout,
        progress_callback=progress_callback,
        download_retries=download_retries,
    )
