"""Standalone entrypoint packaged with optional Torch/Spandrel dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="upscale-worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--tile-size", type=int, default=256)
    parser.add_argument("--tile-overlap", type=int, default=32)
    args = parser.parse_args()

    from backend.upscale_runtime import _upscale_image_file_in_process

    def progress(ratio: float, message: str) -> None:
        print(json.dumps({"type": "progress", "progress": ratio, "message": message}, ensure_ascii=False), flush=True)

    result = _upscale_image_file_in_process(
        Path(args.input),
        Path(args.output),
        model_name=args.model,
        model_dir=Path(args.model_dir),
        device=args.device,
        tile_size=args.tile_size,
        tile_overlap=args.tile_overlap,
        progress=progress,
    )
    print(json.dumps({"type": "result", **result.__dict__}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
