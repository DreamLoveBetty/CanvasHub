"""Local image upscaling runtime backed by Spandrel-compatible ESRGAN models."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Callable

from PIL import Image


UPSCALE_MODELS = {
    "4x-UltraSharp": {
        "filename": "4x-UltraSharp.pth",
        "label": "4x-UltraSharp",
        "family": "photo",
        "scale": 4,
    },
    "4x-AnimeSharp": {
        "filename": "4x-AnimeSharp.pth",
        "label": "4x-AnimeSharp",
        "family": "anime",
        "scale": 4,
    },
}

_MODEL_ALIASES = {
    "ultrasharp": "4x-UltraSharp",
    "4x-ultrasharp": "4x-UltraSharp",
    "4x_ultrasharp": "4x-UltraSharp",
    "photo": "4x-UltraSharp",
    "anime": "4x-AnimeSharp",
    "animesharp": "4x-AnimeSharp",
    "4x-animesharp": "4x-AnimeSharp",
    "4x_animesharp": "4x-AnimeSharp",
}


@dataclass(frozen=True)
class UpscaleResult:
    output_width: int
    output_height: int
    input_width: int
    input_height: int
    scale: int
    model: str
    device: str


class UpscaleRuntimeError(RuntimeError):
    """Raised when local upscaling cannot run."""


def normalize_upscale_model(value: str | None) -> str:
    raw = str(value or "").strip()
    if raw in UPSCALE_MODELS:
        return raw
    key = raw.lower().replace(" ", "").replace("/", "-")
    return _MODEL_ALIASES.get(key, "4x-UltraSharp")


def default_upscale_model_dir(project_root: Path) -> Path:
    return Path(project_root) / "models" / "upscale"


def resolve_upscale_model_path(model_name: str, model_dir: Path) -> Path:
    normalized = normalize_upscale_model(model_name)
    filename = UPSCALE_MODELS[normalized]["filename"]
    return Path(model_dir).expanduser() / filename


def available_upscale_models(model_dir: Path) -> list[dict]:
    base = Path(model_dir).expanduser()
    models = []
    for key, meta in UPSCALE_MODELS.items():
        path = base / meta["filename"]
        models.append({
            "id": key,
            "label": meta["label"],
            "family": meta["family"],
            "scale": meta["scale"],
            "filename": meta["filename"],
            "path": str(path),
            "available": path.is_file(),
        })
    return models


def _load_model(model_path: Path, device: str):
    # The macOS arm64 torch wheels can trip over Homebrew's OpenMP runtime
    # detection in long-lived app processes. Set before importing torch.
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    try:
        import torch
        from spandrel import ImageModelDescriptor, ModelLoader
    except Exception as exc:  # pragma: no cover - depends on optional local deps.
        raise UpscaleRuntimeError(
            "高清放大依赖未安装，请安装 torch、torchvision、numpy、spandrel。"
        ) from exc

    descriptor = ModelLoader().load_from_file(str(model_path))
    if not isinstance(descriptor, ImageModelDescriptor):
        raise UpscaleRuntimeError(f"模型不是图片放大模型：{model_path.name}")

    descriptor.eval()
    descriptor.to(device)
    return descriptor, torch


def pick_torch_device(preferred: str | None = None) -> str:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    try:
        import torch
    except Exception as exc:  # pragma: no cover - depends on optional local deps.
        raise UpscaleRuntimeError(
            "高清放大依赖未安装，请安装 torch、torchvision、numpy、spandrel。"
        ) from exc

    requested = str(preferred or "auto").strip().lower()
    if requested and requested != "auto":
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _image_to_tensor(image: Image.Image, torch):
    import numpy as np

    array = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
    return tensor.contiguous()


def _tensor_to_image(tensor, output_size: tuple[int, int]) -> Image.Image:
    import numpy as np

    tensor = tensor.detach().float().cpu().clamp_(0, 1).squeeze(0)
    array = tensor.permute(1, 2, 0).numpy()
    array = (array * 255.0).round().astype(np.uint8)
    image = Image.fromarray(array, mode="RGB")
    if image.size != output_size:
        image = image.resize(output_size, Image.Resampling.LANCZOS)
    return image


def _upscale_tensor_tiled(
    model,
    input_tensor,
    torch,
    *,
    scale: int,
    tile_size: int,
    tile_overlap: int,
    progress: Callable[[float, str], None] | None = None,
):
    _, channels, height, width = input_tensor.shape
    if tile_size <= 0 or max(width, height) <= tile_size:
        if progress:
            progress(0.25, "正在执行整图放大...")
        with torch.inference_mode():
            return model(input_tensor)

    output = torch.zeros((1, channels, height * scale, width * scale), device=input_tensor.device)
    weights = torch.zeros_like(output)
    xs = list(range(0, width, max(1, tile_size - tile_overlap)))
    ys = list(range(0, height, max(1, tile_size - tile_overlap)))
    total = max(1, len(xs) * len(ys))
    done = 0

    with torch.inference_mode():
        for y in ys:
            for x in xs:
                x0 = max(0, min(x, width))
                y0 = max(0, min(y, height))
                x1 = min(width, x0 + tile_size)
                y1 = min(height, y0 + tile_size)
                tile = input_tensor[:, :, y0:y1, x0:x1]
                tile_out = model(tile)

                ox0 = x0 * scale
                oy0 = y0 * scale
                ox1 = ox0 + tile_out.shape[-1]
                oy1 = oy0 + tile_out.shape[-2]
                output[:, :, oy0:oy1, ox0:ox1] += tile_out
                weights[:, :, oy0:oy1, ox0:ox1] += 1

                done += 1
                if progress:
                    progress(done / total, f"高清放大中 {done}/{total}")

    return output / weights.clamp_min(1)


def upscale_image_file(
    input_path: Path,
    output_path: Path,
    *,
    model_name: str,
    model_dir: Path,
    device: str | None = None,
    tile_size: int = 256,
    tile_overlap: int = 32,
    progress: Callable[[float, str], None] | None = None,
) -> UpscaleResult:
    normalized_model = normalize_upscale_model(model_name)
    model_path = resolve_upscale_model_path(normalized_model, model_dir)
    if not model_path.is_file():
        raise UpscaleRuntimeError(
            f"缺少高清放大模型：{model_path}。请把 {UPSCALE_MODELS[normalized_model]['filename']} 放到 models/upscale/。"
        )

    selected_device = pick_torch_device(device)
    descriptor, torch = _load_model(model_path, selected_device)
    scale = int(getattr(descriptor, "scale", None) or UPSCALE_MODELS[normalized_model]["scale"])

    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(input_path) as opened:
        source = opened.convert("RGBA") if opened.mode in ("RGBA", "LA", "P") else opened.convert("RGB")
        input_width, input_height = source.size
        alpha = source.getchannel("A") if source.mode == "RGBA" else None
        rgb = source.convert("RGB")

    if progress:
        progress(0.1, "正在载入高清放大模型...")
    tensor = _image_to_tensor(rgb, torch).to(selected_device)
    if progress:
        progress(0.18, "正在准备图像分块...")
    result_tensor = _upscale_tensor_tiled(
        descriptor,
        tensor,
        torch,
        scale=scale,
        tile_size=max(64, int(tile_size or 256)),
        tile_overlap=max(0, int(tile_overlap or 0)),
        progress=lambda ratio, text: progress(0.18 + ratio * 0.72, text) if progress else None,
    )

    output_size = (input_width * scale, input_height * scale)
    result_image = _tensor_to_image(result_tensor, output_size)
    if alpha is not None:
        result_alpha = alpha.resize(output_size, Image.Resampling.LANCZOS)
        result_image = result_image.convert("RGBA")
        result_image.putalpha(result_alpha)

    if progress:
        progress(0.95, "正在保存高清结果...")
    result_image.save(output_path, "PNG", optimize=True)

    try:
        if selected_device == "cuda":
            torch.cuda.empty_cache()
        elif selected_device == "mps":
            torch.mps.empty_cache()
    except Exception:
        pass

    return UpscaleResult(
        output_width=output_size[0],
        output_height=output_size[1],
        input_width=input_width,
        input_height=input_height,
        scale=scale,
        model=normalized_model,
        device=selected_device,
    )
