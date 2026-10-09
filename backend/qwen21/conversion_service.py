"""Durable, leased Qwen conversion orchestration; no model imports."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from ..local_image.runtime import _stop
from ..runtime_resources import local_accelerator
from .converter_worker import PREFIX
from .contracts import EXPORT_FORMATS
from .model_store import OUTPUT_BYTES, clean_name

ACTIVE = {"queued", "waiting", "running"}


class ConversionService:
    def __init__(self, root, component, runtime, store, timeout=10800):
        self.root, self.component, self.runtime, self.store = Path(root), Path(component), runtime, store
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
            self._update(status="failed", stage="interrupted", message="服务重启，上一轮 Qwen 转换已中断",
                         error="服务重启，上一轮 Qwen 转换已中断", progress=100)
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
        result = self.store.inspect_source((body or {}).get("source_path"))
        result.pop("source_path", None)
        return result

    def start(self, body):
        body = body if isinstance(body, dict) else {}
        precision = str(body.get("precision") or "8bit")
        if precision not in EXPORT_FORMATS:
            raise ValueError("未知 Qwen 输出精度")
        inspection = self.store.inspect_source(body.get("source_path"))
        self.store.paths()
        expected = OUTPUT_BYTES[precision] + 2 * 1024**3
        if shutil.disk_usage(self.store.directory).free < expected:
            raise RuntimeError(f"Qwen Base 目录空间不足，至少需要约 {expected / 1024**3:.1f} GiB")
        # Only small config is needed for conversion; full shared weights are
        # prepared automatically before generation, not before quantization.
        config = self.store.shared / "transformer" / "config.json"
        if not config.is_file():
            raise RuntimeError("请先准备 Qwen 模型配置")
        with self._lock:
            if self._closed or self._state.get("status") in ACTIVE:
                raise RuntimeError("已有 Qwen 转换任务或服务已关闭")
            job_id = "qwen21_convert_" + uuid.uuid4().hex
            stage = self.store.staging / job_id
            stage.mkdir(parents=True, exist_ok=False)
            self._cancel = threading.Event()
            self._state = {"job_id": job_id, "status": "queued", "stage": "queued", "progress": 1,
                           "source_name": inspection["source_name"], "source_format": inspection["source_format"],
                           "model_name": clean_name(body.get("model_name") or inspection["suggested_name"]),
                           "precision": precision, "created_at": int(time.time()), "error": ""}
            self._update(message="Qwen 模型转换已进入本地推理队列")
            spec = {"source": inspection["source_path"], "stage": stage, "config": config,
                    "name": self._state["model_name"], "source_name": inspection["source_name"],
                    "precision": precision, "job_id": job_id}
            self._thread = threading.Thread(target=self._run, args=(spec,), name="qwen21-conversion", daemon=True)
            self._thread.start()
            return self.status()

    def _run(self, spec):
        try:
            with local_accelerator(self.component.parent / ".local-inference.lock", self._cancel,
                                   lambda event: self._update(status="waiting", stage="waiting", progress=2,
                                                              message=event.get("message", "等待本地推理资源"))) as lease:
                if self._cancel.is_set():
                    raise InterruptedError()
                for stale in self.store.staging.iterdir():
                    if stale != spec["stage"] and stale.is_dir() and not stale.is_symlink():
                        shutil.rmtree(stale)
                self.runtime.release_accelerator_memory()
                result = self._execute(spec, lease.fileno())
                with self._lock:
                    if self._cancel.is_set():
                        raise InterruptedError()
                    self._update(status="running", stage="publishing", progress=99, message="注册 Qwen Base 权重")
                model = self.store.publish(spec["stage"], result, name=spec["name"], source_name=spec["source_name"],
                                           precision=spec["precision"])
                self._update(status="succeeded", stage="done", progress=100, model=model,
                             message="Qwen 转换完成，已加入 Base 模型列表", error="")
        except Exception as exc:
            canceled = self._cancel.is_set() or isinstance(exc, InterruptedError)
            message = "模型转换已取消" if canceled else str(exc)[:1600] or "Qwen 转换失败"
            self._update(status="canceled" if canceled else "failed", stage="canceled" if canceled else "failed",
                         progress=100, message=message, error="" if canceled else message)
            shutil.rmtree(spec["stage"], ignore_errors=True)
        finally:
            with self._lock:
                self._process = None

    def _execute(self, spec, lease_fd):
        command = [str(self.runtime.python), "-u", "-m", "backend.qwen21.converter_worker",
                   "--source", spec["source"], "--output", str(spec["stage"]),
                   "--config", str(spec["config"]), "--name", spec["name"], "--precision", spec["precision"]]
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                                   env=self.runtime.child_environment(), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, start_new_session=True,
                                   pass_fds=(lease_fd,))
        with self._lock:
            self._process = process
        self._update(status="running", stage="converting", message="启动 Qwen MLX 转换", progress=3)
        done, expired = threading.Event(), threading.Event()

        def watch():
            deadline = time.monotonic() + self.timeout
            while not done.wait(.2):
                if self._cancel.is_set():
                    _stop(process)
                    return
                if time.monotonic() >= deadline:
                    expired.set()
                    _stop(process)
                    return
        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        result, error = None, ""
        log_dir = self.component / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (log_dir / (spec["job_id"] + ".log")).open("w") as log:
                written = 0
                for line in process.stdout:
                    if written < 8 * 1024**2:
                        log.write(line)
                        written += len(line.encode())
                    if not line.startswith(PREFIX):
                        continue
                    try:
                        event = json.loads(line[len(PREFIX):])
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
                raise RuntimeError("模型转换超过三小时限制")
            if code != 0 or not result:
                raise RuntimeError(error or f"转换进程退出：{code}")
            return result
        finally:
            done.set()
            watcher.join(timeout=5)
            process.stdout.close()

    def cancel(self):
        with self._lock:
            if self._state.get("status") in ACTIVE and self._state.get("stage") != "publishing":
                self._cancel.set()
                self._update(message="正在停止 Qwen 转换")
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
            self._thread.join(timeout=8)
