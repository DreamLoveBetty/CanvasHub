"""Qwen orchestration: model ports, ordered uploads, tasks and original archive."""
from __future__ import annotations

import atexit
import json
from pathlib import Path
import shutil
import threading
import uuid

from ..local_image.archiving import archive_pngs
from ..local_image.preparation import Preparation
from ..local_image.task_queue import ImageTaskQueue
from ..local_image.uploads import ImageUploads
from .contracts import (DEFAULT_MODEL_ID, ENGINE, REVISION, TASK_TYPE, TERMINAL,
                        catalog, normalize_job, normalize_model_id)
from .profiles import ADAPTERS, DEFAULT_PRESET, PRESETS, canonical_preset
from .lora_store import LoRAStore
from .model_store import BaseModelStore
from .vae_store import VaeStore


class Service:
    def __init__(self, root, component, runtime, *, create_task, get_task, get_all_tasks,
                 update_task, update_task_status, update_task_fields, daily_output_dir,
                 write_prompt_sidecar, send_document, model_store=None, conversion_service=None):
        self.root, self.component, self.runtime = Path(root).resolve(), Path(component).resolve(), runtime
        self.create_task, self.get_task, self.get_all_tasks = create_task, get_task, get_all_tasks
        self.update_task, self.update_task_status, self.update_task_fields = update_task, update_task_status, update_task_fields
        self.daily_output_dir, self.write_prompt_sidecar, self.send_document = daily_output_dir, write_prompt_sidecar, send_document
        self.models = model_store or BaseModelStore(self.root / "assets", self.component)
        self.vaes = VaeStore(self.root / "assets")
        self.loras = LoRAStore(self.root / "assets")
        self.uploads = ImageUploads(self.root / "uploads")
        self.preparation = Preparation(self.component, "QWEN21_EVENT ", "Qwen 2.1")
        if conversion_service is None:
            from .conversion_service import ConversionService
            conversion_service = ConversionService(self.root, self.component, runtime, self.models)
        self.conversion = conversion_service
        self.queue = ImageTaskQueue(self.root, runtime, get_task=get_task, update_task=update_task,
                                    update_task_status=update_task_status, publish=self._archive,
                                    label="Qwen 2.1", terminal=TERMINAL)
        self._model_lock = threading.RLock()
        self._closed = False
        atexit.register(self.close)

    def status(self):
        result = self.runtime.status()
        models = self.models.list()
        ready = bool(result.get("environment_ready") and result.get("source_ready")
                     and any(model.get("ready") for model in models))
        if not any(model.get("ready") for model in models):
            result["reasons"] = list(result.get("reasons") or []) + ["Qwen Base / 共享视觉编码器尚未准备"]
        return {"ok": True, **result, "ready": ready, "models": models,
                **self.models.selection(), "preparation": self.preparation.status(),
                "lora_count": len(self.loras.list())}

    def catalog(self):
        result = catalog(self.models.list())
        selection = self.models.selection()
        result["defaults"]["base_model_id"] = selection["default_model_id"]
        return {"ok": True, **result, **selection}

    def model_tools(self):
        return {"ok": True, **self.models.paths(), "models": self.models.list(),
                **self.models.selection(),
                "vae": self.vaes.status(),
                "import_models": self.models.list_imports(), "conversion": self.conversion.status(),
                "runtime": self.runtime.status(), "preparation": self.preparation.status()}

    def import_vae(self, body):
        with self._model_lock:
            return {"ok": True, "vae": self.vaes.import_file(body.get("source_path"), body.get("name", ""))}

    def select_vae(self, body):
        with self._model_lock:
            return {"ok": True, "vae": self.vaes.select(body.get("vae_id"))}

    def inspect_model(self, body):
        return {"ok": True, "inspection": self.conversion.inspect(body)}

    def convert_model(self, body):
        status = self.runtime.status()
        if not status.get("environment_ready") or not status.get("source_ready"):
            raise RuntimeError("请先准备 Qwen 固定版本源码与共享依赖")
        if self.preparation.status().get("status") == "running":
            raise RuntimeError("Qwen 模型正在准备，请完成后再转换")
        with self._model_lock:
            return {"ok": True, "conversion": self.conversion.start(body)}

    def cancel_model_conversion(self):
        return {"ok": True, "conversion": self.conversion.cancel()}

    def _model_in_use(self, model_id):
        return any(task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL
                   and (task.get("params") or {}).get("base_model_id") == model_id
                   for task in self.get_all_tasks(limit=5000))

    def delete_model(self, model_id):
        model_id = normalize_model_id(model_id)
        with self._model_lock:
            if self.preparation.status().get("status") == "running":
                raise RuntimeError("Qwen 模型正在准备，暂不能删除")
            if self.conversion.status().get("status") in {"queued", "waiting", "running"} or self._model_in_use(model_id):
                raise RuntimeError("该 Base 正被生成/转换任务使用，暂不能删除")
            getattr(self.runtime, "close_idle", self.runtime.close)()
            return {"ok": True, "model": self.models.delete(model_id)}

    def upload_image(self, content, filename="reference"):
        return self.uploads.upload(content, filename)

    def list_loras(self):
        return {"ok": True, "loras": self.loras.list(), "scan_errors": self.loras.scan_errors()}

    def import_lora(self, stream, size, filename):
        return {"ok": True, "lora": self.loras.import_stream(stream, size, filename)}

    def delete_lora(self, asset_id):
        from .contracts import normalize_asset_id
        asset_id = normalize_asset_id(asset_id)
        with self._model_lock:
            for task in self.get_all_tasks(limit=5000):
                if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL and any(
                        item.get("asset_id") == asset_id for item in (task.get("params") or {}).get("loras") or []):
                    raise RuntimeError("该 LoRA 正被 Qwen 任务使用")
            return {"ok": True, "lora": self.loras.delete(asset_id)}

    def prepare(self, body):
        with self._model_lock:
            return self._prepare(body)

    def _prepare(self, body):
        body = body if isinstance(body, dict) else {}
        if self.conversion.status().get("status") in {"queued", "waiting", "running"}:
            raise RuntimeError("Qwen 模型正在转换，请完成后再准备")
        model_id = normalize_model_id(body.get("base_model_id") or self.models.selection()["default_model_id"])
        if not any(item["id"] == model_id for item in self.models.list()):
            raise ValueError("选择的 Base 模型已不存在")
        python = self.runtime.python
        if python is None or not python.is_file():
            raise RuntimeError("未找到共享 Python 环境")
        preset = canonical_preset(body.get("preset") or DEFAULT_PRESET)
        if preset not in PRESETS:
            raise ValueError("未知推理预设")
        command = [str(python), "-u", "-m", "backend.qwen21.install", "--component", str(self.component),
                   "--data", str(self.root)]
        if body.get("sources_only") is True:
            command.append("--sources-only")
        else:
            if model_id != DEFAULT_MODEL_ID:
                command.append("--shared-only")
            if preset != "standard":
                command.extend(("--turbo", "--turbo-preset", preset))
        return self.preparation.start(command, Path(__file__).resolve().parents[2],
                                      {"base_model_id": model_id, "preset": preset})

    def submit(self, body):
        with self._model_lock:
            if isinstance(body, dict) and not body.get("base_model_id"):
                body = {**body, "base_model_id": self.models.selection()["default_model_id"]}
            spec = normalize_job(body)
            status = self.runtime.status()
            model = self.models.resolve(spec["base_model_id"])
            vae = self.vaes.resolve()
            if not status.get("environment_ready") or not status.get("source_ready"):
                raise RuntimeError("Qwen 共享环境或固定版本源码尚未就绪")
            adapter_ready = status.get("turbo_adapters", {}).get(spec["preset"], status.get("turbo_ready"))
            if spec["preset"] != "standard" and not adapter_ready:
                raise RuntimeError("Viggle 加速适配器尚未准备")
            resolved, public = [], []
            for item in spec["loras"]:
                if item["asset_id"] in {value["sha256"] for value in ADAPTERS.values()}:
                    raise ValueError("Viggle 加速适配器由预设自动加载，不能重复添加")
                path, meta = self.loras.resolve(item["asset_id"])
                resolved.append({"path": str(path), "scale": item["scale"]})
                public.append({**item, "name": meta.get("name", "LoRA")})
            task_id = "qwen21_" + uuid.uuid4().hex
            directory = self.root / "jobs" / task_id
            directory.mkdir(parents=True, exist_ok=False)
            try:
                references = [self.uploads.copy(token, directory, f"reference_{index + 1}")
                              for index, token in enumerate(spec.pop("reference_upload_tokens"))]
                spec.update(base_model_name=model["name"])
                worker_spec = {**spec, "loras": resolved, "references": references,
                               "vae": vae,
                               "model": {"id": model["id"], "name": model["name"],
                                         "precision": model["precision"], "path": str(model["path"])}}
                params = {key: value for key, value in spec.items() if key != "prompt"}
                params.update(provider=ENGINE, loras=public, main_model=f"Qwen 2.1 · {model['name']}",
                              vae_id=vae["id"], vae_name=vae["name"], vae_sha256=vae["sha256"],
                              vae_format=vae["format"],
                              reference_count=len(references), precision=model["precision"])
                (directory / "submission.json").write_text(json.dumps(worker_spec, ensure_ascii=False, indent=2) + "\n")
                self.queue.enqueue(task_id, worker_spec, lambda: self.create_task(
                    task_id, spec["prompt"], params, status="queued", task_type=TASK_TYPE))
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
        return {"ok": True, "task_id": task_id, "status": "queued", "type": TASK_TYPE}

    def cancel(self, task_id):
        task = self.get_task(str(task_id or ""))
        if not task or task.get("type") != TASK_TYPE:
            raise ValueError("Qwen 任务不存在")
        self.queue.cancel(task["task_id"])
        return {"ok": True, **(self.get_task(task["task_id"]) or task)}

    def _archive(self, task_id, result):
        task = self.get_task(task_id)
        if not task:
            raise RuntimeError("Qwen 任务状态不存在")
        metadata = {"engine": ENGINE, "revision": REVISION,
                    "base_model_id": result.get("base_model_id"), "base_model_name": result.get("base_model_name"),
                    "seed": result.get("seed"), "seeds": result.get("seeds"), "precision": result.get("precision")}
        images, params = archive_pngs(task_id, task, result, directory=self.daily_output_dir(),
                                     write_prompt_sidecar=self.write_prompt_sidecar, metadata=metadata,
                                     suffix=".qwen21.json")
        names = [path.name for path in images]
        self.update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))
        self.update_task(task_id, "succeeded_no_telegram", result_file=names[0], result_files=json.dumps(names),
                         stage="done", progress=100, progress_text="Qwen 2.1 生成完成，原图已归档")
        if params.get("telegram_enabled"):
            try:
                for image in images:
                    self.send_document(image, "Qwen 2.1 · MLX 本地生成")
                self.update_task(task_id, "succeeded", stage="done", progress=100,
                                 progress_text="Qwen 2.1 生成完成，已发送 Telegram")
            except Exception as exc:
                self.update_task(task_id, "telegram_failed", stage="telegram", progress=100,
                                 progress_text="原图已归档，Telegram 发送失败", error=str(exc)[:1000])

    def recover(self):
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL:
                self.update_task(task["task_id"], "failed", error="服务重启，请重新提交 Qwen 任务",
                                 stage="failed", progress=100, progress_text="服务已重启")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.queue.close()
        self.conversion.close()
        self.preparation.close()
        self.runtime.close()
