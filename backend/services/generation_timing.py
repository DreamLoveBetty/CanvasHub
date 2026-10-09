"""Normalize generation duration metadata for history and image assets."""
from __future__ import annotations

import math
from typing import Any


MAX_DURATION_SECONDS = 7 * 24 * 60 * 60
LOCAL_PHASE_KEYS = (
    "model_load_seconds",
    "inference_seconds",
    "denoise_seconds",
    "save_seconds",
)


def _seconds(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0 or number > MAX_DURATION_SECONDS:
        return None
    return round(number, 3)


def _timestamp(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def normalize_generation_timing(value: Any) -> dict[str, Any]:
    """Return the public, bounded timing contract or an empty mapping."""
    raw = value.get("generation_timing") if isinstance(value, dict) else None
    if not isinstance(raw, dict) and isinstance(value, dict):
        raw = value
    if not isinstance(raw, dict):
        return {}

    total = _seconds(raw.get("total_seconds"))
    local = raw.get("local_inference") is True
    if total is None:
        return {}
    timing: dict[str, Any] = {
        "schema_version": 1,
        "local_inference": local,
        "total_seconds": total,
    }
    if local:
        for key in LOCAL_PHASE_KEYS:
            seconds = _seconds(raw.get(key))
            if seconds is not None:
                timing[key] = seconds
    return timing


def task_total_seconds(task: Any, params: Any = None) -> float | None:
    """Resolve task wall time without inventing phase data for remote providers."""
    if not isinstance(task, dict):
        return None
    task_params = params if isinstance(params, dict) else task.get("params")
    timing = normalize_generation_timing(task_params if isinstance(task_params, dict) else {})
    if timing:
        return timing["total_seconds"]

    for key in ("duration_seconds", "duration"):
        seconds = _seconds(task.get(key))
        if seconds is not None and seconds > 0:
            return seconds

    started = _timestamp(task.get("started_at"))
    finished = _timestamp(task.get("finished_at"))
    if started is None or finished is None or finished < started:
        return None
    return _seconds(finished - started)
