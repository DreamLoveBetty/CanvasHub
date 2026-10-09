"""Persistent JSON-lines child supervision, with explicit accelerator hooks."""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from ..runtime_resources import local_accelerator

class LocalImageError(RuntimeError): pass
class LocalImageCancelled(LocalImageError): pass

def _stop(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


class JsonLineRuntime:
    def __init__(self, component, *, worker, label, prefix, error=LocalImageError,
                 cancelled_error=LocalImageCancelled, before_load=None,
                 timeout=1800, idle_seconds=600):
        self.root = Path(component).expanduser().resolve()
        self.worker_path = Path(worker).resolve()
        self.label, self.prefix = label, prefix
        self.error, self.cancelled_error = error, cancelled_error
        self.before_load = before_load
        self.timeout, self.idle_seconds = int(timeout), int(idle_seconds)
        self._process = None
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._last_used = 0.0
        self._idle_timer = None

    def release_accelerator_memory(self):
        """Only call while holding the shared lease; never terminate active jobs."""
        if self.before_load:
            self.before_load()
        self.close()

    def _start(self):
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._process is not None and self._process.poll() is None:
                return self._process
            python = self.python
            if python is None or not python.is_file():
                raise self.error("未找到画布共享 Python 环境")
            log = self.root / "runtime"
            log.mkdir(parents=True, exist_ok=True)
            command = [str(python), "-u", str(self.worker_path), str(self.root)]
            self._process = subprocess.Popen(
                command, cwd=self.root,
                env={**self.child_environment(), "CANVASHUB_IMAGE_PARENT_PID": str(os.getpid())}, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,
            )
            self._last_used = time.monotonic()
            return self._process


    def _schedule_idle_stop(self):
        with self._lock:
            if self._idle_timer:
                self._idle_timer.cancel()
            generation = self._last_used

            def stop_if_idle():
                with self._lock:
                    if generation == self._last_used and time.monotonic() - self._last_used >= self.idle_seconds:
                        self._close_locked()

            self._idle_timer = threading.Timer(self.idle_seconds + 0.1, stop_if_idle)
            self._idle_timer.daemon = True
            self._idle_timer.start()


    def _close_locked(self):
        timer, self._idle_timer = self._idle_timer, None
        if timer and timer is not threading.current_thread():
            timer.cancel()
        process, self._process = self._process, None
        if process and process.poll() is None:
            try:
                process.stdin.write(json.dumps({"command": "shutdown"}) + "\n")
                process.stdin.flush()
                process.wait(timeout=4)
            except Exception:
                _stop(process)
        for stream in (getattr(process, "stdin", None), getattr(process, "stdout", None)):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


    def close(self):
        with self._lock:
            self._close_locked()

    def close_idle(self):
        """Non-blocking operator unload, without terminating another active job."""
        if not self._request_lock.acquire(blocking=False):
            raise self.error(f"{self.label} 正在推理，请完成后再管理模型")
        try:
            self.close()
        finally:
            self._request_lock.release()


    def _drop(self, process):
        _stop(process)
        with self._lock:
            if self._process is process:
                self._process = None
        for stream in (process.stdin, process.stdout):
            try:
                if stream:
                    stream.close()
            except OSError:
                pass


    def execute(self, spec, directory, cancelled, progress):
        directory = Path(directory).resolve()
        cancel_file = directory / "cancel"
        cancel_file.unlink(missing_ok=True)

        def resource_progress(event):
            progress(0.0, str(event.get("stage") or event.get("message") or "等待本地推理资源"))

        with local_accelerator(self.root.parent / ".local-inference.lock", cancelled, resource_progress):
            if cancelled.is_set():
                raise self.cancelled_error("任务已取消")
            if self.before_load:
                self.before_load()
            with self._request_lock:
                return self._execute(spec, directory, cancel_file, cancelled, progress)


    def _execute(self, spec, directory, cancel_file, cancelled, progress):
        process = self._start()
        payload = {"command": "generate", "job_id": directory.name, "job_dir": str(directory),
                   "cancel_file": str(cancel_file), "spec": spec}
        try:
            process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._drop(process)
            raise self.error(f"{self.label} worker 启动失败") from exc

        done = threading.Event()
        expired = threading.Event()

        def watch():
            deadline = time.monotonic() + self.timeout
            while not done.wait(0.2):
                if cancelled.is_set():
                    cancel_file.touch(exist_ok=True)
                    # During model load there is no callback; stop promptly.
                    if not done.wait(4):
                        self._drop(process)
                    return
                if time.monotonic() >= deadline:
                    expired.set()
                    cancel_file.touch(exist_ok=True)
                    self._drop(process)
                    return

        watcher = threading.Thread(target=watch, name=f"{self.label}-watchdog", daemon=True)
        watcher.start()
        result = None
        error = ""
        log_path = directory / "runtime.log"
        try:
            with log_path.open("a", encoding="utf-8") as log:
                written = log_path.stat().st_size
                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    if written < 8 * 1024 * 1024:
                        log.write(line)
                        log.flush()
                        written += len(line.encode("utf-8", "replace"))
                    # tqdm writes carriage-return updates without newlines to
                    # merged stderr. A valid event can follow that text on the
                    # same read; ignoring it would freeze the canvas progress.
                    _, found, payload_text = line.partition(self.prefix)
                    if not found:
                        continue
                    try:
                        event = json.loads(payload_text.strip())
                    except ValueError:
                        continue
                    kind = event.get("event")
                    if kind == "progress":
                        progress(float(event.get("ratio") or 0), str(event.get("stage") or f"{self.label} 推理中"))
                    elif kind == "result" and event.get("job_id") == directory.name:
                        result = event
                        break
                    elif kind == "cancelled" and event.get("job_id") == directory.name:
                        raise self.cancelled_error(str(event.get("message") or "任务已取消"))
                    elif kind == "error" and event.get("job_id") == directory.name:
                        error = str(event.get("message") or f"{self.label} 推理失败")
                        break
            if cancelled.is_set():
                raise self.cancelled_error("任务已取消")
            if expired.is_set():
                raise self.error(f"{self.label} 推理超过时限，worker 已终止")
            if process.poll() is not None:
                raise self.error(error or f"{self.label} worker 异常退出：{process.returncode}")
            if result is None:
                raise self.error(error or f"{self.label} worker 未返回结果")
            paths = [Path(value).resolve() for value in result.get("paths") or []]
            if not paths or any(not path.is_file() or not path.is_relative_to(directory) for path in paths):
                raise self.error(f"{self.label} worker 返回的结果文件无效")
            return {**result, "paths": paths}
        finally:
            done.set()
            watcher.join(timeout=5)
            cancel_file.unlink(missing_ok=True)
            with self._lock:
                if self._process is process and process.poll() is None:
                    self._last_used = time.monotonic()
                    self._schedule_idle_stop()
                elif self._process is process:
                    self._process = None
