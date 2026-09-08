"""Shared transparent-image to layered-PSD assembly pipeline."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops

from sidecars.chatgpt_pool.alpha_layer_splitter import write_transparent_layers


PSD_MIN_FILE_SIZE = 1024
PSD_TRANSPARENT_IMAGE_PROMPT = """根据上传的第一张参考图重建一张透明背景 PNG 素材图。
必须输出带真实 alpha 通道的 PNG；背景必须完全透明，不能使用白底、灰底或棋盘格模拟透明。
保持参考图的构图、相对位置、比例和视觉内容，不要裁掉任何素材。
互不接触的独立可见素材之间保留清晰透明间隔，不要添加背景板、阴影、光晕、雾化或装饰底色。
原图中本来相接或重叠的内容保持原样，不要为了拆分而改变构图。
只输出最终图片，不要解释过程。"""


@dataclass(frozen=True)
class PsdBundleResult:
    primary_path: Path
    zip_path: Path
    manifest_path: Path


def compose_psd_image_prompt(user_prompt: str) -> str:
    extra = str(user_prompt or "").strip()
    if not extra:
        return PSD_TRANSPARENT_IMAGE_PROMPT
    return PSD_TRANSPARENT_IMAGE_PROMPT + "\n\n以下是用户补充需求，请直接结合执行：\n" + extra


def decode_base64_image(value: str) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("base64 image is empty")
    match = re.match(r"^data:[^;]+;base64,(.*)$", raw, re.IGNORECASE | re.DOTALL)
    payload = re.sub(r"\s+", "", match.group(1) if match else raw)
    try:
        return base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError("base64 image payload is invalid") from exc


def _find_image_magick() -> str:
    for candidate in ("magick", "/opt/homebrew/bin/magick", "/usr/local/bin/magick", "convert"):
        found = shutil.which(candidate)
        if found:
            return found
        path = Path(candidate)
        if path.exists():
            return str(path)
    return ""


def _image_magick_identify_command(magick: str, path: Path) -> list[str]:
    if Path(magick).name.lower().startswith("magick"):
        return [magick, "identify", str(path)]
    for candidate in ("identify", "/opt/homebrew/bin/identify", "/usr/local/bin/identify"):
        found = shutil.which(candidate)
        if found:
            return [found, str(path)]
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return [str(candidate_path), str(path)]
    raise RuntimeError("ImageMagick identify is required to validate layered PSD output")


def validate_psd_bundle(psd_path: Path, zip_path: Path) -> None:
    if not psd_path.exists() or psd_path.stat().st_size < PSD_MIN_FILE_SIZE:
        raise RuntimeError("generated PSD is missing or abnormally small")
    if psd_path.read_bytes()[:4] != b"8BPS":
        raise RuntimeError("generated PSD does not have a valid 8BPS header")
    magick = _find_image_magick()
    if not magick:
        raise RuntimeError("ImageMagick is required to validate layered PSD output")
    identified = subprocess.run(
        _image_magick_identify_command(magick, psd_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
        check=False,
    )
    scenes = [line for line in identified.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    if identified.returncode != 0 or len(scenes) < 2:
        detail = identified.stderr.decode("utf-8", "replace")[-800:]
        raise RuntimeError(f"generated PSD does not contain an editable layer: {detail}")
    if not zip_path.exists() or not zipfile.is_zipfile(zip_path):
        raise RuntimeError("generated layer ZIP is invalid")

    bad_markers = ("fallback", "placeholder", "automatic extraction unavailable")
    with zipfile.ZipFile(zip_path) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist()]
        layer_names = sorted(
            name
            for name in names
            if name.startswith("layers/")
            and not name.endswith("/")
            and Path(name).suffix.lower() == ".png"
        )
        if not layer_names:
            raise RuntimeError("generated layer ZIP does not contain a PNG layer")
        canvas_size: tuple[int, int] | None = None
        has_transparency = False
        layer_images: list[Image.Image] = []
        for name in layer_names:
            with archive.open(name) as source_file:
                image = Image.open(BytesIO(source_file.read())).convert("RGBA")
                image.load()
            layer_images.append(image)
            if canvas_size is None:
                canvas_size = image.size
            elif image.size != canvas_size:
                raise RuntimeError("generated PNG layers do not use a consistent canvas size")
            alpha_min, alpha_max = image.getchannel("A").getextrema()
            has_transparency = has_transparency or alpha_min < alpha_max or alpha_min < 255
        if not has_transparency:
            raise RuntimeError("generated PNG layers do not contain real transparency")
        if "composite_preview.png" not in names:
            raise RuntimeError("generated layer ZIP is missing composite_preview.png")
        with archive.open("composite_preview.png") as source_file:
            preview = Image.open(BytesIO(source_file.read())).convert("RGBA")
            preview.load()
        if canvas_size and preview.size != canvas_size:
            raise RuntimeError("composite preview size does not match layer canvas")
        reconstructed = Image.new("RGBA", preview.size, (0, 0, 0, 0))
        for layer_image in layer_images:
            reconstructed = Image.alpha_composite(reconstructed, layer_image)
        expected = Image.alpha_composite(Image.new("RGBA", preview.size, (0, 0, 0, 0)), preview)
        if ImageChops.difference(reconstructed, expected).getbbox() is not None:
            raise RuntimeError("generated PNG layers do not reconstruct composite_preview.png exactly")
        for name in names:
            if Path(name).suffix.lower() not in {".txt", ".json", ".md"}:
                continue
            text = archive.read(name).decode("utf-8", "replace").lower()
            if any(marker in text for marker in bad_markers):
                raise RuntimeError(f"generated layer ZIP contains invalid marker text in {name}")


def build_transparent_psd_bundle(
    generated_data: bytes,
    reference_data: bytes,
    output_dir: str | Path,
    *,
    provider_route: str,
    conversation_id: str = "",
) -> PsdBundleResult:
    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    layer_set = write_transparent_layers(generated_data, output_path)
    with Image.open(layer_set.composite_path) as composite:
        width, height = composite.size

    reference_path = output_path / "input_reference.png"
    reference = Image.open(BytesIO(reference_data))
    reference.load()
    reference.convert("RGBA").save(reference_path, "PNG")

    clean_route = str(provider_route or "model_native").strip() or "model_native"
    manifest = {
        "version": 2,
        "generator": "gpt-image-2-transparent-alpha+local-components+imagemagick",
        "provider_route": clean_route,
        "conversation_id": str(conversation_id or ""),
        "canvas": {"width": width, "height": height},
        "layer_count": len(layer_set.layer_records),
        "reconstruction_exact": True,
        "layers": layer_set.layer_records,
        "split": layer_set.stats,
        "composite_preview": layer_set.composite_path.name,
        "generated_transparent": layer_set.source_path.name,
        "original_reference": reference_path.name,
    }
    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    readme_path = output_path / "README.txt"
    readme_path.write_text(
        "Editable PSD layers generated from a model-native transparent PNG using local alpha components.\n"
        "Touching visible content remains in one combined layer.\n"
        "Every layer PNG uses the full generated canvas and aligns at coordinates 0,0.\n",
        encoding="utf-8",
    )

    magick = _find_image_magick()
    if not magick:
        raise RuntimeError("ImageMagick is required to assemble a layered PSD")
    psd_path = output_path / "layered_output.psd"
    command = [magick]
    for path, label in [(layer_set.composite_path, "Composite"), *layer_set.layer_paths]:
        command.extend(["(", str(path), "-type", "TrueColorAlpha", "-set", "label", label, ")"])
    command.extend(["-define", "psd:preserve-opacity-mask=true", str(psd_path)])
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[-1200:]
        raise RuntimeError(f"ImageMagick layered PSD assembly failed: {detail}")

    zip_path = output_path / "layered_layers.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(layer_set.composite_path, layer_set.composite_path.name)
        archive.write(layer_set.source_path, layer_set.source_path.name)
        archive.write(reference_path, reference_path.name)
        archive.write(manifest_path, manifest_path.name)
        archive.write(readme_path, readme_path.name)
        for path, _ in layer_set.layer_paths:
            archive.write(path, f"layers/{path.name}")
    validate_psd_bundle(psd_path, zip_path)
    return PsdBundleResult(primary_path=psd_path, zip_path=zip_path, manifest_path=manifest_path)
