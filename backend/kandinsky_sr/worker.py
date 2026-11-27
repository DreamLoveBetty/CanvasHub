"""Isolated PyTorch MPS/CUDA/CPU worker for Kandinsky ImageSR 2.0.

Runs exclusively inside components/kandinsky-sr/venv. Never imported by the HTTP process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Dict

EVENT_PREFIX = "KSR_EVENT "


def _emit(event: str, **payload: Any) -> None:
    print(EVENT_PREFIX + json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def _start_parent_watch() -> None:
    value = os.environ.get("CANVASHUB_IMAGE_PARENT_PID", "")
    if not value.isdigit() or os.name != "posix":
        return
    parent = int(value)

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(0.25)
        os._exit(0)

    threading.Thread(target=watch, name="ksr-parent-watch", daemon=True).start()


def _pick_device(torch, requested: str = "auto"):
    choice = str(requested or "auto").strip().lower()
    if choice and choice != "auto":
        return torch.device(choice)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _extract_rgb_and_alpha(source_path: Path):
    from PIL import Image, ImageOps

    with Image.open(source_path) as opened:
        transposed = ImageOps.exif_transpose(opened)
        icc_profile = transposed.info.get("icc_profile")
        alpha = None
        if transposed.mode in ("RGBA", "LA", "PA"):
            rgba = transposed.convert("RGBA")
            alpha = rgba.getchannel("A")
            rgb = rgba.convert("RGB")
        elif "transparency" in transposed.info:
            rgba = transposed.convert("RGBA")
            alpha = rgba.getchannel("A")
            rgb = rgba.convert("RGB")
        else:
            rgb = transposed.convert("RGB")
        if icc_profile:
            rgb.info["icc_profile"] = icc_profile
        input_w, input_h = rgb.size
        return rgb, alpha, input_w, input_h


def _save_png_atomic(image, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".ksr-tmp.png")
    try:
        image.save(tmp, format="PNG", optimize=True)
        os.replace(tmp, output_path)
    finally:
        tmp.unlink(missing_ok=True)


def run_job(request_path: Path) -> Dict[str, Any]:
    spec = json.loads(request_path.read_text(encoding="utf-8"))
    source_path = Path(spec["input_path"])
    output_path = Path(spec["output_path"])
    model_dir = Path(spec["model_dir"])
    upscale_factor = int(spec["upscale_factor"])
    creativity = int(spec["creativity"])
    overlap = float(spec["overlap"])
    model_id = str(spec.get("model") or "kandinsky-imagesr-2.0")
    requested_device = str(spec.get("device") or "auto")
    vae_precision = str(spec.get("vae_precision") or "auto").strip().lower()

    import torch
    import torch.nn.functional as F
    from PIL import Image

    from kandinsky_image_sr import KandinskyImageSRPipeline
    from kandinsky_image_sr.attention import AttentionBackend, configure_attention
    from kandinsky_image_sr.image_processor import image_to_tensor, tensor_to_pil
    from kandinsky_image_sr.tiling import boundary_aware_window, pad_to_min_tile, tile_positions

    device = _pick_device(torch, requested_device)
    model_dtype = torch.float32 if device.type == "cpu" else torch.bfloat16

    _emit("progress", percent=6, stage="正在加载 Kandinsky SR 2.0 权重...")
    pipe = KandinskyImageSRPipeline.from_pretrained(
        str(model_dir),
        dtype=model_dtype,
        local_files_only=True,
    )
    pipe = pipe.to(device)

    if device.type == "mps":
        # Keep VAE in FP32 on MPS by default to avoid BF16 GroupNorm/Conv2d black/NaN artifacts.
        if vae_precision != "bf16":
            pipe.vae = pipe.vae.to(dtype=torch.float32)

    attn_req = AttentionBackend.AUTO if device.type == "cuda" else AttentionBackend.NATIVE
    attn_used = configure_attention(pipe.transformer, attn_req, device)

    rgb, alpha, input_w, input_h = _extract_rgb_and_alpha(source_path)
    timestep = pipe._resolve_timestep(upscale_factor, None, creativity)
    tile_size = int(pipe.config.tile_size)
    lq_tile = tile_size // upscale_factor
    stride = max(1, int(lq_tile * (1.0 - overlap)))

    input_tensor = image_to_tensor(rgb)
    padded, original_h, original_w = pad_to_min_tile(input_tensor, lq_tile)
    tops = tile_positions(padded.shape[-2], lq_tile, stride)
    lefts = tile_positions(padded.shape[-1], lq_tile, stride)
    cells = [(row, col) for row in range(len(tops)) for col in range(len(lefts))]
    total = max(1, len(cells))

    output_h = padded.shape[-2] * upscale_factor
    output_w = padded.shape[-1] * upscale_factor
    accumulator = torch.zeros(1, 3, output_h, output_w, device=device, dtype=torch.float32)
    weights = torch.zeros(1, 1, output_h, output_w, device=device, dtype=torch.float32)

    _emit("progress", percent=12, done=0, total=total, stage=f"准备超分 {total} 个分块 ({attn_used.value})")

    with torch.inference_mode():
        for done, (row, col) in enumerate(cells, start=1):
            top, left = tops[row], lefts[col]
            tile = padded[:, :, top : top + lq_tile, left : left + lq_tile]
            tile_hr = F.interpolate(tile, size=(tile_size, tile_size), mode="bicubic", align_corners=False)
            pred = pipe._infer_tiles(tile_hr.clamp(0.0, 1.0), timestep, device)
            if not torch.isfinite(pred).all():
                raise RuntimeError("Kandinsky SR 推理输出包含无效数值 (NaN/Inf)")
            window = boundary_aware_window(
                tile_size,
                tile_size,
                top=row == 0,
                bottom=row == len(tops) - 1,
                left=col == 0,
                right=col == len(lefts) - 1,
                device=device,
            )[None, None]
            top_hr, left_hr = top * upscale_factor, left * upscale_factor
            accumulator[:, :, top_hr : top_hr + tile_size, left_hr : left_hr + tile_size] += pred * window
            weights[:, :, top_hr : top_hr + tile_size, left_hr : left_hr + tile_size] += window

            if device.type == "mps":
                torch.mps.synchronize()
            elif device.type == "cuda":
                torch.cuda.synchronize()

            percent = 12 + int(round((done / total) * 78))
            _emit("progress", percent=percent, done=done, total=total, stage=f"超分分块 {done}/{total}")

    tensor = (accumulator / weights.clamp_min(1e-6))[
        :, :, : original_h * upscale_factor, : original_w * upscale_factor
    ].cpu()
    if not torch.isfinite(tensor).all():
        raise RuntimeError("Kandinsky SR 合并输出包含无效数值 (NaN/Inf)")

    result_image = tensor_to_pil(tensor)
    final_size = (input_w * upscale_factor, input_h * upscale_factor)
    if result_image.size != final_size:
        result_image = result_image.resize(final_size, Image.Resampling.LANCZOS)
    if alpha is not None:
        resized_alpha = alpha.resize(final_size, Image.Resampling.LANCZOS)
        result_image = result_image.convert("RGBA")
        result_image.putalpha(resized_alpha)

    _emit("progress", percent=94, stage="正在保存超分图片...")
    _save_png_atomic(result_image, output_path)

    del accumulator, weights, tensor, pipe
    if device.type == "mps":
        torch.mps.empty_cache()
    elif device.type == "cuda":
        torch.cuda.empty_cache()

    return {
        "input_width": input_w,
        "input_height": input_h,
        "output_width": final_size[0],
        "output_height": final_size[1],
        "scale": upscale_factor,
        "model": model_id,
        "device": device.type,
        "tiles": total,
    }


def main(argv=None) -> int:
    _start_parent_watch()
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        _emit("error", message="worker 参数数量无效")
        return 2
    try:
        result = run_job(Path(args[0]))
    except Exception as exc:
        _emit("error", message=str(exc) or type(exc).__name__)
        return 1
    _emit("result", **result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
