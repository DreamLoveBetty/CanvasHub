"""Durable, leased conversion of community MOSS Bases; the numeric work stays in a child process."""
from __future__ import annotations

import atexit
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from ..local_image.runtime import _stop
from ..runtime_resources import local_accelerator
EVENT_PREFIX = "MOSS_CONVERT_EVENT "
from .base_library import clean_name, model_id_for

ACTIVE = {"queued", "waiting", "running"}


class ConversionService:
    def __init__(self, root, component, runtime, library, timeout=3600):
        self.root, self.component, self.runtime, self.library = Path(root), Path(component), runtime, library
        self.timeout = int(timeout)
        self.path = self.root / "model-conversion.json"
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._process, self._thread = None, None
        self._closed = False
        try:
            self._state = json.loads(self.path.read_text())
            if not isinstance(self._state, dict):
                self._state = {}
        except (OSError, ValueError):
            self._state = {}
        if self._state.get("status") in ACTIVE:
            self._update(status="failed", stage="interrupted", message="服务重启，上一轮 MOSS 转换已中断",
                         error="服务重启，上一轮 MOSS 转换已中断", progress=100)
        atexit.register(self.close)

    def _update(self, **values):
        with self._lock:
            self._state.update(values, updated_at=int(time.time()))
            self.root.mkdir(parents=True, exist_ok=True)
            pending = self.path.with_suffix(".json.tmp")
            pending.write_text(json.dumps(self._state, ensure_ascii=False, indent=2) + "\n")
            pending.replace(self.path)

    def status(self):
        with self._lock:
            return dict(self._state or {"status": "idle", "message": ""})

    def inspect(self, body):
        result = self.library.inspect(body.get("source_path"))
        result.pop("source_path", None)
        return result

    def start(self, body):
        inspection = self.library.inspect(body.get("source_path"))
        if not inspection["compatible_candidate"]:
            raise ValueError(inspection["message"])
        name = clean_name(body.get("model_name")) or inspection["suggested_name"]
        if (self.library.directory / model_id_for(name)).exists():
            raise ValueError("同名 Base 已存在，请换一个名称或先删除")
        if self.runtime.python is None:
            raise RuntimeError("请先准备 MOSS 环境")
        self.library.require_space()
        reference = self.library.reference()
        with self._lock:
            if self._closed or self._state.get("status") in ACTIVE:
                raise RuntimeError("已有 MOSS 转换任务或服务已关闭")
            job_id = "moss_convert_" + uuid.uuid4().hex
            self._cancel = threading.Event()
            self._state = {"job_id": job_id, "status": "queued", "stage": "queued", "progress": 1,
                           "source_name": inspection["source_name"], "source_format": inspection["source_format"],
                           "model_name": name, "created_at": int(time.time()), "error": ""}
            self._update(message="MOSS 模型转换已进入本地推理队列")
            spec = {"source": inspection["source_path"], "reference": str(reference), "name": name, "job_id": job_id,
                    "stage": self.library.staging / job_id}
            self._thread = threading.Thread(target=self._run, args=(spec,), name="moss-conversion", daemon=True)
            self._thread.start()
            return self.status()

    def _run(self, spec):
        try:
            with local_accelerator(self.component.parent / ".local-inference.lock", self._cancel,
                                   lambda event: self._update(status="waiting", stage="waiting", progress=2,
                                                              message=event.get("message", "等待本地推理资源"))) as lease:
                if self._cancel.is_set():
                    raise InterruptedError()
                for stale in self.library.staging.iterdir():
                    if stale.is_dir() and not stale.is_symlink():
                        shutil.rmtree(stale)
                self.runtime.release_accelerator_memory()
                self._execute(spec, lease.fileno())
                with self._lock:
                    if self._cancel.is_set():
                        raise InterruptedError()
                    self._update(status="running", stage="publishing", progress=99,
                                 message="校验并注册 MOSS Base 权重")
                model = self.library.publish(spec["stage"], spec["name"])
                self._update(status="succeeded", stage="done", progress=100, model=model,
                             message="MOSS 转换完成，已加入 Base 模型列表", error="")
        except Exception as error:
            canceled = self._cancel.is_set() or isinstance(error, InterruptedError)
            message = "模型转换已取消" if canceled else str(error)[:1600] or "MOSS 转换失败"
            self._update(status="canceled" if canceled else "failed", stage="canceled" if canceled else "failed",
                         progress=100, message=message, error="" if canceled else message)
            shutil.rmtree(spec["stage"], ignore_errors=True)
        finally:
            with self._lock:
                self._process = None

    def _execute(self, spec, lease_fd):
        command = [str(self.runtime.python), "-u", "-m", "backend.moss.base_converter", "--source", spec["source"],
                   "--reference", spec["reference"], "--output", str(spec["stage"])]
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                                   env=self.runtime.child_environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True, pass_fds=(lease_fd,))
        with self._lock:
            self._process = process
        self._update(status="running", stage="converting", message="启动 MOSS 转换", progress=3)
        done, expired = threading.Event(), threading.Event()

        def watch():
            deadline = time.monotonic() + self.timeout
            while not done.wait(.2):
                if self._cancel.is_set() or time.monotonic() >= deadline:
                    if not self._cancel.is_set():
                        expired.set()
                    _stop(process)
                    return

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        result, error = None, ""
        try:
            for line in process.stdout:
                if not line.startswith(EVENT_PREFIX):
                    continue
                try:
                    event = json.loads(line[len(EVENT_PREFIX):])
                except ValueError:
                    continue
                if event.get("event") == "progress":
                    self._update(progress=max(3, min(98, int(event.get("progress") or 3))),
                                 message=str(event.get("stage") or "转换中")[:240])
                elif event.get("event") == "result":
                    result = event
                elif event.get("event") == "error":
                    error = str(event.get("message") or "转换失败")
            code = process.wait()
            if self._cancel.is_set():
                raise InterruptedError()
            if expired.is_set():
                raise RuntimeError("模型转换超过一小时限制")
            if code != 0 or not result:
                raise RuntimeError(error or f"转换进程退出：{code}")
        finally:
            done.set()
            watcher.join(timeout=5)
            process.stdout.close()

    def cancel(self):
        with self._lock:
            if self._state.get("status") in ACTIVE and self._state.get("stage") != "publishing":
                self._cancel.set()
                self._update(message="正在停止 MOSS 转换")
            return self.status()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cancel.set()
            process = self._process
        _stop(process)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
