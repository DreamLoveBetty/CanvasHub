"""Supervisor for the persistent Krea 2 MLX child process.

The web server never imports MLX.  One worker is reused across sequential Krea
jobs, while the existing cross-domain accelerator lease prevents concurrent
local audio/video/image inference.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

from .contracts import BUILDS, REVISION
from .environment import (base_ready, build_ready, environment_ready, model_paths,
                          read_receipt, safety_ready, shared_python, source_ready)
from ..runtime_resources import local_accelerator


PREFIX = "KREA2_EVENT "


class Krea2Error(RuntimeError):
    pass


class Krea2Cancelled(Krea2Error):
    pass


from ..local_image.runtime import JsonLineRuntime


class Runtime(JsonLineRuntime):
    def __init__(self, component, timeout=1800, idle_seconds=600, before_load=None):
        super().__init__(component, worker=Path(__file__).with_name("worker.py"),
                         label="Krea 2", prefix=PREFIX, error=Krea2Error,
                         cancelled_error=Krea2Cancelled, before_load=before_load,
                         timeout=timeout, idle_seconds=idle_seconds)
        self._environment_cache = (None, 0.0, False, [])

    @property
    def python(self):
        return shared_python(read_receipt(self.root))


    def status(self):
        receipt = read_receipt(self.root)
        python = self.python
        key = (str(python), json.dumps(receipt, sort_keys=True))
        previous, checked, env_ready, env_reasons = self._environment_cache
        if previous != key or time.monotonic() - checked > 30:
            env_ready, env_reasons = environment_ready(python)
            self._environment_cache = (key, time.monotonic(), env_ready, env_reasons)
        sources = source_ready(self.root)
        base = base_ready(self.root)
        safety = safety_ready(self.root)
        builds = {name: build_ready(self.root, name) for name in BUILDS}
        reasons = list(env_reasons)
        if not sources:
            reasons.append("Krea 2 固定版本源码尚未准备")
        if not base:
            reasons.append("Krea 2 基础 VAE / 文本编码器尚未下载")
        if not any(builds.values()):
            reasons.append("Krea 2 量化 Transformer 尚未下载")
        try:
            from huggingface_hub import get_token
            authenticated = bool((get_token() or "").strip())
        except Exception:
            authenticated = False
        with self._lock:
            process = self._process
            warm = bool(process and process.poll() is None)
        return {
            "engine": "krea2-alis-mlx",
            "revision": REVISION,
            "shared_python": str(python) if python else "",
            "environment_ready": env_ready,
            "source_ready": sources,
            "base_ready": base,
            "safety_ready": safety,
            "builds": {name: {"ready": ready, "path": str(model_paths(self.root)[name])}
                       for name, ready in builds.items()},
            "ready": env_ready and sources and base and any(builds.values()),
            "warm": warm,
            "offline_inference": True,
            "huggingface_authenticated": authenticated,
            "reasons": reasons,
            "install_command": ".venv/bin/python -m backend.krea2.install --models 8bit",
        }


    def _environment(self):
        krea = self.root / "source" / "krea2"
        mflux = self.root / "source" / "mflux"
        existing = os.environ.get("PYTHONPATH", "")
        return {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(filter(None, (str(krea), str(mflux), existing))),
            "HF_HOME": str(self.root / "cache" / "huggingface"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
            "MLX_ENABLE_TF32": "0",
            "AGX_RELAX_CDM_CTXSTORE_TIMEOUT": "1",
        }


    def child_environment(self):
        """Environment shared by the inference and offline conversion children."""
        return self._environment()


