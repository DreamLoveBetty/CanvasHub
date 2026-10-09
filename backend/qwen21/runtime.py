"""Qwen-specific environment adapter over the neutral worker supervisor."""
from __future__ import annotations

import os
from pathlib import Path
import time

from ..local_image.runtime import JsonLineRuntime, LocalImageCancelled, LocalImageError
from .contracts import ENGINE, REVISION
from .profiles import ADAPTERS
from .environment import (environment_ready, read_receipt, shared_python,
                          source_path, source_ready, turbo_ready)

PREFIX = "QWEN21_EVENT "


class Runtime(JsonLineRuntime):
    def __init__(self, component, timeout=2400, idle_seconds=600, before_load=None):
        super().__init__(component, worker=Path(__file__).with_name("worker.py"),
                         label="Qwen 2.1", prefix=PREFIX, before_load=before_load,
                         timeout=timeout, idle_seconds=idle_seconds)
        self._check_cache = (None, 0.0, False, [])

    @property
    def python(self):
        return shared_python(read_receipt(self.root))

    def child_environment(self):
        project = Path(__file__).resolve().parents[2]
        return {**os.environ,
                "PYTHONPATH": os.pathsep.join((str(source_path(self.root) / "src"), str(project))),
                "HF_HOME": str(self.root / "cache" / "huggingface"),
                "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONUNBUFFERED": "1",
                "MLX_ENABLE_TF32": "0", "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1"}

    def status(self):
        key = str(self.python)
        previous, checked, ready, reasons = self._check_cache
        if previous != key or time.monotonic() - checked > 30:
            ready, reasons = environment_ready(self.python)
            self._check_cache = (key, time.monotonic(), ready, reasons)
        sources = source_ready(self.root)
        with self._lock:
            warm = bool(self._process and self._process.poll() is None)
        return {"engine": ENGINE, "revision": REVISION, "environment_ready": ready,
                "source_ready": sources, "turbo_ready": turbo_ready(self.root),
                "turbo_adapters": {key: turbo_ready(self.root, key) for key in ADAPTERS},
                "warm": warm, "offline_inference": True,
                "reasons": list(reasons) + ([] if sources else ["Qwen 固定版本源码尚未准备"])}
