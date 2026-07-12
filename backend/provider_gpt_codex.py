#!/usr/bin/env python3
"""
Codex / local GPT provider wrapper for tg-mini-app-img-gen.

This module wraps the local Codex image runtime, then normalizes its
outputs so the Mini App can reuse the same history, preview, and delivery
flow as the browser GPT path.
"""

from __future__ import annotations

import base64
import mimetypes
import multiprocessing
import os
import queue as queue_mod
import shutil
import sys
import time
import random
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional

from .app_config import (
    APP_DATA_DIR,
    BASE_DIR,
    DEFAULT_GPT_IMAGE_MAIN_MODEL,
    DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_GPT_REASONING_EFFORT,
    DEFAULT_GPT_TRANSPORT_MODE,
    GPT_IMAGE_MAIN_MODELS,
    GPT_REASONING_EFFORTS,
    GPT_TRANSPORT_MODES,
    get_gpt_provider_config,
)
from PIL import Image
from .image_resolution import build_resolution_metadata
from .gpt_model_catalog import codex_fallback_models, normalize_model_id, resolve_route_model
from .storage_paths import daily_output_dir, write_obsidian_prompt_sidecar

GPT_OUTPUT_DIR = APP_DATA_DIR / "gpt_outputs"
CODEX_IMAGE_RUNTIME_DIR = BASE_DIR / "backend" / "codex_image_runtime"
CODEX_IMAGE_RUNTIME_SCRIPTS_DIR = CODEX_IMAGE_RUNTIME_DIR / "scripts"
if str(CODEX_IMAGE_RUNTIME_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(CODEX_IMAGE_RUNTIME_SCRIPTS_DIR))

from generate_image import generate_with_metadata as generate_gpt_image_2  # noqa: E402
from edit_image import edit_image_with_metadata as edit_gpt_image_2  # noqa: E402
from codex_api import inspect_auth_status, resolve_size  # noqa: E402

SUPPORTED_IMAGE_MAIN_MODELS = set(GPT_IMAGE_MAIN_MODELS)
SUPPORTED_REASONING_EFFORTS = set(GPT_REASONING_EFFORTS)
SUPPORTED_TRANSPORT_MODES = set(GPT_TRANSPORT_MODES)

TRANSIENT_ERROR_MARKERS = (
    "response.failed",
    "server_error",
    "stream disconnected",
    "ChunkedEncodingError",
    "Response ended prematurely",
    "temporarily unavailable",
    "try again",
    "retry your request",
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
)
UNSUPPORTED_CHATGPT_CODEX_MODEL_MARKERS = (
    "model is not supported when using codex with a chatgpt account",
    "model is not supported for codex with a chatgpt account",
    "model is not available",
    "model is unavailable",
    "unsupported model",
    "invalid model",
    "model_not_found",
    "model_access_denied",
    "does not exist or you do not have access",
)

LOCAL_PROVIDER_TOTAL_TIMEOUT_SECONDS = DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS


def _set_env_value(key: str, value: str | None, *, force: bool = False) -> None:
    if value in (None, ""):
        os.environ.pop(key, None)
        return
    if force or not os.environ.get(key):
        os.environ[key] = str(value)


def _managed_codex_provider_env() -> dict | None:
    try:
        from .managed_codex_oauth import get_auth_status as get_managed_codex_oauth_status
        from .managed_codex_oauth import get_provider_env as get_managed_codex_provider_env
    except Exception as exc:
        print(f"⚠️ managed Codex env unavailable: {exc}")
        return None

    try:
        managed_status = get_managed_codex_oauth_status()
    except Exception as exc:
        print(f"⚠️ managed Codex status unavailable: {exc}")
        return None

    if managed_status.get("enabled") and managed_status.get("configured"):
        try:
            return get_managed_codex_provider_env()
        except Exception as exc:
            print(f"⚠️ managed Codex auth unavailable; falling back to local Codex: {exc}")
    return None


def _parse_pixel_size(value: str) -> tuple[int, int] | None:
    try:
        width_text, height_text = str(value or "").lower().split("x", 1)
        width = int(width_text.strip())
        height = int(height_text.strip())
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _requested_pixel_size(resolution: str, ratio: str) -> tuple[int, int] | None:
    try:
        return _parse_pixel_size(resolve_size(resolution or "1k", ratio or "1:1"))
    except Exception:
        return None


def _ratio_value(ratio: str) -> float | None:
    try:
        width, height = str(ratio or "").split(":", 1)
        width_number = float(width)
        height_number = float(height)
    except (TypeError, ValueError):
        return None
    if width_number <= 0 or height_number <= 0:
        return None
    return width_number / height_number


def _render_contract_prompt(prompt: str, ratio: str, resolution: str) -> str:
    requested_size = _requested_pixel_size(resolution, ratio)
    size_line = f"{requested_size[0]}x{requested_size[1]} pixels" if requested_size else f"{resolution} resolution"
    contract = "\n".join(
        [
            "NON-NEGOTIABLE OUTPUT CONTRACT:",
            f"- Final canvas aspect ratio must be exactly {ratio}.",
            f"- Final requested image size is {size_line}.",
            "- Do not reinterpret the canvas as vertical, portrait, square, 4:5, 3:4, 9:16, or any other ratio.",
            "- If the creative brief contains conflicting orientation words, keep the subject/style but obey the canvas ratio above.",
            "- If an internal revised prompt is created, it must preserve this exact canvas ratio and requested size.",
            "",
            "USER CREATIVE BRIEF:",
        ]
    )
    return f"{contract}\n{str(prompt or '').strip()}"


def _image_pixel_dimensions(image_path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception:
        return None


def _render_contract_warnings(image_path: Path, ratio: str, resolution: str) -> list[str]:
    actual = _image_pixel_dimensions(image_path)
    if not actual:
        return []
    warnings = []
    actual_width, actual_height = actual
    requested_ratio = _ratio_value(ratio)
    if requested_ratio:
        actual_ratio = actual_width / max(1, actual_height)
        if abs(actual_ratio - requested_ratio) / requested_ratio > 0.035:
            warnings.append(
                f"actual_ratio_mismatch: requested {ratio}, got {actual_width}x{actual_height}"
            )
    requested_size = _requested_pixel_size(resolution, ratio)
    if requested_size:
        requested_width, requested_height = requested_size
        if actual_width < requested_width * 0.9 or actual_height < requested_height * 0.9:
            warnings.append(
                f"actual_resolution_lower_than_requested: requested {resolution} "
                f"({requested_width}x{requested_height}), got {actual_width}x{actual_height}"
            )
    return warnings


def _apply_gpt_provider_env() -> dict:
    cfg = get_gpt_provider_config()
    auth_file = cfg.get("auth_file")
    auth_dir = cfg.get("auth_dir")
    api_base = cfg.get("api_base")
    image_main_model = cfg.get("image_main_model")
    reasoning_effort = cfg.get("reasoning_effort")
    transport_mode = cfg.get("transport_mode")
    if auth_file and not os.environ.get("CODEX_API_AUTH_FILE"):
        os.environ["CODEX_API_AUTH_FILE"] = str(auth_file)
    if auth_dir and not os.environ.get("CODEX_API_AUTH_DIR"):
        os.environ["CODEX_API_AUTH_DIR"] = str(auth_dir)
    if api_base and not os.environ.get("CODEX_API_BASE"):
        os.environ["CODEX_API_BASE"] = str(api_base)
    if image_main_model and not os.environ.get("GPT_IMAGE_MAIN_MODEL"):
        os.environ["GPT_IMAGE_MAIN_MODEL"] = str(image_main_model)
    if reasoning_effort and not os.environ.get("GPT_REASONING_EFFORT"):
        os.environ["GPT_REASONING_EFFORT"] = str(reasoning_effort)
    if transport_mode and not os.environ.get("GPT_TRANSPORT_MODE"):
        os.environ["GPT_TRANSPORT_MODE"] = str(transport_mode)

    managed_env = _managed_codex_provider_env()
    if managed_env:
        for key, value in managed_env.items():
            _set_env_value(str(key), value, force=True)
    return cfg


def get_gpt_provider_auth_status() -> dict:
    """Return safe local Codex auth status for diagnostics."""
    cfg = _apply_gpt_provider_env()
    status = inspect_auth_status()
    auth_file = cfg.get("auth_file")
    auth_dir = cfg.get("auth_dir")
    status.update(
        {
            "auth_file_configured": bool(auth_file),
            "auth_file": str(auth_file) if auth_file else "",
            "auth_dir_configured": bool(auth_dir),
            "auth_dir": str(auth_dir) if auth_dir else "",
            "api_base_configured": bool(cfg.get("api_base")),
            "transport_mode": str(cfg.get("transport_mode") or DEFAULT_GPT_TRANSPORT_MODE),
            "total_timeout_seconds": int(cfg.get("total_timeout_seconds") or DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS),
            "allowed_transport_modes": sorted(SUPPORTED_TRANSPORT_MODES),
        }
    )
    return status


def _ensure_preview_assets(image_path: Path, prompt_file: Optional[str] = None) -> Dict[str, str]:
    GPT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    preview_path = GPT_OUTPUT_DIR / image_path.name
    shutil.copy2(image_path, preview_path)

    thumb_path = GPT_OUTPUT_DIR / f"{image_path.stem}_thumb.png"
    try:
        with Image.open(image_path) as img:
            img.thumbnail((400, 400), Image.Resampling.LANCZOS)
            img.save(thumb_path, "PNG", optimize=True, quality=85)
    except Exception as exc:
        print(f"⚠️ Codex preview thumbnail failed: {exc}")

    prompt_copy = ""
    if prompt_file:
        src_prompt = Path(prompt_file)
        if src_prompt.exists():
            prompt_copy_path = GPT_OUTPUT_DIR / src_prompt.name
            shutil.copy2(src_prompt, prompt_copy_path)
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
    moderation: str,
    image_count: int,
    prompt_mode: str = "smart",
    revised_prompt: str = "",
    main_model: str = DEFAULT_GPT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_GPT_REASONING_EFFORT,
    actual_size: tuple[int, int] | None = None,
    render_warnings: list[str] | None = None,
) -> Path:
    prompt_mode = _normalize_prompt_mode(prompt_mode)
    revised_prompt = str(revised_prompt or "").strip()
    render_warnings = render_warnings or []
    lines = [
        f"image_file: {image_path.name}",
        f"ratio: {ratio}",
        f"resolution: {resolution}",
        f"quality: {quality}",
        f"moderation: {moderation}",
        f"image_count: {image_count}",
        f"actual_size: {actual_size[0]}x{actual_size[1]}" if actual_size else "actual_size: unknown",
        f"render_contract_warnings: {len(render_warnings)}",
        f"main_model: {main_model}",
        f"reasoning_effort: {reasoning_effort}",
        f"prompt_mode: {prompt_mode}",
        f"revised_prompt_available: {'true' if revised_prompt else 'false'}",
        f"generated_at: {int(time.time())}",
        "",
        "[user_prompt]",
        prompt.strip(),
        "",
    ]
    if render_warnings:
        lines.extend(["[render_contract_warnings]", *render_warnings, ""])
    if revised_prompt:
        lines.extend(["[revised_prompt]", revised_prompt, ""])
    txt_path = image_path.with_suffix(".txt")
    content = "\n".join(lines)
    txt_path.write_text(content, encoding="utf-8")
    write_obsidian_prompt_sidecar(image_path, content, txt_path=txt_path)
    return txt_path


def _normalize_gpt_quality(quality: str) -> str:
    quality_key = str(quality or "auto").strip().lower()
    return quality_key if quality_key in ("low", "medium", "high", "auto") else "auto"


def _normalize_gpt_moderation(moderation: str) -> str:
    moderation_key = str(moderation or "auto").strip().lower()
    return moderation_key if moderation_key in ("auto", "low") else "auto"


def _normalize_prompt_mode(prompt_mode: str) -> str:
    mode = str(prompt_mode or "smart").strip().lower()
    return "faithful" if mode in ("faithful", "literal", "忠实原文") else "smart"


def _normalize_main_model(model: str | None) -> str:
    cfg = get_gpt_provider_config()
    fallback = str(cfg.get("image_main_model") or DEFAULT_GPT_IMAGE_MAIN_MODEL)
    return normalize_model_id(model or fallback, normalize_model_id(fallback))


def _normalize_reasoning_effort(effort: str | None) -> str:
    cfg = get_gpt_provider_config()
    fallback = str(cfg.get("reasoning_effort") or DEFAULT_GPT_REASONING_EFFORT).strip().lower()
    selected = str(effort or fallback).strip().lower()
    return selected if selected in SUPPORTED_REASONING_EFFORTS else fallback


def _reasoning_effort_for_model(model: str, effort: str) -> str:
    try:
        resolution = resolve_route_model("codex", model, reasoning_effort=effort)
        if resolution.get("model") == model and resolution.get("reasoning_efforts"):
            return str(resolution.get("reasoning_effort") or effort)
    except Exception:
        pass
    return effort


def _normalize_transport_mode(mode: str | None) -> str:
    cfg = get_gpt_provider_config()
    fallback = str(cfg.get("transport_mode") or DEFAULT_GPT_TRANSPORT_MODE).strip().lower()
    selected = str(mode or fallback).strip().lower()
    return selected if selected in SUPPORTED_TRANSPORT_MODES else fallback


def _normalize_total_timeout_seconds(timeout_seconds: int | None) -> int:
    cfg = get_gpt_provider_config()
    try:
        selected = int(timeout_seconds or cfg.get("total_timeout_seconds") or LOCAL_PROVIDER_TOTAL_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        selected = LOCAL_PROVIDER_TOTAL_TIMEOUT_SECONDS
    return max(30, min(1800, selected))


def _image_item_bytes(item) -> bytes:
    if isinstance(item, dict):
        data = item.get("image_bytes")
        return data if isinstance(data, bytes) else b""
    return item if isinstance(item, bytes) else b""


def _image_item_revised_prompt(item) -> str:
    if isinstance(item, dict):
        return str(item.get("revised_prompt") or "").strip()
    return ""


def _is_transient_provider_error(error: Exception | str) -> bool:
    text = str(error or "")
    non_retryable_markers = (
        "usage_limit_reached",
        "invalid_value",
        "image_generation_user_error",
        "moderation_blocked",
        "safety_violations",
        "rejected by the safety system",
    )
    if any(marker in text for marker in non_retryable_markers):
        return False
    return any(marker.lower() in text.lower() for marker in TRANSIENT_ERROR_MARKERS)


def _call_with_transient_retries(label: str, fn, attempts: int = 2):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _is_transient_provider_error(exc):
                raise
            wait_seconds = 3 * attempt
            print(f"⚠️ {label} transient failure ({attempt}/{attempts}): {exc}")
            print(f"⏳ Retrying {label} in {wait_seconds}s...")
            time.sleep(wait_seconds)
    raise last_error


def _call_with_model_compatibility_fallback(label: str, main_model: str, fn):
    selected_model = str(main_model or DEFAULT_GPT_IMAGE_MAIN_MODEL).strip()
    candidates = [selected_model, *codex_fallback_models(selected_model)]
    last_error = None
    for index, candidate in enumerate(candidates):
        try:
            return fn(candidate), candidate
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            unsupported = any(marker in message for marker in UNSUPPORTED_CHATGPT_CODEX_MODEL_MARKERS)
            if not unsupported or index >= len(candidates) - 1:
                raise
            next_model = candidates[index + 1]
            print(
                f"⚠️ {label} model {candidate} is unavailable for ChatGPT Codex auth; "
                f"retrying with {next_model}"
            )
    raise last_error or RuntimeError(f"{label} has no compatible model")


def _provider_subprocess_context():
    requested = os.environ.get("GPT_PROVIDER_START_METHOD", "").strip()
    if requested:
        try:
            return multiprocessing.get_context(requested)
        except ValueError:
            pass

    if sys.platform == "darwin":
        candidates = ("spawn", "forkserver", "fork")
    elif os.name != "nt":
        candidates = ("forkserver", "spawn", "fork")
    else:
        candidates = ("spawn",)

    for method in candidates:
        try:
            return multiprocessing.get_context(method)
        except ValueError:
            continue
    return multiprocessing.get_context()


def _provider_worker(queue, mode: str, payload: dict, provider_env: dict | None = None):
    try:
        for key, value in (provider_env or {}).items():
            if value in (None, ""):
                os.environ.pop(str(key), None)
            else:
                os.environ[str(key)] = str(value)
        if mode == "generate":
            result = generate_gpt_image_2(**payload)
        elif mode == "edit":
            result = edit_gpt_image_2(**payload)
        else:
            raise RuntimeError(f"unknown provider mode: {mode}")
        queue.put({"ok": True, "result": result})
    except Exception as exc:
        queue.put(
            {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        )


def _run_provider_with_total_timeout(
    label: str,
    mode: str,
    payload: dict,
    timeout_seconds: int = LOCAL_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    on_wait: Optional[Callable[[str, int, int], None]] = None,
    provider_env: dict | None = None,
):
    _apply_gpt_provider_env()
    ctx = _provider_subprocess_context()
    queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=_provider_worker, args=(queue, mode, payload, provider_env or {}), daemon=True)
    proc.start()

    deadline = time.monotonic() + timeout_seconds
    started_at = time.monotonic()
    last_wait_notice = 0.0
    message = None

    while message is None:
        now = time.monotonic()
        if on_wait and now - last_wait_notice >= 15:
            try:
                elapsed = int(now - started_at)
                remaining_seconds = max(0, int(deadline - now))
                on_wait(label, elapsed, remaining_seconds)
            except Exception as exc:
                print(f"⚠️ provider wait callback failed: {exc}")
            last_wait_notice = now

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            proc.terminate()
            proc.join(10)
            if proc.is_alive():
                proc.kill()
                proc.join(5)
            raise TimeoutError(f"{label} total timeout after {timeout_seconds}s")

        try:
            # Image payloads are large. Read the queue while the child is still
            # alive so its multiprocessing feeder thread cannot block process
            # exit while the parent is waiting in join().
            message = queue.get(timeout=min(0.25, remaining))
            break
        except queue_mod.Empty:
            if proc.is_alive():
                continue
            try:
                message = queue.get_nowait()
            except queue_mod.Empty:
                code = proc.exitcode
                raise RuntimeError(f"{label} exited without result (exitcode={code})")

    proc.join(10)
    if proc.is_alive():
        proc.terminate()
        proc.join(5)

    if not message.get("ok"):
        error_type = message.get("error_type") or "RuntimeError"
        raise RuntimeError(f"{error_type}: {message.get('error')}")

    return message.get("result")


def _decode_data_uri_image(data: str) -> tuple[bytes, str]:
    payload = str(data or "")
    mime_type = "image/png"
    if "," in payload:
        header, payload = payload.split(",", 1)
        if header.startswith("data:"):
            mime_type = header[5:].split(";", 1)[0] or mime_type
    image_bytes = base64.b64decode(payload)
    extension = mimetypes.guess_extension(mime_type) or ".png"
    if extension == ".jpe":
        extension = ".jpg"
    return image_bytes, extension


def _write_temp_source_images(images: list[str]) -> tuple[tempfile.TemporaryDirectory, list[str]]:
    tmp_dir = tempfile.TemporaryDirectory(prefix="gpt-edit-src-")
    paths: list[str] = []
    try:
        for index, image_data in enumerate(images, start=1):
            image_bytes, extension = _decode_data_uri_image(image_data)
            path = Path(tmp_dir.name) / f"source_{index:02d}{extension}"
            path.write_bytes(image_bytes)
            paths.append(str(path))
    except Exception:
        tmp_dir.cleanup()
        raise
    return tmp_dir, paths


def _save_gpt_outputs(
    images: list[bytes],
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    moderation: str,
    file_prefix: str = "gpt",
    prompt_mode: str = "smart",
    main_model: str = DEFAULT_GPT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_GPT_REASONING_EFFORT,
) -> dict:
    batch = _new_gpt_output_batch(file_prefix)
    batch["prompt_mode"] = _normalize_prompt_mode(prompt_mode)
    batch["main_model"] = main_model
    batch["reasoning_effort"] = reasoning_effort
    for image_item in images:
        image_bytes = _image_item_bytes(image_item)
        if not image_bytes:
            continue
        _append_gpt_output(
            batch,
            image_bytes,
            prompt,
            ratio,
            resolution,
            quality,
            moderation,
            len(images),
            prompt_mode=prompt_mode,
            revised_prompt=_image_item_revised_prompt(image_item),
            main_model=main_model,
            reasoning_effort=reasoning_effort,
        )
    return _build_gpt_output_result(batch)


def _new_gpt_output_batch(file_prefix: str = "gpt") -> dict:
    day_dir = daily_output_dir()
    day_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    file_stem = f"{file_prefix}_{ts}_{random.randint(1000, 9999)}"
    return {
        "day_dir": day_dir,
        "file_stem": file_stem,
        "output_paths": [],
        "preview_paths": [],
        "thumb_paths": [],
        "prompt_file": "",
        "prompt_mode": "smart",
        "main_model": DEFAULT_GPT_IMAGE_MAIN_MODEL,
        "reasoning_effort": DEFAULT_GPT_REASONING_EFFORT,
        "revised_prompts": [],
    }


def _append_gpt_output(
    batch: dict,
    image_bytes: bytes,
    prompt: str,
    ratio: str,
    resolution: str,
    quality: str,
    moderation: str,
    image_count: int,
    prompt_mode: str = "smart",
    revised_prompt: str = "",
    main_model: str = DEFAULT_GPT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_GPT_REASONING_EFFORT,
) -> Path:
    idx = len(batch["output_paths"]) + 1
    suffix = "" if idx == 1 else f"_{idx:02d}"
    out_path = batch["day_dir"] / f"{batch['file_stem']}{suffix}.png"
    out_path.write_bytes(image_bytes)
    batch["output_paths"].append(out_path)
    actual_size = _image_pixel_dimensions(out_path)
    render_warnings = _render_contract_warnings(out_path, ratio, resolution)
    batch.setdefault("requested_resolution", str(resolution or "").strip().lower())
    requested_size = _requested_pixel_size(resolution, ratio)
    if requested_size:
        batch.setdefault("requested_size", f"{requested_size[0]}x{requested_size[1]}")
    batch.setdefault("actual_sizes", []).append(actual_size)
    if render_warnings:
        batch.setdefault("render_contract_warnings", []).extend(render_warnings)

    prompt_file = str(
        _write_prompt_sidecar(
            out_path,
            prompt,
            ratio,
            resolution,
            quality,
            moderation,
            image_count,
            prompt_mode=prompt_mode,
            revised_prompt=revised_prompt,
            main_model=main_model,
            reasoning_effort=reasoning_effort,
            actual_size=actual_size,
            render_warnings=render_warnings,
        )
    )
    if idx == 1:
        batch["prompt_file"] = prompt_file
    if revised_prompt:
        batch.setdefault("revised_prompts", []).append(str(revised_prompt).strip())

    assets = _ensure_preview_assets(out_path, prompt_file)
    batch["preview_paths"].append(assets["preview_path"])
    batch["thumb_paths"].append(assets["thumb_path"])
    return out_path


def _build_gpt_output_result(batch: dict) -> dict:
    output_paths = batch["output_paths"]
    if not output_paths:
        raise RuntimeError("gpt-image-2 did not return any images")

    primary = output_paths[0]
    actual_sizes = [
        {"width": item[0], "height": item[1]}
        for item in (batch.get("actual_sizes") or [])
        if item
    ]
    result = {
        "success": True,
        "image_path": str(primary),
        "image_paths": [str(p) for p in output_paths],
        "image_count": len(output_paths),
        "output_file": primary.name,
        "prompt_file": batch["prompt_file"],
        "preview_path": batch["preview_paths"][0] if batch["preview_paths"] else "",
        "preview_paths": batch["preview_paths"],
        "thumb_path": batch["thumb_paths"][0] if batch["thumb_paths"] else "",
        "thumbnail_paths": batch["thumb_paths"],
        "provider": "codex-image-runtime",
        "prompt_mode": batch.get("prompt_mode") or "smart",
        "main_model": batch.get("main_model") or DEFAULT_GPT_IMAGE_MAIN_MODEL,
        "reasoning_effort": batch.get("reasoning_effort") or DEFAULT_GPT_REASONING_EFFORT,
        "revised_prompt": (batch.get("revised_prompts") or [""])[0] if batch.get("revised_prompts") else "",
        "revised_prompts": batch.get("revised_prompts") or [],
        "actual_sizes": actual_sizes,
        "render_contract_warnings": batch.get("render_contract_warnings") or [],
    }
    result.update(
        build_resolution_metadata(
            batch.get("requested_resolution"),
            actual_sizes,
            batch.get("requested_size"),
        )
    )
    return result


def generate_image_gpt_codex(
    prompt: str,
    ratio: str = "1:1",
    resolution: str = "1k",
    quality: str = "auto",
    image_count: int = 1,
    moderation: str = "auto",
    prompt_mode: str = "smart",
    main_model: str | None = None,
    reasoning_effort: str | None = None,
    transport_mode: str | None = None,
    total_timeout_seconds: int | None = None,
    on_image_saved: Optional[Callable[[dict, int, int], None]] = None,
    on_provider_wait: Optional[Callable[[str, int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    provider_env: dict | None = None,
) -> dict:
    """Generate image(s) through gpt-image-2 with local Codex auth."""
    result = {
        "success": False,
        "image_path": None,
        "image_paths": [],
        "prompt_file": None,
        "error": None,
    }

    try:
        quality_key = _normalize_gpt_quality(quality)
        moderation_key = _normalize_gpt_moderation(moderation)
        prompt_mode_key = _normalize_prompt_mode(prompt_mode)
        main_model_key = _normalize_main_model(main_model)
        requested_main_model_key = main_model_key
        requested_reasoning_effort_key = _normalize_reasoning_effort(reasoning_effort)
        reasoning_effort_key = _reasoning_effort_for_model(main_model_key, requested_reasoning_effort_key)
        transport_mode_key = _normalize_transport_mode(transport_mode)
        total_timeout_key = _normalize_total_timeout_seconds(total_timeout_seconds)

        try:
            count = int(image_count or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(10, count))

        batch_result = _new_gpt_output_batch("gpt")
        batch_result["prompt_mode"] = prompt_mode_key
        batch_result["main_model"] = main_model_key
        batch_result["reasoning_effort"] = reasoning_effort_key
        provider_prompt = _render_contract_prompt(prompt, ratio or "1:1", resolution or "1k")
        for index in range(count):
            if should_cancel and should_cancel():
                if batch_result["output_paths"]:
                    result.update(_build_gpt_output_result(batch_result))
                    result["canceled"] = True
                    return result
                result["error"] = "canceled"
                result["canceled"] = True
                return result
            try:
                label = f"gpt-image-2 generate {index + 1}/{count}"
                attempted_reasoning: dict[str, str] = {}

                def call_model(selected_model: str):
                    selected_effort = _reasoning_effort_for_model(selected_model, requested_reasoning_effort_key)
                    attempted_reasoning[selected_model] = selected_effort
                    return _call_with_transient_retries(
                        label,
                        lambda: _run_provider_with_total_timeout(
                            label,
                            "generate",
                            {
                                "prompt": provider_prompt,
                                "size": resolution or "1k",
                                "ratio": ratio or "1:1",
                                "quality": quality_key,
                                "background": "auto",
                                "moderation": moderation_key,
                                "output_format": "png",
                                "output_compression": 100,
                                "n": 1,
                                "prompt_mode": prompt_mode_key,
                                "main_model": selected_model,
                                "reasoning_effort": selected_effort,
                                "transport_mode": transport_mode_key,
                            },
                            timeout_seconds=total_timeout_key,
                            on_wait=on_provider_wait,
                            provider_env=provider_env,
                        ),
                    )

                batch, main_model_key = _call_with_model_compatibility_fallback(
                    label,
                    main_model_key,
                    call_model,
                )
                reasoning_effort_key = attempted_reasoning.get(main_model_key, reasoning_effort_key)
                batch_result["main_model"] = main_model_key
                batch_result["reasoning_effort"] = reasoning_effort_key
                if not batch:
                    raise RuntimeError("gpt-image-2 did not return any images")
                for image_item in batch:
                    image_bytes = _image_item_bytes(image_item)
                    if not image_bytes:
                        continue
                    _append_gpt_output(
                        batch_result,
                        image_bytes,
                        prompt,
                        ratio,
                        resolution,
                        quality_key,
                        moderation_key,
                        count,
                        prompt_mode=prompt_mode_key,
                        revised_prompt=_image_item_revised_prompt(image_item),
                        main_model=main_model_key,
                        reasoning_effort=reasoning_effort_key,
                    )
                    if on_image_saved:
                        try:
                            partial = _build_gpt_output_result(batch_result)
                            on_image_saved(partial, len(batch_result["output_paths"]), count)
                        except Exception as callback_exc:
                            print(f"⚠️ GPT progress callback failed: {callback_exc}")
                    if should_cancel and should_cancel():
                        result.update(_build_gpt_output_result(batch_result))
                        result["canceled"] = True
                        return result
            except Exception as exc:
                if batch_result["output_paths"]:
                    print(
                        f"⚠️ gpt-image-2 generate {index + 1}/{count} failed after "
                        f"{len(batch_result['output_paths'])} image(s); saving partial result: {exc}"
                    )
                    break
                raise
        if not batch_result["output_paths"]:
            raise RuntimeError("gpt-image-2 did not return any images")

        result.update(_build_gpt_output_result(batch_result))
        if main_model_key != requested_main_model_key:
            result["requested_main_model"] = requested_main_model_key
            result["model_fallback_from"] = requested_main_model_key
        if reasoning_effort_key != requested_reasoning_effort_key:
            result["requested_reasoning_effort"] = requested_reasoning_effort_key
            result["reasoning_fallback_from"] = requested_reasoning_effort_key
    except Exception as exc:
        result["error"] = str(exc)

    return result


def edit_image_gpt_codex(
    prompt: str,
    images: list[str],
    ratio: str = "1:1",
    resolution: str = "1k",
    quality: str = "auto",
    moderation: str = "auto",
    mask: str | None = None,
    prompt_mode: str = "smart",
    main_model: str | None = None,
    reasoning_effort: str | None = None,
    transport_mode: str | None = None,
    total_timeout_seconds: int | None = None,
    on_provider_wait: Optional[Callable[[str, int, int], None]] = None,
    provider_env: dict | None = None,
) -> dict:
    """Edit image(s) through gpt-image-2 with local Codex auth."""
    result = {
        "success": False,
        "image_path": None,
        "image_paths": [],
        "prompt_file": None,
        "error": None,
    }

    tmp_sources = None
    tmp_mask = None
    try:
        if not images:
            raise RuntimeError("GPT edit requires at least one source image")

        quality_key = _normalize_gpt_quality(quality)
        moderation_key = _normalize_gpt_moderation(moderation)
        prompt_mode_key = _normalize_prompt_mode(prompt_mode)
        main_model_key = _normalize_main_model(main_model)
        requested_main_model_key = main_model_key
        requested_reasoning_effort_key = _normalize_reasoning_effort(reasoning_effort)
        reasoning_effort_key = _reasoning_effort_for_model(main_model_key, requested_reasoning_effort_key)
        transport_mode_key = _normalize_transport_mode(transport_mode)
        total_timeout_key = _normalize_total_timeout_seconds(total_timeout_seconds)
        tmp_sources, source_paths = _write_temp_source_images(images)
        provider_prompt = _render_contract_prompt(prompt, ratio or "1:1", resolution or "1k")

        mask_path = None
        if mask:
            tmp_mask, mask_paths = _write_temp_source_images([mask])
            mask_path = mask_paths[0] if mask_paths else None

        attempted_reasoning: dict[str, str] = {}

        def call_model(selected_model: str):
            selected_effort = _reasoning_effort_for_model(selected_model, requested_reasoning_effort_key)
            attempted_reasoning[selected_model] = selected_effort
            return _call_with_transient_retries(
                "gpt-image-2 edit",
                lambda: _run_provider_with_total_timeout(
                    "gpt-image-2 edit",
                    "edit",
                    {
                        "prompt": provider_prompt,
                        "image_paths": source_paths,
                        "mask_path": mask_path,
                        "size": resolution or "1k",
                        "ratio": ratio or "1:1",
                        "quality": quality_key,
                        "background": "auto",
                        "moderation": moderation_key,
                        "output_format": "png",
                        "output_compression": 100,
                        "prompt_mode": prompt_mode_key,
                        "main_model": selected_model,
                        "reasoning_effort": selected_effort,
                        "transport_mode": transport_mode_key,
                    },
                    timeout_seconds=total_timeout_key,
                    on_wait=on_provider_wait,
                    provider_env=provider_env,
                ),
            )

        edited_images, main_model_key = _call_with_model_compatibility_fallback(
            "gpt-image-2 edit",
            main_model_key,
            call_model,
        )
        reasoning_effort_key = attempted_reasoning.get(main_model_key, reasoning_effort_key)
        result.update(
            _save_gpt_outputs(
                edited_images,
                prompt,
                ratio,
                resolution,
                quality_key,
                moderation_key,
                file_prefix="gpt_edit",
                prompt_mode=prompt_mode_key,
                main_model=main_model_key,
                reasoning_effort=reasoning_effort_key,
            )
        )
        if main_model_key != requested_main_model_key:
            result["requested_main_model"] = requested_main_model_key
            result["model_fallback_from"] = requested_main_model_key
        if reasoning_effort_key != requested_reasoning_effort_key:
            result["requested_reasoning_effort"] = requested_reasoning_effort_key
            result["reasoning_fallback_from"] = requested_reasoning_effort_key
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if tmp_mask:
            tmp_mask.cleanup()
        if tmp_sources:
            tmp_sources.cleanup()

    return result
