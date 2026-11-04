"""MOSS result policy: archive the original first, derive from it, and never let a derivative fail the job."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

from PIL import Image, ImageDraw

from ..local_image.archiving import archive_pngs
from .contracts import ENGINE

SIDECAR_SUFFIX = ".moss.json"
OVERLAY_DIRECTORY = ".moss-overlays"
TELEGRAM_CAPTION = "MOSS · MLX 本地生成"
CANCELED = {"canceled", "cancelled"}
GRID_LINE = 2


def _params(task):
    params = task.get("params")
    return params if isinstance(params, dict) else {}


def _replay(task):
    """A task that already published keeps its record; nothing is rewritten or sent twice."""
    params = _params(task)
    return {"published": False, "status": task.get("status"), "result_file": task.get("result_file"),
            "result_files": task.get("result_files") or [], "artifacts": params.get("artifacts") or [],
            "params": params, "warnings": params.get("warnings") or [], "telegram_error": None}


def _source_image(task_id, result, job_dir):
    if not re.fullmatch(r"moss_[0-9a-f]+", str(task_id)):
        raise ValueError("MOSS 任务 ID 无效")
    paths = [Path(path).resolve() for path in result.get("paths") or []]
    if len(paths) != 1 or not paths[0].is_file() or not paths[0].is_relative_to(Path(job_dir).resolve()):
        raise ValueError("MOSS 结果文件无效")
    return paths[0]


def _metadata(params, result):
    return {"engine": ENGINE, "role": "original", "seed": result.get("seed"), "effective": result.get("effective"),
            **{key: params.get(key) for key in ("mode", "raw_prompt", "negative_prompt", "layout_draft", "prompt_hash", "geometry_spec",
                                                "geometry_hash", "text_sources")}}


def _save_png(image, destination):
    pending = destination.with_suffix(".png.part")
    image.save(pending, format="PNG")
    os.replace(pending, destination)


def _checked_boxes(image, geometry):
    if image.size != (geometry["width"], geometry["height"]):
        raise ValueError("整图尺寸与分镜几何不一致")
    for panel in geometry["panels"]:
        x1, y1, x2, y2 = panel["bbox"]
        if not 0 <= x1 < x2 <= image.width or not 0 <= y1 < y2 <= image.height:
            raise ValueError("分镜切图范围越界")
    return geometry["panels"]


def _write_panel(original, source, panel, caption, task, seed, write_prompt_sidecar):
    index = panel["index"]
    destination = original.with_name(f"{original.stem}_p{index + 1:02d}.png")
    crop = source.crop(tuple(panel["bbox"]))
    _save_png(crop, destination)
    text = destination.with_suffix(".txt")
    text.write_text(task["prompt"].strip() + "\n", encoding="utf-8")
    write_prompt_sidecar(destination, task["prompt"], txt_path=text)
    artifact = {"role": "panel", "file": destination.name, "width": crop.width, "height": crop.height,
                "panel_id": panel["panel_id"], "panel_index": index, "source_bbox": list(panel["bbox"]),
                "original_ref": original.name}
    destination.with_suffix(SIDECAR_SUFFIX).write_text(json.dumps(
        {**artifact, "engine": ENGINE, "caption": caption, "seed": seed, "seed_scope": "page"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return artifact


def _remove_panels(original):
    for path in original.parent.glob(f"{original.stem}_p[0-9][0-9].*"):
        path.unlink(missing_ok=True)


def _split(original, task, seed, write_prompt_sidecar):
    """All panels or none: a partial storyboard is worse than the delivered whole page."""
    params = _params(task)
    draft = params.get("layout_draft") if isinstance(params.get("layout_draft"), dict) else {}
    captions = {item.get("id"): item.get("caption") for item in draft.get("panels") or []}
    try:
        with Image.open(original) as source:
            source.load()
            panels = _checked_boxes(source, params["geometry_spec"])
            return [_write_panel(original, source, panel, captions.get(panel["panel_id"]), task, seed,
                                 write_prompt_sidecar) for panel in panels]
    except (OSError, ValueError, KeyError, TypeError) as error:
        _remove_panels(original)
        raise RuntimeError(f"切图失败，已保留整图：{error}") from error


def _overlay(original, geometry):
    """Optional derivative outside the asset grid; the original and panels never carry these lines."""
    destination = original.parent / OVERLAY_DIRECTORY / f"{original.stem}_grid.png"
    destination.parent.mkdir(exist_ok=True)
    with Image.open(original) as source:
        canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    for panel in geometry["panels"]:
        draw.rectangle(tuple(panel["bbox"]), outline=(255, 255, 255), width=GRID_LINE)
    _save_png(canvas, destination)
    return {"role": "grid_overlay", "file": f"{OVERLAY_DIRECTORY}/{destination.name}", "width": canvas.width,
            "height": canvas.height, "original_ref": original.name}


def _derive(original, task, seed, write_prompt_sidecar):
    params, artifacts, warnings = _params(task), [], []
    storyboard = params.get("mode") == "storyboard"
    if storyboard and params.get("split_panels"):
        try:
            artifacts += _split(original, task, seed, write_prompt_sidecar)
        except RuntimeError as error:
            warnings.append(str(error))
    if storyboard and params.get("draw_grid"):
        try:
            artifacts.append(_overlay(original, params["geometry_spec"]))
        except (OSError, ValueError, KeyError, TypeError) as error:
            warnings.append(f"描线图生成失败：{error}")
    return artifacts, warnings


def publish_artifacts(task_id, task, result, *, job_dir, daily_output_dir, write_prompt_sidecar, send_document,
                      on_archived=None):
    """Publish one finished job. `on_archived` records the files before the slower Telegram step."""
    if task.get("status") in CANCELED:
        return {"published": False, "status": task["status"], "result_file": None, "result_files": [],
                "artifacts": [], "params": _params(task), "warnings": [], "telegram_error": None}
    if _params(task).get("artifacts"):
        return _replay(task)
    source = _source_image(task_id, result, job_dir)
    images, params = archive_pngs(task_id, task, {**result, "paths": [source]}, directory=daily_output_dir(),
                                  write_prompt_sidecar=write_prompt_sidecar, metadata=_metadata(_params(task), result),
                                  suffix=SIDECAR_SUFFIX)
    original = images[0]
    with Image.open(original) as image:
        record = {"role": "original", "file": original.name, "width": image.width, "height": image.height}
    derived, warnings = _derive(original, task, result.get("seed"), write_prompt_sidecar)
    artifacts = [record, *derived]
    names = [item["file"] for item in artifacts if item["role"] != "grid_overlay"]
    params.update(artifacts=artifacts, warnings=warnings, effective=result.get("effective"), seed=result.get("seed"))
    outcome = {"published": True, "status": "succeeded_no_telegram", "result_file": names[0], "result_files": names,
               "artifacts": artifacts, "params": params, "warnings": warnings, "telegram_error": None}
    if on_archived:
        on_archived(outcome)
    if params.get("telegram_enabled"):
        try:
            send_document(original, TELEGRAM_CAPTION)
            outcome["status"] = "succeeded"
        except Exception as error:
            outcome.update(status="telegram_failed", telegram_error=str(error)[:1000])
    return outcome
