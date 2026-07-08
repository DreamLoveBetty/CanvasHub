#!/usr/bin/env python3
"""Edit images with gpt-image-2 directly through Codex Responses."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from codex_api import (
    DEFAULT_IMAGE_MAIN_MODEL,
    DEFAULT_IMAGE_TOOL_MODEL,
    DEFAULT_REASONING_EFFORT,
    CodexAPIError,
    build_image_request,
    decode_image_items_with_metadata,
    extract_images,
    image_file_to_data_url,
    post_codex_images,
    post_responses,
    prepare_image_prompt,
    resolve_size,
)


def edit_image_with_metadata(
    prompt: str,
    image_paths: list[str],
    mask_path: str | None,
    size: str,
    ratio: str | None,
    quality: str,
    background: str,
    moderation: str,
    output_format: str,
    output_compression: int,
    prompt_mode: str = "smart",
    main_model: str = DEFAULT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    transport_mode: str = "stream_then_nonstream",
) -> list[dict[str, object]]:
    resolved_size = resolve_size(size, ratio)
    request_prompt, _ = prepare_image_prompt(prompt, prompt_mode)
    image_urls = [image_file_to_data_url(path) for path in image_paths]
    tool: dict[str, object] = {
        "type": "image_generation",
        "action": "edit",
        "model": DEFAULT_IMAGE_TOOL_MODEL,
        "size": resolved_size,
        "quality": quality,
        "background": background,
        "output_format": output_format,
        "moderation": moderation,
    }
    if output_format in {"jpeg", "webp"}:
        tool["output_compression"] = output_compression
    if mask_path:
        tool["input_image_mask"] = {"image_url": image_file_to_data_url(mask_path)}

    print(f"Editing {len(image_paths)} image(s) @ {resolved_size}, quality={quality}, bg={background}")
    print(f"Prompt: {prompt[:160]}{'...' if len(prompt) > 160 else ''}")
    started = time.time()
    image_payload: dict[str, object] = {
        "model": DEFAULT_IMAGE_TOOL_MODEL,
        "prompt": request_prompt,
        "images": [{"image_url": image_url} for image_url in image_urls],
        "size": resolved_size,
        "quality": quality,
        "output_format": output_format,
    }
    if background and background != "auto":
        image_payload["background"] = background
    if moderation and moderation != "auto":
        image_payload["moderation"] = moderation
    if output_format in {"jpeg", "webp"}:
        image_payload["output_compression"] = output_compression
    if mask_path:
        image_payload["mask"] = {"image_url": image_file_to_data_url(mask_path)}
    try:
        image_response = post_codex_images("edits", image_payload)
    except Exception as images_exc:
        print(f"⚠️ Codex images/edits failed; falling back to responses: {images_exc}", file=sys.stderr)
        event = post_responses(
            build_image_request(
                prompt,
                tool,
                images=image_urls,
                prompt_mode=prompt_mode,
                main_model=main_model,
                reasoning_effort=reasoning_effort,
            ),
            transport_mode=transport_mode,
        )
        image_response = extract_images(event, response_format="b64_json")
    images = decode_image_items_with_metadata(image_response)
    print(f"Edited {len(images)} image(s) in {time.time() - started:.1f}s")
    return images


def edit_image(
    prompt: str,
    image_paths: list[str],
    mask_path: str | None,
    size: str,
    ratio: str | None,
    quality: str,
    background: str,
    moderation: str,
    output_format: str,
    output_compression: int,
    prompt_mode: str = "smart",
    main_model: str = DEFAULT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    transport_mode: str = "stream_then_nonstream",
) -> list[bytes]:
    image_items = edit_image_with_metadata(
        prompt=prompt,
        image_paths=image_paths,
        mask_path=mask_path,
        size=size,
        ratio=ratio,
        quality=quality,
        background=background,
        moderation=moderation,
        output_format=output_format,
        output_compression=output_compression,
        prompt_mode=prompt_mode,
        main_model=main_model,
        reasoning_effort=reasoning_effort,
        transport_mode=transport_mode,
    )
    return [item["image_bytes"] for item in image_items if item.get("image_bytes")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Edit images with gpt-image-2 without CLIProxyAPI")
    parser.add_argument("prompt", help="edit instruction")
    parser.add_argument("--image", "-i", action="append", required=True, help="source image; can repeat")
    parser.add_argument("--mask", "-m", default=None, help="optional mask image")
    parser.add_argument("--size", "-s", default="1k", help="auto, 1k, 2k, 4k, or valid WxH")
    parser.add_argument("--ratio", "-r", default=None, help="aspect ratio for shorthand sizes")
    parser.add_argument("--quality", "-q", default="auto", choices=["auto", "low", "medium", "high"])
    parser.add_argument("--bg", "--background", default="auto", choices=["opaque", "auto"])
    parser.add_argument("--moderation", default="auto", choices=["auto", "low"])
    parser.add_argument("--format", "-f", default="png", choices=["png", "webp", "jpeg"])
    parser.add_argument("--compression", type=int, default=100, help="0-100 for jpeg/webp")
    parser.add_argument("--prompt-mode", default="smart", choices=["smart", "faithful"], help="prompt interpretation mode")
    parser.add_argument("--main-model", default=DEFAULT_IMAGE_MAIN_MODEL, help="Responses main model")
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, choices=["none", "low", "medium", "high", "xhigh"])
    parser.add_argument("--output", "-o", default=None, help="output file path")
    parser.add_argument("--output-dir", default=None, help="output directory for multiple results")
    args = parser.parse_args()

    for image in args.image:
        if not Path(image).expanduser().is_file():
            print(f"Error: image not found: {image}", file=sys.stderr)
            sys.exit(1)
    if args.mask and not Path(args.mask).expanduser().is_file():
        print(f"Error: mask not found: {args.mask}", file=sys.stderr)
        sys.exit(1)

    try:
        images = edit_image(
            prompt=args.prompt,
            image_paths=args.image,
            mask_path=args.mask,
            size=args.size,
            ratio=args.ratio,
            quality=args.quality,
            background=args.bg,
            moderation=args.moderation,
            output_format=args.format,
            output_compression=args.compression,
            prompt_mode=args.prompt_mode,
            main_model=args.main_model,
            reasoning_effort=args.reasoning_effort,
        )
    except (CodexAPIError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not images:
        print("Error: no images returned", file=sys.stderr)
        sys.exit(1)

    ext = args.format
    if args.output and len(images) == 1:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(images[0])
        print(f"Saved: {out_path} ({len(images[0]) / 1024:.0f} KB)")
        return

    out_dir = Path(args.output_dir or "/tmp/codex-image-runtime-edits").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    for i, img in enumerate(images):
        out_path = out_dir / f"edit_{ts}_{i}.{ext}"
        out_path.write_bytes(img)
        print(f"Saved: {out_path} ({len(img) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
