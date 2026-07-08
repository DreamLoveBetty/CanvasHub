#!/usr/bin/env python3
"""Generate images with gpt-image-2 directly through Codex Responses."""

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
    post_codex_images,
    post_responses,
    prepare_image_prompt,
    resolve_size,
)


def generate_with_metadata(
    prompt: str,
    size: str,
    ratio: str | None,
    quality: str,
    background: str,
    moderation: str,
    output_format: str,
    output_compression: int,
    n: int,
    prompt_mode: str = "smart",
    main_model: str = DEFAULT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    transport_mode: str = "stream_then_nonstream",
) -> list[dict[str, object]]:
    try:
        count = int(n or 1)
    except (TypeError, ValueError):
        count = 1
    count = max(1, min(10, count))
    resolved_size = resolve_size(size, ratio)
    request_prompt, _ = prepare_image_prompt(prompt, prompt_mode)
    tool: dict[str, object] = {
        "type": "image_generation",
        "action": "generate",
        "model": DEFAULT_IMAGE_TOOL_MODEL,
        "size": resolved_size,
        "quality": quality,
        "background": background,
        "output_format": output_format,
        "moderation": moderation,
    }
    if output_format in {"jpeg", "webp"}:
        tool["output_compression"] = output_compression
    if count > 1:
        tool["partial_images"] = 0

    print(f"Generating {count} image(s) @ {resolved_size}, quality={quality}, bg={background}, format={output_format}")
    print(f"Prompt: {prompt[:160]}{'...' if len(prompt) > 160 else ''}")
    started = time.time()

    images: list[dict[str, object]] = []
    image_payload: dict[str, object] = {
        "model": DEFAULT_IMAGE_TOOL_MODEL,
        "prompt": request_prompt,
        "size": resolved_size,
        "quality": quality,
        "output_format": output_format,
    }
    if count > 1:
        image_payload["n"] = count
    if background and background != "auto":
        image_payload["background"] = background
    if moderation and moderation != "auto":
        image_payload["moderation"] = moderation
    if output_format in {"jpeg", "webp"}:
        image_payload["output_compression"] = output_compression
    try:
        image_response = post_codex_images("generations", image_payload)
        images.extend(decode_image_items_with_metadata(image_response))
        if images:
            print(f"Generated {len(images)} image(s) in {time.time() - started:.1f}s")
            return images
        raise CodexAPIError("images/generations response did not decode any images", 502)
    except Exception as images_exc:
        print(f"⚠️ Codex images/generations failed; falling back to responses: {images_exc}", file=sys.stderr)

    for index in range(count):
        try:
            event = post_responses(
                build_image_request(
                    prompt,
                    tool,
                    prompt_mode=prompt_mode,
                    main_model=main_model,
                    reasoning_effort=reasoning_effort,
                ),
                transport_mode=transport_mode,
            )
            image_response = extract_images(event, response_format="b64_json")
            images.extend(decode_image_items_with_metadata(image_response))
        except Exception as exc:
            if images:
                print(
                    f"Warning: image {index + 1}/{count} failed after {len(images)} image(s); "
                    f"returning partial result: {exc}",
                    file=sys.stderr,
                )
                break
            raise

    print(f"Generated {len(images)} image(s) in {time.time() - started:.1f}s")
    return images


def generate(
    prompt: str,
    size: str,
    ratio: str | None,
    quality: str,
    background: str,
    moderation: str,
    output_format: str,
    output_compression: int,
    n: int,
    prompt_mode: str = "smart",
    main_model: str = DEFAULT_IMAGE_MAIN_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    transport_mode: str = "stream_then_nonstream",
) -> list[bytes]:
    image_items = generate_with_metadata(
        prompt=prompt,
        size=size,
        ratio=ratio,
        quality=quality,
        background=background,
        moderation=moderation,
        output_format=output_format,
        output_compression=output_compression,
        n=n,
        prompt_mode=prompt_mode,
        main_model=main_model,
        reasoning_effort=reasoning_effort,
        transport_mode=transport_mode,
    )
    return [item["image_bytes"] for item in image_items if item.get("image_bytes")]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate images with gpt-image-2 without CLIProxyAPI")
    parser.add_argument("prompt", help="Image prompt")
    parser.add_argument("--size", "-s", default="1k", help="auto, 1k, 2k, 4k, or valid WxH")
    parser.add_argument("--ratio", "-r", default=None, help="1:1, 4:3, 3:4, 16:9, 9:16, 3:2, 2:3, 4:5, 5:4, 21:9")
    parser.add_argument("--quality", "-q", default="auto", choices=["low", "medium", "high", "auto"])
    parser.add_argument("--bg", "--background", default="auto", choices=["opaque", "auto"])
    parser.add_argument("--moderation", default="auto", choices=["auto", "low"])
    parser.add_argument("--format", "-f", default="png", choices=["png", "webp", "jpeg"])
    parser.add_argument("--compression", type=int, default=100, help="0-100 for jpeg/webp")
    parser.add_argument("--prompt-mode", default="smart", choices=["smart", "faithful"], help="prompt interpretation mode")
    parser.add_argument("--main-model", default=DEFAULT_IMAGE_MAIN_MODEL, help="Responses main model")
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, choices=["none", "low", "medium", "high", "xhigh"])
    parser.add_argument("-n", type=int, default=1, help="number of images")
    parser.add_argument("--output", "-o", default=None, help="output file path for one image")
    parser.add_argument("--output-dir", default=None, help="output directory for multiple images")
    args = parser.parse_args()

    try:
        images = generate(
            prompt=args.prompt,
            size=args.size,
            ratio=args.ratio,
            quality=args.quality,
            background=args.bg,
            moderation=args.moderation,
            output_format=args.format,
            output_compression=args.compression,
            n=args.n,
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

    out_dir = Path(args.output_dir or "/tmp/codex-image-runtime-images").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    for i, img in enumerate(images):
        out_path = out_dir / f"gen_{ts}_{i}.{ext}"
        out_path.write_bytes(img)
        print(f"Saved: {out_path} ({len(img) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
