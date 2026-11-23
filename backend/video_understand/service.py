"""Serial queue, content-addressed cache, and lifecycle management for video_understand."""
from __future__ import annotations

import atexit
import fcntl
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from ..local_image.downloads import sha256 as file_sha256
from ..local_image.preparation import Preparation
from . import environment
from .contracts import ACTIVE, ENGINE, MAX_QUEUE_DEPTH, MODES, PREPARE_PREFIX, normalize
from .runtime import Runtime
from .storage import Store

STATUS_TTL = 30


class VideoUnderstandService:
    def __init__(
        self,
        component: str | Path,
        data_root: str | Path,
        *,
        resolver: Any,
        runtime: Optional[Runtime] = None,
        preparation: Optional[Preparation] = None,
        status_reader=environment.status,
    ):
        self.component = Path(component)
        self.store = Store(data_root)
        self.resolver = resolver
        self.runtime = runtime or Runtime(self.component)
        self.preparation = preparation or Preparation(self.component, PREPARE_PREFIX, "视频理解")
        self._status_reader = status_reader
        self._lock = threading.RLock()
        self._status_cache = (0.0, None, None)
        self._queue: queue.Queue = queue.Queue()
        self._events: Dict[str, threading.Event] = {}
        self._thread: Optional[threading.Thread] = None
        self._lease = None
        self._closed = False
        atexit.register(self.close)

    def _start(self) -> None:
        if self._closed:
            raise RuntimeError("服务正在停止")
        if self._thread:
            return
        lease = (self.store.root / "service.lock").open("a+b")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lease.close()
            raise RuntimeError("另一个服务正在管理视频理解任务") from exc
        self._lease = lease
        self.store.recover()
        self._thread = threading.Thread(target=self._loop, name="video-understand-service", daemon=True)
        self._thread.start()

    def status(self) -> Dict[str, Any]:
        operation = self.preparation.status()
        key = (operation.get("status"), operation.get("stage"))
        with self._lock:
            checked, seen, cached = self._status_cache
            if cached is None or seen != key or (time.monotonic() - checked) > STATUS_TTL:
                cached = self._status_reader(self.component)
                self._status_cache = (time.monotonic(), key, cached)
        ready = bool(cached["ready"]) and operation.get("status") != "running"
        return {
            "ok": True,
            "engine": ENGINE,
            **cached,
            "ready": ready,
            "preparation": operation,
            "modes": {k: dict(v) for k, v in MODES.items()},
        }

    def prepare(self, _body=None) -> Dict[str, Any]:
        python = environment.launcher_python()
        if python is None:
            raise RuntimeError("未找到可运行准备程序的 Python")
        command = [str(python), "-u", "-m", "backend.video_understand.environment", "prepare"]
        return self.preparation.start(command, Path(__file__).resolve().parents[2], {"operation": "prepare"})

    def submit(self, body: Any) -> Dict[str, Any]:
        if self.preparation.status().get("status") == "running":
            raise RuntimeError("视频理解环境正在准备，请完成后再试")
        spec = normalize(body)
        video_path = self.resolver.resolve(spec["video_url"])
        if not self.status().get("ready"):
            raise RuntimeError("视频理解环境或模型尚未准备，请先在设置中心 → 模型工具中准备")

        video_digest = file_sha256(video_path)
        cache_payload = [
            ENGINE,
            self.runtime.fingerprint(),
            video_digest,
            {k: v for k, v in spec.items() if k != "video_url"},
        ]
        cache_key = hashlib.sha256(json.dumps(cache_payload, sort_keys=True).encode("utf-8")).hexdigest()

        with self._lock:
            self._start()
            if len(self._events) >= MAX_QUEUE_DEPTH:
                raise RuntimeError("视频理解队列已满，请稍后提交")
            for old in self.store.recent(100):
                if old.get("cache_key") == cache_key and old.get("status") == "succeeded":
                    try:
                        self.store.artifact(old["id"], "result/result.json")
                        self.store.artifact(old["id"], "result/output.md")
                    except FileNotFoundError:
                        continue
                    return old
            job = self.store.create(spec)
            job = self.store.update(job["id"], cache_key=cache_key, engine=ENGINE)
            self._events[job["id"]] = threading.Event()
            self._queue.put(job["id"])
            return job

    def job(self, ident: str) -> Dict[str, Any]:
        with self._lock:
            self._start()
        return self.store.get(ident)

    def cancel(self, ident: str) -> Dict[str, Any]:
        with self._lock:
            job = self.store.get(ident)
            event = self._events.get(ident)
            if event and job.get("status") in ACTIVE:
                event.set()
                return self.store.update(ident, status="cancelling", stage="正在停止")
            return job

    def _loop(self) -> None:
        while True:
            ident = self._queue.get()
            if ident is None:
                return
            with self._lock:
                event = self._events[ident]
                job = self.store.get(ident)
                if not event.is_set():
                    self.store.update(ident, status="running", started_at=time.time(), stage="准备本地处理")
            try:
                if event.is_set():
                    status, error = "cancelled", ""
                else:
                    video_path = self.resolver.resolve(job["spec"]["video_url"])

                    def progress(info: Dict[str, Any]) -> None:
                        with self._lock:
                            if event.is_set():
                                return
                            stage = str(info.get("stage") or "处理中")[:120]
                            message = str(info.get("message") or stage)[:1000]
                            ratio = info.get("ratio")
                            percent = None
                            if isinstance(ratio, (int, float)):
                                percent = max(0, min(100, round(float(ratio) * 100)))
                            obs = {
                                "stage": stage,
                                "message": message,
                                "generated_tokens": info.get("generated_tokens"),
                                "prompt_tokens": info.get("prompt_tokens"),
                                "decode_tps": info.get("decode_tps"),
                            }
                            current = self.store.get(ident)
                            events = (current.get("events", []) + [obs])[-50:]
                            changes: Dict[str, Any] = {
                                "stage": stage,
                                "progress_message": message,
                                "events": events,
                            }
                            if percent is not None:
                                changes["progress_percent"] = percent
                            if info.get("preview_tail"):
                                changes["preview_tail"] = str(info["preview_tail"])[:200]
                            self.store.update(ident, **changes)

                    status, error = self.runtime.execute(
                        job["spec"], self.store.path(ident), video_path, event, progress
                    )

                with self._lock:
                    if event.is_set():
                        status, error = "cancelled", ""
                    artifacts = []
                    result_summary = None
                    if status == "succeeded":
                        res_dir = self.store.path(ident) / "result"
                        result_summary = json.loads((res_dir / "result.json").read_text(encoding="utf-8"))
                        for name in ("output.md", "result.json", "shots.json"):
                            file_path = res_dir / name
                            if file_path.is_file():
                                rel = "result/" + name
                                artifacts.append(
                                    {
                                        "name": rel,
                                        "file_size": file_path.stat().st_size,
                                        "url": "/api/video_understand/artifact?" + urlencode({"id": ident, "name": rel}),
                                    }
                                )
                    self.store.update(
                        ident,
                        status=status,
                        error=error,
                        stage={"succeeded": "分析完成", "failed": "分析失败", "cancelled": "已停止"}.get(status, status),
                        progress_percent=100 if status == "succeeded" else self.store.get(ident).get("progress_percent", 0),
                        finished_at=time.time(),
                        result=result_summary,
                        artifacts=artifacts,
                    )
            except Exception as exc:
                self.store.update(
                    ident,
                    status="cancelled" if event.is_set() else "failed",
                    stage="已停止" if event.is_set() else "分析失败",
                    error=str(exc)[:2000],
                    finished_at=time.time(),
                )
            finally:
                with self._lock:
                    self._events.pop(ident, None)
                self._queue.task_done()

    def close(self) -> None:
        self.preparation.close()
        with self._lock:
            self._closed = True
            for event in self._events.values():
                event.set()
            if self._thread:
                self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=8)
        if self._lease and (not self._thread or not self._thread.is_alive()):
            self._lease.close()
            self._lease = None
