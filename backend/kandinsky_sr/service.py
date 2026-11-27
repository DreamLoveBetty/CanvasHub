"""Kandinsky ImageSR 2.0 service: preparation lifecycle and EnhancementEngine adapter."""
from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional

from ..local_image.preparation import Preparation
from ..services.image_enhancement import EnhancementEngine
from . import environment
from .contracts import (
    ENGINE,
    MODEL_ID,
    MODEL_LABEL,
    PREPARE_PREFIX,
    catalog_entry,
    normalize_model,
    normalize_options,
)
from .runtime import Runtime

STATUS_TTL = 30


class Service:
    def __init__(
        self,
        component: str | Path,
        *,
        runtime: Optional[Runtime] = None,
        preparation: Optional[Preparation] = None,
        status_reader=environment.status,
    ):
        self.component = Path(component)
        self.runtime = runtime or Runtime(self.component, status_reader=status_reader)
        self.preparation = preparation or Preparation(self.component, PREPARE_PREFIX, "Kandinsky SR 2.0")
        self._status_reader = status_reader
        self._lock = threading.RLock()
        self._status_cache = (0.0, None, None)

    def status(self) -> Dict[str, Any]:
        operation = self.preparation.status()
        key = (operation.get("status"), operation.get("stage"))
        with self._lock:
            checked, seen, cached = self._status_cache
            if cached is None or seen != key or (time.monotonic() - checked) > STATUS_TTL:
                cached = self._status_reader(self.component)
                self._status_cache = (time.monotonic(), key, cached)
        ready = bool(cached.get("ready")) and operation.get("status") != "running"
        return {
            "ok": True,
            "engine": ENGINE,
            **cached,
            "ready": ready,
            "preparation": operation,
            "models": [catalog_entry(ready, cached.get("reasons"))],
        }

    def prepare(self, _body: Any = None) -> Dict[str, Any]:
        python = environment.launcher_python()
        if python is None:
            raise RuntimeError("未找到可运行准备程序的 Python")
        command = [str(python), "-u", "-m", "backend.kandinsky_sr.environment", "prepare"]
        return self.preparation.start(command, Path(__file__).resolve().parents[2], {"operation": "prepare"})

    def engine(self, params: Dict[str, Any]) -> EnhancementEngine:
        options = normalize_options((params or {}).get("kandinsky_sr"))
        models = {
            MODEL_ID: {
                "id": MODEL_ID,
                "label": MODEL_LABEL,
                "route": "kandinsky_sr_local",
                "scale": options["upscale_factor"],
            }
        }

        def execute(source, output, *, model_name, cancelled, progress, **unused):
            del model_name, unused
            return self.runtime.execute(
                source,
                output,
                options=options,
                cancelled=cancelled,
                progress=progress,
            )

        return EnhancementEngine(
            task_type="kandinsky_sr",
            provider="kandinsky_sr",
            models=models,
            normalize_model=normalize_model,
            execute=execute,
            output_format="png",
            parameter_key="kandinsky_sr",
            display_name="Kandinsky SR 2.0 超分",
        )
