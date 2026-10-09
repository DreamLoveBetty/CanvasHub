"""Krea 2 queue, local assets, archive and task-state orchestration."""
from __future__ import annotations

import atexit
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from PIL import Image, UnidentifiedImageError

from ..services.generation_timing import normalize_generation_timing
from .contracts import (BUILDS, BUILTIN_MODEL_IDS, DEFAULT_MODEL_ID, EXPORT_FORMATS,
                        MAX_IMAGE_UPLOAD, TASK_TYPE, TERMINAL, catalog,
                        normalize_job, normalize_model_id)
from .conversion_service import ConversionService
from .lora_store import LoRAStore
from .model_store import BaseModelStore
from .runtime import Krea2Cancelled


class _CancelPort:
    """Cancellation port shared by the queue event and the generic task API."""
    def __init__(self, event, task_id, get_task):
        self.event, self.task_id, self.get_task = event, task_id, get_task

    def is_set(self):
        if self.event.is_set():
            return True
        task = self.get_task(self.task_id)
        return str((task or {}).get("status") or "") in {"canceled", "cancelled"}

    def wait(self, timeout):
        self.event.wait(timeout)
        return self.is_set()


class Service:
    def __init__(self, root, component, runtime, *, create_task, get_task, get_all_tasks,
                 update_task, update_task_status, update_task_fields, daily_output_dir,
                 write_prompt_sidecar, send_document, model_store=None,
                 conversion_service=None):
        self.root = Path(root).resolve()
        self.component = Path(component).resolve()
        self.runtime = runtime
        self.create_task = create_task
        self.get_task = get_task
        self.get_all_tasks = get_all_tasks
        self.update_task = update_task
        self.update_task_status = update_task_status
        self.update_task_fields = update_task_fields
        self.daily_output_dir = daily_output_dir
        self.write_prompt_sidecar = write_prompt_sidecar
        self.send_document = send_document
        self.loras = LoRAStore(self.root / "assets")
        self.models = model_store or BaseModelStore(self.root / "assets", self.component)
        self.conversion = conversion_service or ConversionService(
            self.root, self.component, self.runtime, self.models)
        self._uploads = {}
        self._events = {}
        self._queue = queue.Queue(maxsize=8)
        self._lock = threading.RLock()
        self._model_lock = threading.RLock()
        self._thread = None
        self._closed = False
        self._prepare_process = None
        self._prepare_state = {"status": "idle", "stage": "", "message": ""}
        atexit.register(self.close)

    def status(self):
        result = self.runtime.status()
        raw_builds = result.get("builds") or {}
        # Do not disclose machine-specific paths or authentication tokens.
        result.pop("shared_python", None)
        result["builds"] = {
            name: {"ready": bool((result.get("builds") or {}).get(name, {}).get("ready")),
                   "download_bytes": build["size"], "label": build["label"]}
            for name, build in BUILDS.items()
        }
        result["models"] = self.models.list(raw_builds)
        result["default_model_id"] = DEFAULT_MODEL_ID
        if any(model.get("ready") for model in result["models"]):
            result["reasons"] = [reason for reason in result.get("reasons") or []
                                 if "量化 Transformer 尚未下载" not in reason]
        result["ready"] = bool(result.get("environment_ready") and result.get("source_ready")
                               and result.get("base_ready")
                               and any(model.get("ready") for model in result["models"]))
        with self._lock:
            process = self._prepare_process
            preparing = bool(process and process.poll() is None)
            state = dict(self._prepare_state)
        state["status"] = "running" if preparing else state.get("status", "idle")
        result.update({"ok": True, "preparation": state, "lora_count": len(self.loras.list())})
        return result

    def catalog(self):
        runtime = self.runtime.status()
        return {"ok": True, **catalog(self.models.list(runtime.get("builds") or {}))}

    def model_tools(self):
        runtime = self.runtime.status()
        return {"ok": True, **self.models.paths(),
                "import_models": self.models.list_imports(),
                "models": self.models.list(runtime.get("builds") or {}),
                "conversion": self.conversion.status()}

    def inspect_model(self, body):
        return {"ok": True, "inspection": self.conversion.inspect(body)}

    def convert_model(self, body):
        runtime = self.runtime.status()
        if not runtime.get("environment_ready") or not runtime.get("source_ready"):
            raise RuntimeError("Krea 2 共享环境或固定版本源码尚未准备")
        with self._lock:
            if self._prepare_process and self._prepare_process.poll() is None:
                raise RuntimeError("Krea 2 环境正在准备，请完成后再转换模型")
        return {"ok": True, "conversion": self.conversion.start(body)}

    def cancel_model_conversion(self):
        return {"ok": True, "conversion": self.conversion.cancel()}

    def delete_model(self, model_id):
        model_id = normalize_model_id(model_id)
        with self._model_lock:
            if self.conversion.status().get("status") in {"queued", "waiting", "running"}:
                raise RuntimeError("模型转换期间不能删除 Base 权重")
            for task in self.get_all_tasks(limit=5000):
                if task.get("type") != TASK_TYPE or task.get("status") in TERMINAL:
                    continue
                if (task.get("params") or {}).get("base_model_id") == model_id:
                    raise RuntimeError("该 Base 权重正被排队或运行中的 Krea 2 任务使用")
            getattr(self.runtime, "close_idle", self.runtime.close)()
            return {"ok": True, "model": self.models.delete(model_id)}

    def upload_image(self, content, filename="source"):
        if not content or len(content) > MAX_IMAGE_UPLOAD:
            raise ValueError("参考图须小于 32 MB")
        try:
            with Image.open(__import__("io").BytesIO(content)) as image:
                image.verify()
                width, height, fmt = image.width, image.height, str(image.format or "").upper()
        except (OSError, ValueError, UnidentifiedImageError) as exc:
            raise ValueError("无法识别参考图文件") from exc
        if not width or not height or width * height > 100_000_000:
            raise ValueError("参考图尺寸无效或像素过大")
        suffix = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "AVIF": ".avif"}.get(fmt)
        if not suffix:
            raise ValueError("参考图仅支持 PNG、JPEG、WebP 或 AVIF")
        directory = self.root / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        target = directory / f"{token}{suffix}"
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".upload-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, target)
        with self._lock:
            now = time.time()
            expired = [key for key, item in self._uploads.items() if item[1] < now]
            for key in expired:
                self._uploads.pop(key)[0].unlink(missing_ok=True)
            self._uploads[token] = (target, now + 3600)
        return {"ok": True, "upload_token": token, "width": width, "height": height,
                "filename": Path(str(filename or "source")).name[:160]}

    def import_lora(self, stream, size, filename):
        return {"ok": True, "lora": self.loras.import_stream(stream, size, filename)}

    def list_loras(self):
        return {"ok": True, "loras": self.loras.list()}

    def delete_lora(self, asset_id):
        asset_id = str(asset_id or "").replace("sha256:", "").lower()
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") != TASK_TYPE or task.get("status") in TERMINAL:
                continue
            for item in (task.get("params") or {}).get("loras") or []:
                if item.get("asset_id") == asset_id:
                    raise RuntimeError("该 LoRA 正被排队或运行中的 Krea 2 任务使用")
            if ((task.get("params") or {}).get("edit_adapter") or {}).get("asset_id") == asset_id:
                raise RuntimeError("该编辑 LoRA 正被排队或运行中的 Krea 2 任务使用")
        return {"ok": True, "lora": self.loras.delete(asset_id)}

    def prepare(self, body):
        body = body if isinstance(body, dict) else {}
        if self.conversion.status().get("status") in {"queued", "waiting", "running"}:
            raise RuntimeError("Base 权重正在转换，请完成后再准备 Krea 2 环境")
        requested_id = body.get("base_model_id")
        precision = str(body.get("precision") or "8bit")
        if requested_id:
            model_id = normalize_model_id(requested_id)
            builtin_precision = next((key for key, value in BUILTIN_MODEL_IDS.items()
                                      if value == model_id), None)
            if builtin_precision:
                precision = builtin_precision
                install_model = precision
            else:
                model = self.models.resolve(model_id)
                precision = model["precision"]
                install_model = "none"
        else:
            model_id = BUILTIN_MODEL_IDS.get(precision, DEFAULT_MODEL_ID)
            install_model = precision
        safety_enabled = body.get("safety_enabled") is True
        if precision not in EXPORT_FORMATS or (install_model != "none" and precision not in BUILDS):
            raise ValueError("未知 Krea 2 模型构建")
        with self._lock:
            if self._prepare_process and self._prepare_process.poll() is None:
                return {"ok": True, "preparation": dict(self._prepare_state), "already_running": True}
            python = self.runtime.python
            if python is None or not python.is_file():
                raise RuntimeError("未找到画布共享 Python 环境")
            command = [str(python), "-u", "-m", "backend.krea2.install", "--models", install_model,
                       "--python", str(python)]
            if not safety_enabled:
                command.append("--skip-safety")
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[2],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, bufsize=1, start_new_session=True)
            self._prepare_process = process
            self._prepare_state = {"status": "running", "stage": "starting",
                                   "message": "开始准备 Krea 2", "precision": precision,
                                   "base_model_id": model_id,
                                   "safety_enabled": safety_enabled,
                                   "downloaded": 0,
                                   "total": BUILDS[precision]["size"] if install_model != "none" else 0}
        threading.Thread(target=self._watch_prepare, args=(process,), name="krea2-prepare",
                         daemon=True).start()
        return {"ok": True, "preparation": dict(self._prepare_state)}

    def _watch_prepare(self, process):
        log_dir = self.component / "runtime"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (log_dir / "prepare.log").open("a", encoding="utf-8") as log:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if not line.startswith("KREA2_EVENT "):
                        continue
                    try:
                        event = json.loads(line[len("KREA2_EVENT "):])
                    except ValueError:
                        continue
                    safe = {key: event[key] for key in ("stage", "message", "downloaded", "total", "file")
                            if key in event}
                    safe["status"] = "running"
                    with self._lock:
                        if self._prepare_process is process:
                            self._prepare_state.update(safe)
            code = process.wait()
            with self._lock:
                if self._prepare_process is process:
                    previous_message = str(self._prepare_state.get("message") or "")
                    self._prepare_state.update(status="succeeded" if code == 0 else "failed",
                                               stage="done" if code == 0 else "failed")
                    self._prepare_state["message"] = ("Krea 2 准备完成" if code == 0 else
                        previous_message if previous_message and previous_message != "开始准备 Krea 2"
                        else f"Krea 2 准备失败（退出码 {code}）")
        finally:
            try:
                process.stdout.close()
            except OSError:
                pass

    def _uploaded_image(self, token, directory, stem="input"):
        token = str(token or "")
        if not token:
            return ""
        with self._lock:
            record = self._uploads.get(token)
        if not record or record[1] < time.time() or not record[0].is_file():
            raise ValueError("参考图已过期，请重新连接并上传")
        destination = directory / (str(stem) + record[0].suffix)
        shutil.copyfile(record[0], destination)
        return str(destination)

    def submit(self, body):
        spec = normalize_job(body)
        with self._model_lock:
            model = self.models.resolve(spec["base_model_id"])
            spec.update({"base_model_id": model["id"], "base_model_name": model["name"],
                         "precision": model["precision"]})
            runtime_status = self.runtime.status()
            ready = (runtime_status.get("environment_ready") and runtime_status.get("source_ready")
                     and runtime_status.get("base_ready")
                     and (not spec["safety_enabled"] or runtime_status.get("safety_ready"))
                     and model.get("ready"))
            if not ready:
                reasons = list(runtime_status.get("reasons") or [])
                if spec["safety_enabled"] and not runtime_status.get("safety_ready"):
                    reasons.append("Krea 2 安全分类模型尚未下载")
                if not model.get("ready"):
                    reasons.append(f"Base 权重模型 {model['name']} 尚未准备")
                raise RuntimeError("Krea 2 尚未就绪：" + "；".join(dict.fromkeys(reasons or ["请先准备模型"])))
            resolved_loras = []
            public_loras = []
            for item in spec["loras"]:
                path, meta = self.loras.resolve(item["asset_id"])
                resolved_loras.append({"path": str(path), "scale": item["scale"]})
                public_loras.append({"asset_id": item["asset_id"], "name": meta.get("name", "LoRA"),
                                     "scale": item["scale"]})
            resolved_edit_adapter = None
            public_edit_adapter = None
            if spec["mode"] == "edit":
                path, meta = self.loras.resolve(spec["edit_adapter_asset_id"])
                resolved_edit_adapter = {
                    "path": str(path), "scale": spec["edit_adapter_scale"]}
                public_edit_adapter = {
                    "asset_id": spec["edit_adapter_asset_id"],
                    "name": meta.get("name", "Krea 2 Edit LoRA"),
                    "scale": spec["edit_adapter_scale"],
                }
            with self._lock:
                if self._closed or self._queue.full():
                    raise RuntimeError("Krea 2 队列繁忙，请稍后重试")
                task_id = "krea2_" + uuid.uuid4().hex
                directory = self.root / "jobs" / task_id
                directory.mkdir(parents=True, exist_ok=False)
                try:
                    init_image = self._uploaded_image(spec.pop("init_image_upload_token"), directory)
                    edit_image = self._uploaded_image(
                        spec.pop("edit_image_upload_token"), directory, "edit_input")
                    worker_spec = {**spec, "init_image": init_image, "loras": resolved_loras,
                                   "edit_image": edit_image,
                                   "edit_adapter": resolved_edit_adapter,
                                   "model": {"id": model["id"], "name": model["name"],
                                             "precision": model["precision"],
                                             "path": str(model["path"])}}
                    stored_params = {key: value for key, value in spec.items() if key != "prompt"}
                    model_display_name = str(model["name"])
                    if not model_display_name.lower().startswith("krea"):
                        model_display_name = f"Krea2 · {model_display_name}"
                    stored_params.update({"provider": "krea2-alis-mlx", "loras": public_loras,
                                          "edit_adapter": public_edit_adapter,
                                          "main_model": model_display_name,
                                          "has_init_image": bool(init_image),
                                          "has_edit_image": bool(edit_image)})
                    (directory / "submission.json").write_text(
                        json.dumps({**worker_spec, "loras": public_loras,
                                    "edit_adapter": public_edit_adapter},
                                   ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
                    self.create_task(task_id, spec["prompt"], stored_params, status="queued", task_type=TASK_TYPE)
                    event = threading.Event()
                    self._events[task_id] = event
                    self._queue.put_nowait((task_id, worker_spec))
                    if self._thread is None or not self._thread.is_alive():
                        self._thread = threading.Thread(target=self._work, name="krea2-queue", daemon=True)
                        self._thread.start()
                except Exception:
                    shutil.rmtree(directory, ignore_errors=True)
                    raise
        return {"ok": True, "task_id": task_id, "status": "queued", "type": TASK_TYPE}

    def cancel(self, task_id):
        task = self.get_task(str(task_id or ""))
        if not task or task.get("type") != TASK_TYPE:
            raise ValueError("Krea 2 任务不存在")
        with self._lock:
            event = self._events.get(task["task_id"])
            if event:
                event.set()
        if task.get("status") not in TERMINAL:
            self.update_task(task["task_id"], "canceled", stage="canceled", progress=100,
                             progress_text="任务已取消", error="")
        return {"ok": True, **(self.get_task(task["task_id"]) or task)}

    def _work(self):
        while not self._closed:
            try:
                task_id, spec = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            with self._lock:
                event = self._events.get(task_id) or threading.Event()
            cancel = _CancelPort(event, task_id, self.get_task)
            try:
                if cancel.is_set():
                    continue
                self.update_task_status(task_id, "processing", "等待 Krea 2 本地推理资源",
                                        stage="waiting", progress=1)
                directory = self.root / "jobs" / task_id

                def progress(ratio, text):
                    if not cancel.is_set():
                        percent = max(1, min(95, int(float(ratio) * 100)))
                        self.update_task_status(task_id, "processing", str(text)[:240],
                                                stage="generating", progress=percent)

                result = self.runtime.execute(spec, directory, cancel, progress)
                if cancel.is_set():
                    raise Krea2Cancelled("任务已取消")
                self._archive(task_id, result)
            except Krea2Cancelled:
                if (self.get_task(task_id) or {}).get("status") not in TERMINAL:
                    self.update_task(task_id, "canceled", stage="canceled", progress=100,
                                     progress_text="任务已取消", error="")
            except Exception as exc:
                if not cancel.is_set():
                    message = str(exc)[:1000] or "Krea 2 任务失败"
                    self.update_task(task_id, "failed", error=message, stage="failed", progress=100,
                                     progress_text=message)
            finally:
                with self._lock:
                    self._events.pop(task_id, None)
                self._queue.task_done()

    def _archive(self, task_id, result):
        archive_started = time.monotonic()
        task = self.get_task(task_id)
        if not task:
            raise RuntimeError("Krea 2 任务状态不存在")
        folder = self.daily_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        archived = []
        metadata = {
            "task_id": task_id, "engine": "krea2-alis-mlx", "revision": self.runtime.status()["revision"],
            "prompt": task["prompt"], "parameters": task.get("params") or {},
            "seed": result.get("seed"), "precision": result.get("precision"),
            "base_model_id": result.get("base_model_id"),
            "base_model_name": result.get("base_model_name"),
            "safety_enabled": result.get("safety_enabled") is True,
            "safety_threshold": result.get("safety_threshold"), "flagged_count": result.get("flagged", 0),
        }
        for index, source in enumerate(result["paths"], 1):
            destination = folder / f"{task_id}_{index}.png"
            temporary = destination.with_suffix(".png.part")
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
            txt = destination.with_suffix(".txt")
            txt.write_text(task["prompt"].strip() + "\n", encoding="utf-8")
            self.write_prompt_sidecar(destination, task["prompt"], txt_path=txt)
            archived.append(destination)
        names = [path.name for path in archived]
        params = dict(task.get("params") or {})
        params.update({"flagged_count": int(result.get("flagged") or 0),
                       "safety_enabled": result.get("safety_enabled") is True,
                       "safety_threshold": result.get("safety_threshold")})
        generation_timing = normalize_generation_timing(result.get("generation_timing") or {})
        if generation_timing.get("local_inference") is True:
            archive_seconds = max(0.0, time.monotonic() - archive_started)
            generation_timing["save_seconds"] = round(
                float(generation_timing.get("save_seconds") or 0) + archive_seconds, 3)
            generation_timing["total_seconds"] = round(
                float(generation_timing.get("total_seconds") or 0) + archive_seconds, 3)
            params["generation_timing"] = generation_timing
            params["duration_seconds"] = generation_timing["total_seconds"]
        metadata["parameters"] = params
        metadata["generation_timing"] = generation_timing
        for index, destination in enumerate(archived, 1):
            destination.with_suffix(".krea2.json").write_text(
                json.dumps({**metadata, "output_index": index}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
        self.update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))
        status = "succeeded_no_telegram"
        text = "Krea 2 生成完成，原图已归档"
        self.update_task(task_id, status, result_file=names[0],
                         result_files=json.dumps(names, ensure_ascii=False), stage="done", progress=100,
                         progress_text=text)
        if task.get("params", {}).get("telegram_enabled"):
            try:
                for path in archived:
                    self.send_document(path, "Krea 2 · MLX 本地生成")
                self.update_task(task_id, "succeeded", result_file=names[0], stage="done", progress=100,
                                 progress_text="Krea 2 生成完成，已发送 Telegram")
            except Exception as exc:
                self.update_task(task_id, "telegram_failed", result_file=names[0], stage="telegram",
                                 progress=100, progress_text="结果已归档，Telegram 发送失败",
                                 error=f"结果已归档，Telegram 发送失败：{exc}")

    def recover(self):
        # Global startup recovery already marks processing tasks stale.  This
        # extra pass handles old queued records from versions that lacked it.
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL:
                self.update_task(task["task_id"], "failed", error="服务已重启，请重新提交 Krea 2 任务",
                                 stage="failed", progress=100, progress_text="服务已重启，请重新提交")

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for event in self._events.values():
                event.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=8)
        self.conversion.close()
        self.runtime.close()
        process = self._prepare_process
        if process and process.poll() is None:
            try:
                os.killpg(process.pid, __import__("signal").SIGTERM)
            except ProcessLookupError:
                pass
