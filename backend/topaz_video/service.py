"""Serial task service for Topaz Video, independent from video-control/audio."""
from __future__ import annotations

import atexit
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
from urllib.parse import urlencode

from .contracts import ACTIVE, normalize
from .features import validate_capabilities
from .storage import Store


class TopazVideoService:
    def __init__(self, root: Path | str, runtime):
        self.store = Store(root)
        self.runtime = runtime
        self._lock = threading.RLock()
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._events: dict[str, threading.Event] = {}
        self._thread: threading.Thread | None = None
        self._lease = None
        self._closed = False
        atexit.register(self.close)

    def _start(self) -> None:
        if self._closed:
            raise RuntimeError("Topaz Video 服务正在停止")
        if self._thread:
            return
        import fcntl
        lease = (self.store.root / "service.lock").open("a+b")
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lease.close()
            raise RuntimeError("另一个服务正在管理 Topaz Video 任务") from exc
        self._lease = lease
        self.store.recover()
        self._thread = threading.Thread(target=self._loop, name="topaz-video-jobs", daemon=True)
        self._thread.start()

    def status(self) -> dict:
        result = dict(self.runtime.status())
        completed = self.store.verified_model_scales()
        models = []
        for source in result.get("models", []):
            item = dict(source)
            declared = {int(scale) for scale in item.get("scales", [])
                        if not isinstance(scale, bool) and isinstance(scale, (int, float))}
            observed = {int(scale) for scale in item.get("verified_scales", [])
                        if not isinstance(scale, bool) and isinstance(scale, (int, float))}
            observed.update(completed.get(str(item.get("id") or ""), ()))
            if declared:
                observed.intersection_update(declared)
            if item.get("available") and observed:
                item["verified"] = True
                item["verified_scales"] = sorted(observed)
                scale_label = " / ".join(f"{scale}×" for scale in sorted(observed))
                if declared and declared.issubset(observed):
                    item["reason"] = (f"本机已完成无水印短片验证（{scale_label}）；"
                                      "长片画质/速度未验收")
                else:
                    item["reason"] = (f"本机已完成无水印短片验证（{scale_label}）；"
                                      "其他倍率建议先生成短选区预览")
            elif not item.get("available"):
                item["verified"] = False
                item["verified_scales"] = []
            else:
                item["verified_scales"] = sorted(observed)
            models.append(item)
        result["models"] = models
        return result

    def upload(self, data: bytes, name: str) -> dict:
        if not (data[:4] == b"\x1aE\xdf\xa3" or data[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free"}):
            raise ValueError("仅接受 MP4 / MOV / WebM / MKV 视频容器")
        info = self.store.upload(data, name)
        path = self.store.asset(info["asset_id"])
        try:
            ffprobe = self.runtime.probe_binary()
            command = [str(ffprobe), "-v", "error", "-protocol_whitelist", "file,pipe",
                       "-select_streams", "v:0", "-show_entries", "stream=width,height",
                       "-of", "json", str(path)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            streams = json.loads(result.stdout).get("streams", []) if result.returncode == 0 else []
            if not streams or not 0 < int(streams[0].get("width", 0)) <= 7680 or not 0 < int(streams[0].get("height", 0)) <= 7680:
                raise ValueError("视频不可读取或尺寸超过 7680 像素")
        except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            raise ValueError("无法读取视频，请导入有效的本地 MP4 / MOV / WebM 视频") from exc
        return info

    def submit(self, body: object) -> dict:
        spec = normalize(body)
        self.store.asset(spec["asset_id"])
        try:
            validate_capabilities(spec, self.runtime.status())
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        with self._lock:
            self._start()
            if len(self._events) >= 8:
                raise RuntimeError("Topaz Video 队列已满，请稍后重试")
            job = self.store.create(spec)
            self._events[job["id"]] = threading.Event()
            self._queue.put(job["id"])
            return job

    def job(self, ident: str) -> dict:
        with self._lock:
            self._start()
        return self.store.get(ident)

    def cancel(self, ident: str) -> dict:
        with self._lock:
            job = self.store.get(ident)
            event = self._events.get(ident)
            if event and job["status"] in ACTIVE:
                event.set()
                return self.store.update(ident, status="cancelling", stage="正在停止",
                                         progress_message="正在停止本地推理")
            return job

    def _loop(self) -> None:
        while True:
            ident = self._queue.get()
            if ident is None:
                self._queue.task_done()
                return
            with self._lock:
                event = self._events[ident]
                job = self.store.get(ident)
                if not event.is_set():
                    self.store.update(ident, status="running", started_at=time.time(),
                                      stage="准备本地模型", progress_message="准备本地模型")
            try:
                def progress(info: dict) -> None:
                    with self._lock:
                        if event.is_set():
                            return
                        percent = max(0, min(100, int(info.get("percent", 0))))
                        stage = str(info.get("stage") or "本地视频增强")[:100]
                        message = str(info.get("message") or stage)[:300]
                        old = self.store.get(ident)
                        events = (old.get("events", []) + [{"at": time.time(), "stage": stage,
                                                             "message": message, "percent": percent}])[-40:]
                        self.store.update(ident, stage=stage, progress_percent=percent,
                                          progress=percent, progress_message=message, events=events)

                status, error = ("cancelled", "") if event.is_set() else self.runtime.execute(
                    job["spec"], self.store.path(ident), self.store.asset(job["spec"]["asset_id"]), event, progress)
                with self._lock:
                    if event.is_set():
                        status, error = "cancelled", ""
                    artifacts = []
                    provenance = {}
                    if status == "succeeded":
                        path = self.store.path(ident) / "result/enhanced.mp4"
                        provenance_path = self.store.path(ident) / "result/provenance.json"
                        if not path.is_file() or path.stat().st_size == 0:
                            raise RuntimeError("模型报告成功但视频结果缺失")
                        try:
                            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError) as exc:
                            raise RuntimeError("视频结果缺少无水印验收记录") from exc
                        if (provenance.get("watermark_verified") is not True
                                or provenance.get("verification") not in {
                                    "licensed_topaz_checkout",
                                    "precise_engine_no_watermark_baseline",
                                    "local_video_encoding",
                                }):
                            raise RuntimeError("视频结果未通过无水印验收")
                        name = "result/enhanced.mp4"
                        artifacts = [{"name": name, "file_size": path.stat().st_size,
                                      "url": "/api/topaz_video/artifact?" + urlencode({"id": ident, "name": name})}]
                    percent = 100 if status == "succeeded" else self.store.get(ident).get("progress_percent", 0)
                    self.store.update(ident, status=status, error=error[:2000],
                        stage={"succeeded": "处理完成", "failed": "处理失败", "cancelled": "已停止"}.get(status, status),
                        progress_message={"succeeded": "视频结果已保存", "failed": error[:300], "cancelled": "任务已停止"}.get(status, ""),
                        progress_percent=percent, progress=percent,
                        watermark_verified=bool(status == "succeeded"),
                        export_provenance=(provenance.get("verification", "") if status == "succeeded" else ""),
                        media=(provenance.get("media", {}) if status == "succeeded" else {}),
                        artifacts=artifacts, finished_at=time.time())
            except Exception as exc:
                self.store.update(ident, status="cancelled" if event.is_set() else "failed",
                    stage="已停止" if event.is_set() else "处理失败",
                    progress_message="任务已停止" if event.is_set() else str(exc)[:300],
                    error="" if event.is_set() else str(exc)[:2000], finished_at=time.time())
            finally:
                with self._lock:
                    self._events.pop(ident, None)
                self._queue.task_done()

    def close(self) -> None:
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
