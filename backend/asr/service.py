"""ASR domain service: environment status, the user-triggered prepare operation, and the
`transcribe` port other domains call (video_edit's automatic subtitles)."""
from __future__ import annotations

from pathlib import Path
import threading
import time

from ..local_image.preparation import Preparation
from . import environment
from .contracts import ENGINE, MAX_AUDIO_SECONDS, SCRIPTS
from .runtime import Runtime

STATUS_TTL = 30


class AsrService:
    def __init__(self, component, *, runtime=None, preparation=None, status_reader=environment.status):
        self.component = Path(component)
        self.runtime = runtime or Runtime(self.component)
        self.preparation = preparation or Preparation(self.component, environment.PREFIX, "语音识别")
        self._status_reader = status_reader
        self._lock = threading.Lock()
        self._cache = (0.0, None, None)  # (checked, preparation key, status)

    def status(self):
        operation = self.preparation.status()
        key = (operation.get("status"), operation.get("stage"))
        with self._lock:
            checked, seen, cached = self._cache
            # A finished prepare must not wait out the cache.
            if cached is None or seen != key or time.monotonic() - checked > STATUS_TTL:
                cached = self._status_reader(self.component)
                self._cache = (time.monotonic(), key, cached)
        ready = bool(cached["ready"]) and operation.get("status") != "running"
        return {"ok": True, "engine": ENGINE, **cached, "ready": ready, "preparation": operation,
                "max_seconds": MAX_AUDIO_SECONDS, "scripts": list(SCRIPTS)}

    def prepare(self, _body=None):
        python = environment.launcher_python()
        if python is None:
            raise RuntimeError("未找到可运行准备程序的 Python")
        command = [str(python), "-u", "-m", "backend.asr.environment", "prepare"]
        return self.preparation.start(command, Path(__file__).resolve().parents[2], {"operation": "prepare"})

    def transcribe(self, audio, *, seconds, script, cancelled, progress):
        if self.preparation.status().get("status") == "running":
            raise RuntimeError("语音识别环境正在准备，请完成后再试")
        return self.runtime.transcribe(audio, seconds=seconds, script=script, cancelled=cancelled, progress=progress)

    def close(self):
        self.preparation.close()
