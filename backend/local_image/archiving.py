"""Original PNG archive helper shared independently of model providers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import time

from ..services.generation_timing import normalize_generation_timing


def archive_pngs(task_id, task, result, *, directory, write_prompt_sidecar, metadata, suffix):
    started = time.monotonic()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    archived = []
    for index, source in enumerate(result["paths"], 1):
        destination = directory / f"{task_id}_{index}.png"
        pending = destination.with_suffix(".png.part")
        shutil.copyfile(source, pending)
        os.replace(pending, destination)
        text = destination.with_suffix(".txt")
        text.write_text(task["prompt"].strip() + "\n", encoding="utf-8")
        write_prompt_sidecar(destination, task["prompt"], txt_path=text)
        archived.append(destination)
    if not archived:
        raise RuntimeError("推理未产生图片")
    timing = normalize_generation_timing(result.get("generation_timing") or {})
    if timing.get("local_inference"):
        extra = max(0, time.monotonic() - started)
        timing["save_seconds"] = round(float(timing.get("save_seconds") or 0) + extra, 3)
        timing["total_seconds"] = round(float(timing.get("total_seconds") or 0) + extra, 3)
    params = dict(task.get("params") or {})
    if timing:
        params.update(generation_timing=timing, duration_seconds=timing["total_seconds"])
    for index, image in enumerate(archived, 1):
        image.with_suffix(suffix).write_text(json.dumps(
            {**metadata, "task_id": task_id, "prompt": task["prompt"], "parameters": params,
             "generation_timing": timing, "output_index": index}, ensure_ascii=False, indent=2) + "\n")
    return archived, params
