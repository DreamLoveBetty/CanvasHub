"""Bounded serial queue using explicit task-store and result-publication ports."""
from __future__ import annotations

from pathlib import Path
import queue
import threading

from .runtime import LocalImageCancelled


class CancelPort:
    def __init__(self, event, task_id, get_task):
        self.event, self.task_id, self.get_task = event, task_id, get_task

    def is_set(self):
        return self.event.is_set() or (self.get_task(self.task_id) or {}).get("status") in {"canceled", "cancelled"}

    def wait(self, timeout):
        self.event.wait(timeout)
        return self.is_set()


class ImageTaskQueue:
    def __init__(self, root, runtime, *, get_task, update_task, update_task_status,
                 publish, label, terminal, capacity=8):
        self.root, self.runtime = Path(root), runtime
        self.get_task, self.update_task, self.update_task_status = get_task, update_task, update_task_status
        self.publish, self.label, self.terminal = publish, label, frozenset(terminal)
        self._queue = queue.Queue(maxsize=capacity)
        self._lock = threading.RLock()
        self._events = {}
        self._thread = None
        self._closed = False

    def enqueue(self, task_id, spec, create):
        with self._lock:
            if self._closed or self._queue.full():
                raise RuntimeError(f"{self.label} 队列繁忙，请稍后重试")
            create()
            self._events[task_id] = threading.Event()
            self._queue.put_nowait((task_id, spec))
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._work, name=f"{self.label}-queue", daemon=True)
                self._thread.start()

    def cancel(self, task_id):
        with self._lock:
            if task_id in self._events:
                self._events[task_id].set()
        task = self.get_task(task_id) or {}
        if task and task.get("status") not in self.terminal:
            self.update_task(task_id, "canceled", stage="canceled", progress=100,
                             progress_text="任务已取消", error="")

    def _work(self):
        while not self._closed:
            try:
                task_id, spec = self._queue.get(timeout=.5)
            except queue.Empty:
                continue
            with self._lock:
                event = self._events.get(task_id) or threading.Event()
            cancel = CancelPort(event, task_id, self.get_task)
            try:
                if cancel.is_set():
                    continue
                self.update_task_status(task_id, "processing", f"等待 {self.label} 本地推理资源",
                                        stage="waiting", progress=1)

                def progress(ratio, text):
                    if not cancel.is_set():
                        self.update_task_status(task_id, "processing", str(text)[:240], stage="generating",
                                                progress=max(1, min(95, int(float(ratio) * 100))))
                result = self.runtime.execute(spec, self.root / "jobs" / task_id, cancel, progress)
                if cancel.is_set():
                    raise LocalImageCancelled("任务已取消")
                self.publish(task_id, result)
            except LocalImageCancelled:
                self.cancel(task_id)
            except Exception as exc:
                if not cancel.is_set():
                    message = str(exc)[:1000] or f"{self.label} 任务失败"
                    self.update_task(task_id, "failed", error=message, stage="failed", progress=100,
                                     progress_text=message)
            finally:
                with self._lock:
                    self._events.pop(task_id, None)
                self._queue.task_done()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for event in self._events.values():
                event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=8)
