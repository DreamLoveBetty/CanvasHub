"""One-shot WeMM-Video MLX subprocess under the shared local-inference lease.

The HTTP process never imports MLX, transformers, or OpenCV. Each job starts
worker.py inside the isolated Python 3.12 venv and releases all model memory
immediately on exit.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from ..local_image.runtime import _stop
from ..runtime_resources import local_accelerator
from . import environment
from .contracts import EVENT_PREFIX, MODEL_LABEL, TIMEOUT_SECONDS

WORKER = Path(__file__).with_name("worker.py")
LOG_LIMIT = 4 * 1024 * 1024


class Runtime:
    def __init__(
        self,
        component: str | Path,
        *,
        before_load: Optional[Callable[[], None]] = None,
        popen=subprocess.Popen,
        worker: Path = WORKER,
    ):
        self.root = Path(component).absolute()
        self.before_load = before_load
        self._popen = popen
        self._worker = Path(worker)

    @property
    def python(self) -> Optional[Path]:
        value = environment.read_receipt(self.root).get("python")
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None

    def model_dir(self) -> Path:
        return environment.resolve_model_dir(self.root)

    def model_variant(self) -> str:
        return str(environment.read_receipt(self.root).get("model_variant") or MODEL_LABEL)

    def fingerprint(self) -> str:
        model_path = self.model_dir()
        if not model_path.is_dir():
            return "missing"
        return environment.model_fingerprint(model_path)

    @staticmethod
    def worker_path() -> str:
        return os.pathsep.join([os.environ.get("PATH", ""), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"])

    def child_environment(self) -> Dict[str, str]:
        project = Path(__file__).resolve().parents[2]
        src_root = environment.src_dir(self.root)
        pythonpath = os.pathsep.join([str(project), str(src_root)])
        return {
            **os.environ,
            "PATH": self.worker_path(),
            "PYTHONPATH": pythonpath,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
            "HF_HOME": str(self.root / "cache"),
            "TOKENIZERS_PARALLELISM": "false",
            "PYTHONUNBUFFERED": "1",
            "CANVASHUB_IMAGE_PARENT_PID": str(os.getpid()),
        }

    def execute(
        self,
        spec: Dict[str, Any],
        job_dir: Path,
        video_path: Path,
        cancelled: threading.Event,
        progress: Callable[[Dict[str, Any]], None],
    ) -> Tuple[str, str]:
        python = self.python
        if python is None or not python.is_file():
            return "failed", "视频理解隔离环境尚未准备，请先在设置中心准备"
        model_dir = self.model_dir()
        if not model_dir.is_dir():
            return "failed", "视频理解模型尚未准备，请先在设置中心准备"

        def waiting(event: Dict[str, Any]) -> None:
            progress({"stage": str(event.get("stage") or "等待本地推理资源"), "message": str(event.get("message") or ""), "ratio": 0.0})

        with local_accelerator(self.root.parent / ".local-inference.lock", cancelled, waiting) as lease:
            if cancelled.is_set():
                return "cancelled", ""
            if self.before_load:
                self.before_load()
            return self._run(python, model_dir, spec, job_dir, video_path, cancelled, progress, lease.fileno())

    def _run(
        self,
        python: Path,
        model_dir: Path,
        spec: Dict[str, Any],
        job_dir: Path,
        video_path: Path,
        cancelled: threading.Event,
        progress: Callable[[Dict[str, Any]], None],
        lease_fd: int,
    ) -> Tuple[str, str]:
        job_dir = Path(job_dir)
        result_dir = job_dir / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        request_file = job_dir / "request.json"
        request_payload = {
            **spec,
            "video_path": str(video_path),
            "model_dir": str(model_dir),
            "model_variant": self.model_variant(),
        }
        request_file.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        log_dir = self.root / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)

        process = self._popen(
            [str(python), "-u", str(self._worker), str(request_file), str(result_dir)],
            cwd=self.root,
            env=self.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(lease_fd,),
        )
        done = threading.Event()
        expired = threading.Event()

        def watch() -> None:
            deadline = time.monotonic() + TIMEOUT_SECONDS
            while not done.wait(0.2):
                if cancelled.is_set() or time.monotonic() >= deadline:
                    if not cancelled.is_set():
                        expired.set()
                    _stop(process)
                    return

        watcher = threading.Thread(target=watch, name="video-understand-watchdog", daemon=True)
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
                    tail = (tail + [line])[-10:]
                    _, found, payload = line.partition(EVENT_PREFIX)
                    if not found:
                        continue
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("event") in ("progress", "done"):
                        progress(event)
            code = process.wait()
        finally:
            done.set()
            process.stdout.close()
            if process.poll() is None:
                _stop(process)
            watcher.join(timeout=5)

        if cancelled.is_set():
            return "cancelled", ""
        if expired.is_set():
            return "failed", f"视频理解超过 {TIMEOUT_SECONDS} 秒，已停止"
        if code != 0 or not (result_dir / "result.json").is_file() or not (result_dir / "output.md").is_file():
            detail = next((line for line in reversed(tail) if line and not line.startswith(EVENT_PREFIX)), "")
            return "failed", (detail[:500] or f"视频理解进程异常退出（退出码 {code}）")
        return "succeeded", ""
