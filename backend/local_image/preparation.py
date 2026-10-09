"""One preparation process per component, with bounded public progress."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import threading

from .runtime import _stop


class Preparation:
    def __init__(self, component, prefix, label):
        self.component, self.prefix, self.label = Path(component), prefix, str(label)
        self._lock = threading.RLock()
        self._process = None
        self._state = {"status": "idle", "message": "", "stage": ""}

    def status(self):
        with self._lock:
            return dict(self._state)

    def start(self, command, cwd, metadata):
        with self._lock:
            if self._process and self._process.poll() is None:
                return {"ok": True, "preparation": dict(self._state), "already_running": True}
            process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, start_new_session=True)
            self._process = process
            self._state = {"status": "running", "stage": "starting", "message": f"开始准备 {self.label}",
                           "downloaded": 0, "total": 0, **metadata}
            threading.Thread(target=self._watch, args=(process,), name=f"{self.label}-prepare", daemon=True).start()
            return {"ok": True, "preparation": dict(self._state), "already_running": False}

    def _watch(self, process):
        directory = self.component / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with (directory / "prepare.log").open("a", encoding="utf-8") as log:
                written = 0
                for line in process.stdout:
                    if written < 8 * 1024**2:
                        log.write(line)
                        log.flush()
                        written += len(line.encode())
                    if not line.startswith(self.prefix):
                        continue
                    try:
                        event = json.loads(line[len(self.prefix):])
                    except ValueError:
                        continue
                    safe = {key: event[key] for key in ("stage", "message", "downloaded", "total", "file") if key in event}
                    with self._lock:
                        if self._process is process:
                            self._state.update(safe)
                code = process.wait()
            with self._lock:
                if self._process is process:
                    self._state.update(status="succeeded" if code == 0 else "failed", stage="done" if code == 0 else "failed")
                    if code == 0:
                        self._state["message"] = f"{self.label} 准备完成"
                    elif not self._state.get("message") or self._state["message"].startswith("开始准备"):
                        self._state["message"] = f"{self.label} 准备失败（退出码 {code}）"
        finally:
            process.stdout.close()

    def close(self):
        with self._lock:
            process = self._process
        _stop(process)
