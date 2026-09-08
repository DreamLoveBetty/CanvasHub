"""Model-native PSD provider built on transparent image editing plus local assembly."""

from __future__ import annotations

import base64
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable

from .provider_gpt_codex import edit_image_gpt_codex
from .provider_third_party_image import edit_image_third_party
from .psd_pipeline import (
    build_transparent_psd_bundle,
    compose_psd_image_prompt,
    decode_base64_image,
)


NATIVE_PSD_ROUTES = {"codex", "third_party_image_api"}


def _artifact_payload(path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "filename": path.name,
        "b64": base64.b64encode(path.read_bytes()).decode("ascii"),
        "size": path.stat().st_size,
    }


def generate_editable_psd_native(
    *,
    route: str,
    prompt: str,
    base64_images: list[str],
    ratio: str = "1:1",
    resolution: str = "2k",
    quality: str = "high",
    moderation: str = "auto",
    prompt_mode: str = "smart",
    main_model: str | None = None,
    reasoning_effort: str | None = None,
    total_timeout_seconds: int | None = None,
    on_provider_wait: Callable[[str, int, int], None] | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    provider_env: dict | None = None,
) -> dict[str, Any]:
    clean_route = str(route or "codex").strip().lower()
    if clean_route not in NATIVE_PSD_ROUTES:
        return {"success": False, "error": f"unsupported native PSD route: {clean_route}"}
    images = [str(item or "").strip() for item in (base64_images or []) if str(item or "").strip()]
    if not images:
        return {"success": False, "error": "PSD generation requires at least one reference image"}

    provider_prompt = compose_psd_image_prompt(prompt)
    try:
        if clean_route == "third_party_image_api":
            image_result = edit_image_third_party(
                provider_prompt,
                images,
                ratio=ratio,
                resolution=resolution,
                quality=quality,
                moderation=moderation,
                progress_callback=progress_callback,
                background="transparent",
                output_format="png",
            )
        else:
            image_result = edit_image_gpt_codex(
                provider_prompt,
                images,
                ratio=ratio,
                resolution=resolution,
                quality=quality,
                moderation=moderation,
                prompt_mode=prompt_mode,
                main_model=main_model,
                reasoning_effort=reasoning_effort,
                total_timeout_seconds=total_timeout_seconds,
                on_provider_wait=on_provider_wait,
                provider_env=provider_env,
                background="transparent",
            )
        if not image_result.get("success"):
            raise RuntimeError(image_result.get("error") or "native image edit did not return an image")
        generated_path = Path(str(image_result.get("image_path") or "")).expanduser()
        if not generated_path.is_file():
            raise RuntimeError("native image edit result file is missing")

        reference_data = decode_base64_image(images[0])
        with TemporaryDirectory(prefix=f"native_psd_{clean_route}_") as tmp:
            bundle = build_transparent_psd_bundle(
                generated_path.read_bytes(),
                reference_data,
                tmp,
                provider_route=clean_route,
            )
            result = {
                "success": True,
                "kind": "psd",
                "conversation_id": "",
                "primary": _artifact_payload(bundle.primary_path, "primary"),
                "zip": _artifact_payload(bundle.zip_path, "source_zip"),
                "provider": clean_route,
                "gpt_provider_route": clean_route,
                "generated_transparent_path": str(generated_path),
            }
        for key in (
            "main_model",
            "requested_main_model",
            "model_fallback_from",
            "reasoning_effort",
            "requested_reasoning_effort",
            "reasoning_fallback_from",
            "prompt_mode",
            "codex_auth_source",
            "third_party_api",
            "requested_resolution",
            "actual_resolution",
            "actual_resolutions",
            "effective_resolution",
            "requested_size",
            "actual_size",
            "actual_sizes",
        ):
            if image_result.get(key) not in (None, "", []):
                result[key] = image_result[key]
        return result
    except Exception as exc:
        return {
            "success": False,
            "kind": "psd",
            "provider": clean_route,
            "gpt_provider_route": clean_route,
            "error": str(exc),
        }
