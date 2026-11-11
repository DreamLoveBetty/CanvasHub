"""One-shot ASR subprocess under the shared local-inference lease. The HTTP process never imports torch.

Each call starts worker.py in the isolated venv and waits for it to exit, so the model's memory is
returned to the system as soon as a transcription ends. Before loading, resident local models are
asked to unload (`before_load`); the lease descriptor is passed to the child, so an abruptly killed
server still keeps other GPU work out until the child is gone, and the child exits on its own when
its parent dies (parent_watch). Cancel and timeout kill the whole process group.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from ..local_image.runtime import _stop
from ..runtime_resources import local_accelerator
from . import environment
from .contracts import EVENT_PREFIX, MAX_AUDIO_SECONDS, is_filler, max_new_tokens, timeout_seconds

WORKER = Path(__file__).with_name("worker.py")
LOG_LIMIT = 4 * 1024 * 1024


class AsrError(RuntimeError):
    pass


class AsrCancelled(AsrError):
    pass


class Runtime:
    def __init__(self, component, *, before_load=None, popen=subprocess.Popen):
        self.root = Path(component).absolute()  # the worker runs with cwd=root; model paths must not be relative
        self.before_load = before_load
        self._popen = popen

    @property
    def python(self):
        value = environment.read_receipt(self.root).get("python")
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None

    def child_environment(self):
        project = Path(__file__).resolve().parents[2]
        return {**os.environ, "PYTHONPATH": str(project), "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "HF_HOME": str(self.root / "cache"),
                "TOKENIZERS_PARALLELISM": "false", "PYTORCH_ENABLE_MPS_FALLBACK": "1", "PYTHONUNBUFFERED": "1",
                "CANVASHUB_IMAGE_PARENT_PID": str(os.getpid())}

    def transcribe(self, audio, *, seconds, script, cancelled, progress):
        """{language, text, tokens, speech} for a 16 kHz mono WAV of `seconds` (at most 180).

        progress(ratio, stage). Raises AsrCancelled when `cancelled` is set, AsrError otherwise."""
        if seconds > MAX_AUDIO_SECONDS + 1e-6:
            raise AsrError(f"语音识别一次最多 {MAX_AUDIO_SECONDS} 秒")
        python = self.python
        if python is None or not python.is_file():
            raise AsrError("语音识别环境尚未准备，请先在设置中心准备")

        def waiting(event):
            progress(0.0, str(event.get("stage") or "等待本地推理资源"))

        with local_accelerator(self.root.parent / ".local-inference.lock", cancelled, waiting) as lease:
            if cancelled.is_set():
                raise AsrCancelled("已取消")
            if self.before_load:
                self.before_load()
            result = self._run(python, audio, seconds, script, cancelled, progress, lease.fileno())
        return {**result, "speech": not is_filler(result.get("text", ""))}

    def _run(self, python, audio, seconds, script, cancelled, progress, lease_fd):
        log_dir = self.root / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="asr-") as scratch:
            request, result = Path(scratch) / "request.json", Path(scratch) / "result.json"
            request.write_text(json.dumps({
                "audio": str(audio), "model": str(environment.model_dir("asr", self.root)),
                "aligner": str(environment.model_dir("aligner", self.root)),
                "max_new_tokens": max_new_tokens(seconds), "script": script}, ensure_ascii=False), encoding="utf-8")
            process = self._popen([str(python), "-u", str(WORKER), str(request), str(result)], cwd=self.root,
                                  env=self.child_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(lease_fd,))
            done, expired = threading.Event(), threading.Event()
            limit = timeout_seconds(seconds)

            def watch():
                deadline = time.monotonic() + limit
                while not done.wait(0.2):
                    if cancelled.is_set() or time.monotonic() >= deadline:
                        if not cancelled.is_set():
                            expired.set()
                        _stop(process)
                        return

            watcher = threading.Thread(target=watch, name="asr-watchdog", daemon=True)
            watcher.start()
            tail = []
            try:
                with (log_dir / "last-run.log").open("wb") as log:
                    written = 0
                    for raw in iter(process.stdout.readline, b""):
                        if written < LOG_LIMIT:
                            log.write(raw)
                            written += len(raw)
                        line = raw.decode("utf-8", "replace").strip()
                        tail = (tail + [line])[-8:]
                        _, found, payload = line.partition(EVENT_PREFIX)
                        if not found:
                            continue
                        try:
                            event = json.loads(payload)
                        except ValueError:
                            continue
                        if event.get("event") == "progress":
                            progress(float(event.get("ratio") or 0), str(event.get("stage") or "语音识别中"))
                code = process.wait()
            finally:
                done.set()
                process.stdout.close()
                if process.poll() is None:
                    _stop(process)
                watcher.join(timeout=5)
            if cancelled.is_set():
                raise AsrCancelled("已取消")
            if expired.is_set():
                raise AsrError(f"语音识别超过 {limit} 秒，已停止")
            if code != 0 or not result.is_file():
                detail = next((line for line in reversed(tail) if line and not line.startswith(EVENT_PREFIX)), "")
                raise AsrError(f"语音识别失败：{detail[:300] or f'退出码 {code}'}")
            try:
                data = json.loads(result.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise AsrError("语音识别结果无法读取") from error
        tokens = [{"start": float(item["start"]), "end": float(item["end"]), "text": str(item["text"])}
                  for item in data.get("tokens") or [] if isinstance(item, dict)]
        return {"language": str(data.get("language") or ""), "text": str(data.get("text") or ""), "tokens": tokens}
