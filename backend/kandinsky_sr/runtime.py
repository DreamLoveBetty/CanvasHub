"""Supervised one-shot worker runtime for Kandinsky ImageSR 2.0 under the shared local-inference lease."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable, Dict, Optional
import uuid

from ..local_image.runtime import _stop
from ..runtime_resources import local_accelerator
from . import environment
from .contracts import EVENT_PREFIX, MODEL_ID, TIMEOUT_SECONDS, normalize_options

WORKER = Path(__file__).with_name("worker.py")
LOG_LIMIT = 4 * 1024 * 1024


class KandinskySrError(RuntimeError):
    """Raised when Kandinsky ImageSR execution fails or environment is unready."""


class KandinskySrCancelled(KandinskySrError):
    """Raised when a Kandinsky ImageSR task is cancelled."""


@dataclass(frozen=True)
class Result:
    input_width: int
    input_height: int
    output_width: int
    output_height: int
    scale: int
    model: str
    device: str


class _CancelPort:
    def __init__(self, callback: Callable[[], bool]):
        self._callback = callback

    def is_set(self) -> bool:
        return bool(self._callback())

    def wait(self, timeout: float) -> bool:
        time.sleep(timeout)
        return self.is_set()


class Runtime:
    def __init__(
        self,
        component: str | Path,
        *,
        timeout: int = TIMEOUT_SECONDS,
        before_load: Optional[Callable[[], None]] = None,
        popen=subprocess.Popen,
        worker: Path = WORKER,
        status_reader=environment.status,
    ):
        self.root = Path(component).expanduser().resolve()
        self.timeout = int(timeout)
        self.before_load = before_load
        self._popen = popen
        self._worker = Path(worker)
        self._status_reader = status_reader

    @property
    def python(self) -> Optional[Path]:
        value = environment.read_receipt(self.root).get("python")
        return Path(value) if isinstance(value, str) and Path(value).is_absolute() else None

    def model_dir(self) -> Path:
        return environment.resolve_model_dir(self.root)

    def status(self) -> Dict[str, Any]:
        return self._status_reader(self.root)

    def child_environment(self) -> Dict[str, str]:
        project = Path(__file__).resolve().parents[2]
        pkg_root = environment.python_package_root(self.root)
        pythonpath = os.pathsep.join([str(pkg_root), str(project)])
        env = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER")
        }
        env.update(
            {
                "PYTHONPATH": pythonpath,
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
                "HF_HOME": str(self.root / "cache"),
                "TOKENIZERS_PARALLELISM": "false",
                "PYTHONUNBUFFERED": "1",
                "CANVASHUB_IMAGE_PARENT_PID": str(os.getpid()),
            }
        )
        return env

    def execute(
        self,
        source: str | Path,
        output: str | Path,
        *,
        options: Optional[Dict[str, Any]] = None,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Optional[Callable[[float, str], None]] = None,
    ) -> Result:
        clean_options = normalize_options(options)
        readiness = self.status()
        if not readiness.get("ready"):
            reasons = readiness.get("reasons") or []
            detail = reasons[0] if reasons else "Kandinsky SR 环境或模型尚未准备"
            raise KandinskySrError(f"{detail}，请先在设置中心 → 模型工具中准备")

        python = self.python
        if python is None or not python.is_file():
            raise KandinskySrError("Kandinsky SR 隔离环境丢失，请重新准备")
        model_dir = self.model_dir()
        if not model_dir.is_dir():
            raise KandinskySrError("Kandinsky SR 模型目录不存在，请先在设置中心准备")

        progress_cb = progress or (lambda _ratio, _text: None)
        port = _CancelPort(cancelled)

        def waiting(_event: Dict[str, Any]) -> None:
            progress_cb(0.02, "等待本地推理资源...")

        with local_accelerator(self.root.parent / ".local-inference.lock", port, waiting) as lease:
            if cancelled():
                raise KandinskySrCancelled("任务已取消")
            if self.before_load:
                self.before_load()
            return self._run(
                python,
                model_dir,
                Path(source),
                Path(output),
                clean_options,
                cancelled,
                progress_cb,
                lease.fileno(),
            )

    def _run(
        self,
        python: Path,
        model_dir: Path,
        source: Path,
        output: Path,
        options: Dict[str, Any],
        cancelled: Callable[[], bool],
        progress: Callable[[float, str], None],
        lease_fd: int,
    ) -> Result:
        work = self.root / "jobs" / uuid.uuid4().hex
        work.mkdir(parents=True, exist_ok=True)
        request_file = work / "request.json"
        request_file.write_text(
            json.dumps(
                {
                    "input_path": str(source),
                    "output_path": str(output),
                    "model_dir": str(model_dir),
                    "model": MODEL_ID,
                    "upscale_factor": int(options["upscale_factor"]),
                    "creativity": int(options["creativity"]),
                    "overlap": float(options["overlap"]),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        progress(0.08, "正在启动 Kandinsky SR 推理进程...")
        process = self._popen(
            [str(python), "-u", str(self._worker), str(request_file)],
            cwd=str(self.root),
            env=self.child_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            pass_fds=(lease_fd,),
        )

        done = threading.Event()
        expired = threading.Event()

        def monitor() -> None:
            deadline = time.monotonic() + self.timeout
            while not done.wait(0.2):
                if cancelled() or time.monotonic() >= deadline:
                    if not cancelled():
                        expired.set()
                    _stop(process)
                    return

        watcher = threading.Thread(target=monitor, name="ksr-watchdog", daemon=True)
        watcher.start()

        result_payload: Optional[Dict[str, Any]] = None
        error_msg = ""
        tail: list[str] = []
        last_percent = -1

        try:
            with (work / "runtime.log").open("wb") as log:
                written = 0
                assert process.stdout is not None
                for raw in iter(process.stdout.readline, b""):
                    if written < LOG_LIMIT:
                        log.write(raw)
                        written += len(raw)
                    line = raw.decode("utf-8", "replace").strip()
                    if line:
                        tail = (tail + [line])[-10:]
                    _, found, payload = line.partition(EVENT_PREFIX)
                    if not found:
                        continue
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    kind = event.get("event")
                    if kind == "progress" and not cancelled():
                        percent = max(0, min(95, int(event.get("percent") or 0)))
                        if percent >= last_percent:
                            last_percent = percent
                            progress(percent / 100.0, str(event.get("stage") or f"超分处理 {percent}%"))
                    elif kind == "result":
                        result_payload = event
                    elif kind == "error":
                        error_msg = str(event.get("message") or "")
            code = process.wait()
        finally:
            done.set()
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                _stop(process)
            watcher.join(timeout=5)
            request_file.unlink(missing_ok=True)

        if cancelled():
            raise KandinskySrCancelled("任务已取消")
        if expired.is_set():
            raise KandinskySrError(f"Kandinsky SR 处理超过 {self.timeout} 秒，已停止")
        if code != 0 or not result_payload or not output.is_file():
            fallback = next((line for line in reversed(tail) if not line.startswith(EVENT_PREFIX)), "")
            raise KandinskySrError(error_msg or fallback or f"Kandinsky SR 进程异常退出（退出码 {code}）")

        return Result(
            input_width=int(result_payload["input_width"]),
            input_height=int(result_payload["input_height"]),
            output_width=int(result_payload["output_width"]),
            output_height=int(result_payload["output_height"]),
            scale=int(result_payload["scale"]),
            model=str(result_payload["model"]),
            device=str(result_payload["device"]),
        )
