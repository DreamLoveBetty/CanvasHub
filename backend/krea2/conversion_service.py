"""One-at-a-time Krea 2 model conversion orchestration.

The service owns job state and process lifecycle.  MLX is imported only by the
converter child, while the neutral accelerator lease serializes it with YuE,
Krea generation and the other Mac-local inference domains.
"""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid

from .contracts import BUILDS, EXPORT_FORMATS
from .converter_worker import PREFIX
from ..runtime_resources import local_accelerator


ACTIVE = {"queued", "waiting", "running"}
TERMINAL = {"succeeded", "failed", "canceled"}


def _stop(process):
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


class ConversionService:
    def __init__(self, root, component, runtime, store, timeout=3 * 60 * 60):
        self.root = Path(root).resolve()
        self.component = Path(component).resolve()
        self.runtime = runtime
        self.store = store
        self.timeout = int(timeout)
        self.state_path = self.root / "model-conversion.json"
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._process = None
        self._thread = None
        self._closed = False
        self._state = self._load_state()
        if self._state.get("status") in ACTIVE:
            self._state.update(status="failed", stage="interrupted", progress=100,
                               message="服务重启，上一轮模型转换已中断",
                               error="服务重启，上一轮模型转换已中断")
            self._save_state()
        atexit.register(self.close)

    def _load_state(self):
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        self.root.mkdir(parents=True, exist_ok=True)
        pending = self.state_path.with_suffix(".json.tmp")
        pending.write_text(json.dumps(self._state, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        os.replace(pending, self.state_path)

    @staticmethod
    def _public(state):
        fields = ("job_id", "status", "stage", "message", "progress", "source_name",
                  "source_format", "model_name", "precision", "created_at", "updated_at",
                  "model", "error")
        return {key: state[key] for key in fields if key in state}

    def status(self):
        with self._lock:
            state = dict(self._state)
            return self._public(state or {"status": "idle", "stage": "", "message": ""})

    def inspect(self, body):
        body = body if isinstance(body, dict) else {}
        result = self.store.inspect_source(body.get("source_path"))
        for precision, build in BUILDS.items():
            result.setdefault("estimated_outputs", {})[precision] = build["size"]
        result.pop("source_path", None)
        result.pop("metadata", None)
        return result

    @staticmethod
    def _name(value, fallback):
        name = re.sub(r"[\x00-\x1f/\\]+", " ", str(value or ""))
        name = re.sub(r"\s+", " ", name).strip()[:120]
        return name or str(fallback or "Krea 2 模型")[:120]

    def start(self, body):
        body = body if isinstance(body, dict) else {}
        precision = str(body.get("precision") or "8bit")
        if precision not in EXPORT_FORMATS:
            raise ValueError("未知输出精度")
        inspected = self.store.inspect_source(body.get("source_path"))
        if inspected["kind"] == "lora":
            raise ValueError("该文件是 LoRA/差分权重，请放入 LoRA 模型目录")
        if inspected["kind"] == "quantized":
            raise ValueError("该文件已经量化，请选择原始 FP32/BF16/FP16 权重")
        if inspected["kind"] == "unsupported":
            raise ValueError(inspected["message"])
        name = self._name(body.get("model_name"), inspected["suggested_name"])
        paths = self.store.paths()
        output_bytes = inspected.get("estimated_outputs", {}).get(precision)
        if output_bytes is None:
            output_bytes = BUILDS[precision]["size"]
        expected = int(output_bytes * 1.08) + 2 * 1024**3
        free = shutil.disk_usage(paths["base_model_directory"]).free
        if free < expected:
            raise RuntimeError(f"Base 权重目录空间不足，至少还需要约 {expected / 1024**3:.1f} GiB")
        with self._lock:
            if self._closed:
                raise RuntimeError("模型转换服务已关闭")
            if self._state.get("status") in ACTIVE:
                raise RuntimeError("已有 Krea 2 模型转换任务正在进行")
            job_id = "krea2_convert_" + uuid.uuid4().hex
            stage = self.store.staging / job_id
            stage.mkdir(parents=True, exist_ok=False)
            self._cancel = threading.Event()
            now = int(time.time())
            self._state = {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "message": "模型转换已进入本地推理队列",
                "progress": 1,
                "source_name": inspected["source_name"],
                "source_format": inspected.get("source_format", "float"),
                "model_name": name,
                "precision": precision,
                "created_at": now,
                "updated_at": now,
                "error": "",
            }
            self._save_state()
            spec = {"job_id": job_id, "source_path": inspected["source_path"],
                    "source_name": inspected["source_name"], "model_name": name,
                    "precision": precision, "stage": stage}
            self._thread = threading.Thread(target=self._run, args=(spec,),
                                            name="krea2-model-conversion", daemon=True)
            self._thread.start()
            return self._public(dict(self._state))

    def _update(self, **values):
        with self._lock:
            if values.get("job_id") and values["job_id"] != self._state.get("job_id"):
                return
            values.pop("job_id", None)
            self._state.update(values, updated_at=int(time.time()))
            self._save_state()

    def _run(self, spec):
        stage = Path(spec["stage"])

        def waiting(event):
            message = str(event.get("message") or event.get("stage") or "等待其他本地推理任务释放资源")
            self._update(status="waiting", stage="waiting", message=message, progress=2)

        try:
            with local_accelerator(self.component.parent / ".local-inference.lock",
                                   self._cancel, waiting) as lease:
                if self._cancel.is_set():
                    raise InterruptedError("模型转换已取消")
                # A previous server crash may have left an unpublished staging
                # directory.  The lease proves no inherited converter is still
                # writing there, so stale stages are now safe to remove.
                self.store.staging.mkdir(parents=True, exist_ok=True)
                for stale in self.store.staging.iterdir():
                    if stale != stage:
                        if stale.is_dir() and not stale.is_symlink():
                            shutil.rmtree(stale, ignore_errors=True)
                        else:
                            stale.unlink(missing_ok=True)
                # The lease guarantees no generation is active.  Close a warm
                # Krea worker now so its resident model releases unified memory.
                release = getattr(self.runtime, "release_accelerator_memory", self.runtime.close)
                release()
                self._execute(spec, lease.fileno())
        except InterruptedError:
            self._update(status="canceled", stage="canceled", message="模型转换已取消",
                         progress=100, error="")
            shutil.rmtree(stage, ignore_errors=True)
        except Exception as exc:
            if self._cancel.is_set():
                self._update(status="canceled", stage="canceled", message="模型转换已取消",
                             progress=100, error="")
            else:
                message = str(exc)[:2000] or "模型转换失败"
                self._update(status="failed", stage="failed", message=message,
                             progress=100, error=message)
            shutil.rmtree(stage, ignore_errors=True)
        finally:
            with self._lock:
                self._process = None

    def _execute(self, spec, lease_fd):
        python = self.runtime.python
        if python is None or not python.is_file():
            raise RuntimeError("未找到画布共享 Python 环境")
        command = [str(python), "-u", str(Path(__file__).with_name("converter_worker.py")),
                   "--component", str(self.component), "--source", spec["source_path"],
                   "--output", str(spec["stage"]), "--precision", spec["precision"],
                   "--name", spec["model_name"]]
        process = subprocess.Popen(
            command, cwd=self.component,
            env=self.runtime.child_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True,
            # Keep the accelerator lease alive in the converter if the server
            # exits unexpectedly.  New YuE/Krea/Topaz/ReShot work will remain
            # queued until the orphaned conversion process itself terminates.
            pass_fds=(int(lease_fd),))
        with self._lock:
            self._process = process
        self._update(status="running", stage="starting", message="启动 MLX 模型转换进程",
                     progress=3)
        done = threading.Event()
        expired = threading.Event()

        def watch():
            deadline = time.monotonic() + self.timeout
            while not done.wait(.25):
                if self._cancel.is_set():
                    _stop(process)
                    return
                if time.monotonic() >= deadline:
                    expired.set()
                    _stop(process)
                    return

        watcher = threading.Thread(target=watch, name="krea2-convert-watchdog", daemon=True)
        watcher.start()
        result = None
        error = ""
        log_dir = self.component / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{spec['job_id']}.log"
        try:
            with log_path.open("a", encoding="utf-8") as log:
                written = log_path.stat().st_size
                for line in process.stdout:
                    if written < 8 * 1024 * 1024:
                        log.write(line)
                        log.flush()
                        written += len(line.encode("utf-8", "replace"))
                    clean = line.strip()
                    if not clean.startswith(PREFIX):
                        continue
                    try:
                        event = json.loads(clean[len(PREFIX):])
                    except ValueError:
                        continue
                    if event.get("event") == "progress":
                        progress = max(3, min(98, int(float(event.get("progress") or 3))))
                        self._update(status="running", stage="converting",
                                     message=str(event.get("stage") or "MLX 模型转换中")[:240],
                                     progress=progress)
                    elif event.get("event") == "result":
                        result = event
                    elif event.get("event") == "error":
                        error = str(event.get("message") or "模型转换失败")
            code = process.wait()
            if self._cancel.is_set():
                raise InterruptedError("模型转换已取消")
            if expired.is_set():
                raise RuntimeError("模型转换超过三小时限制，进程已终止")
            if code != 0 or not result:
                raise RuntimeError(error or f"模型转换进程异常退出：{code}")
            if result.get("precision") != spec["precision"]:
                raise RuntimeError("转换结果与请求的输出精度不一致")
            self._update(status="running", stage="publishing", message="注册 Base 权重模型",
                         progress=99)
            model = self.store.publish(
                spec["stage"], name=spec["model_name"], precision=spec["precision"],
                source_name=spec["source_name"], source_sha256=result["source_sha256"],
                output_sha256=result["output_sha256"],
                source_prefix=result.get("source_prefix", ""),
                source_tensor_count=result.get("source_tensor_count", 0),
                output_tensor_count=result.get("output_tensor_count", 0),
                quantized_linear_count=result.get("quantized_linear_count", 0),
                source_format=result.get("source_format", "float"),
                source_quantized_tensor_count=result.get("source_quantized_tensor_count", 0))
            self._update(status="succeeded", stage="done", message="模型转换完成，已加入 Base 权重列表",
                         progress=100, model=model, error="")
        finally:
            done.set()
            watcher.join(timeout=5)
            try:
                process.stdout.close()
            except OSError:
                pass

    def cancel(self):
        with self._lock:
            if self._state.get("status") not in ACTIVE:
                return self._public(dict(self._state or {"status": "idle"}))
            self._cancel.set()
            self._state.update(message="正在停止模型转换", stage="canceling",
                               updated_at=int(time.time()))
            self._save_state()
            return self._public(dict(self._state))

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
