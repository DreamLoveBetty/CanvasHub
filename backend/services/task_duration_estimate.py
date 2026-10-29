"""Expected run time for cloud image tasks, from recent successful runs.

Cloud APIs return the image in one piece and report no intermediate progress, so the
UI can only show an estimate. This module only reads history; it never writes tasks.
"""
from __future__ import annotations

import statistics
import threading
import time

# Task types whose providers report no progress of their own. Local runtimes
# (Qwen, Krea, Topaz, ...) publish real progress and are deliberately excluded.
ESTIMATED_TASK_TYPES = frozenset({'gpt', 'gpt-edit', 'google-gen', 'google-edit'})
IN_FLIGHT_STATUSES = frozenset({'queued', 'preparing', 'processing', 'fallback_running'})
MIN_SAMPLES = 3
CACHE_SECONDS = 120


RESOLUTION_ALIASES = {'hd': '4k', 'standard': '2k', 'normal': '2k'}


def _resolution(params):
    value = str(params.get('requested_resolution') or params.get('resolution') or params.get('quality') or '').lower()
    return RESOLUTION_ALIASES.get(value, value)


def _keys(params):
    """Most specific grouping first; broader groups only when the specific one lacks samples."""
    route = str(params.get('google_provider_route') or '')
    model = str(params.get('model') or '')
    resolution = _resolution(params)
    return ((route, model, resolution), (route, model), (route,), ())


class TaskDurationEstimator:
    def __init__(self, load_durations, *, clock=time.monotonic):
        self.load_durations = load_durations
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = {}

    def _medians(self, task_type):
        now = self.clock()
        with self.lock:
            cached = self.cache.get(task_type)
            if cached and now - cached[0] < CACHE_SECONDS:
                return cached[1]
        groups = {}
        for params, seconds in self.load_durations(task_type):
            for key in _keys(params):
                groups.setdefault(key, []).append(seconds)
        medians = {key: statistics.median(values) for key, values in groups.items() if len(values) >= MIN_SAMPLES}
        with self.lock:
            self.cache[task_type] = (now, medians)
        return medians

    def estimate_seconds(self, task):
        """Median seconds for a matching in-flight cloud task, or None when unknown."""
        task_type = str((task or {}).get('type') or '')
        if task_type not in ESTIMATED_TASK_TYPES or task.get('status') not in IN_FLIGHT_STATUSES:
            return None
        params = task.get('params') if isinstance(task.get('params'), dict) else {}
        try:
            medians = self._medians(task_type)
        except Exception:
            return None  # An estimate must never break status polling.
        for key in _keys(params):
            if key in medians:
                return round(medians[key], 1)
        return None
