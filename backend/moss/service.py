"""MOSS orchestration: compile, admission, tasks and publication. No HTTP and no MLX."""
from __future__ import annotations

import atexit
import copy
import hashlib
import json
from pathlib import Path
import threading
import uuid

from ..local_image.preparation import Preparation
from ..local_image.task_queue import ImageTaskQueue
from . import environment
from .artifacts import publish_artifacts
from .contracts import (DEFAULT_MODEL_ID, ENGINE, MAX_TOKENS, PRESETS, TASK_TYPE, TERMINAL, catalog, check_fields,
                        normalize_asset_id, normalize_compile, normalize_job)
from .environment import PREFIX
from .layout import compile_layout, import_draft
from .base_library import BaseLibrary
from .conversion_service import ConversionService
from .lora_store import LoRAStore
from .model_store import ModelStore
from .runtime import worker_spec


def _text_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_value(job, source):
    """Text a trace entry claims to hash. Matching proves content only, never which node supplied it."""
    if source["field"] == "prompt":
        return job["prompt"]
    draft = job["layout_draft"] or {}
    for item in draft.get("items") or draft.get("panels") or []:
        if item.get("id") == source["target_id"]:
            return item.get(source["field"])
    return None


def _check_text_sources(job):
    for source in job["text_sources"]:
        value = _source_value(job, source)
        if not isinstance(value, str) or _text_hash(value) != source["content_hash"]:
            raise ValueError(f"文本来源与提交内容不一致：{source['target_id']}")


class Service:
    def __init__(self, root, component, runtime, *, create_task, get_task, get_all_tasks, update_task,
                 update_task_status, update_task_fields, daily_output_dir, write_prompt_sidecar, send_document,
                 publisher=publish_artifacts, model_store=None, lora_store=None, preparation=None):
        self.root, self.component, self.runtime = Path(root).resolve(), Path(component).resolve(), runtime
        self.create_task, self.get_task, self.get_all_tasks = create_task, get_task, get_all_tasks
        self.update_task, self.update_task_fields = update_task, update_task_fields
        self.daily_output_dir, self.write_prompt_sidecar = daily_output_dir, write_prompt_sidecar
        self.send_document, self.publisher = send_document, publisher
        self.models = model_store or ModelStore(self.root, environment.assets_dir(self.component))
        self.loras = lora_store or LoRAStore(self.root)
        self.preparation = preparation or Preparation(self.component, PREFIX, "MOSS")
        self.runtime.model_store = self.models
        self.bases = BaseLibrary(self.root, self.models)
        self.conversion = ConversionService(self.root, self.component, runtime, self.bases)
        self.queue = ImageTaskQueue(self.root, runtime, get_task=get_task, update_task=update_task,
                                    update_task_status=update_task_status, publish=self._publish,
                                    label="MOSS", terminal=TERMINAL)
        self._lock = threading.RLock()
        self._seen_operation = None
        self._closed = False
        atexit.register(self.close)

    def _active_tasks(self):
        return [task for task in self.get_all_tasks(limit=5000)
                if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL]

    def _operation_running(self):
        return self.preparation.status().get("status") == "running"

    def status(self):
        operation = self.preparation.status()
        key = (operation.get("operation_id"), operation.get("status"))
        if key != self._seen_operation:  # A finished prepare must not wait out the status cache.
            self._seen_operation = key
            self.runtime.invalidate_status()
        runtime, model = self.runtime.status(), self.models.public()
        reasons = list(runtime.get("reasons") or [])
        if not model["ready"]:
            reasons.append(f"MOSS 模型未就绪：{model['reason']}")
        return {"ok": True, **runtime, "ready": bool(runtime.get("ready") and model["ready"]), "reasons": reasons,
                "model": model, "models": self.models.list(), "preparation": operation,
                "lora_count": len(self.loras.list())}

    def catalog(self):
        return {"ok": True, **catalog(self.models.list())}

    def model_tools(self):
        return {"ok": True, **self.bases.paths(), "models": self.models.list(),
                "import_models": self.bases.list_imports(), "conversion": self.conversion.status()}

    def inspect_model(self, body):
        check_fields(body, {"source_path"}, "检查参数")
        return {"ok": True, "inspection": self.conversion.inspect(body)}

    def convert_model(self, body):
        check_fields(body, {"source_path", "model_name"}, "转换参数")
        return {"ok": True, "conversion": self.conversion.start(body)}

    def cancel_conversion(self, _body):
        return {"ok": True, "conversion": self.conversion.cancel()}

    def delete_model(self, body):
        check_fields(body, {"model_id"}, "删除参数")
        with self._lock:
            if any((task.get("params") or {}).get("base_model_id") == body.get("model_id")
                   for task in self._active_tasks()):
                raise RuntimeError("该 Base 正被 MOSS 任务使用")
            self.bases.delete(body.get("model_id"))
        return {"ok": True}

    def _start_operation(self, kind, arguments):
        with self._lock:
            if self._active_tasks():
                raise RuntimeError("MOSS 任务进行中，请完成后再操作")
            python = environment.base_python()
            if python is None:
                raise RuntimeError("未找到共享 Python，无法准备 MOSS 环境")
            operation_id = "mossop_" + uuid.uuid4().hex
            command = [str(python), "-u", "-m", "backend.moss.environment", kind, *arguments]
            result = self.preparation.start(command, Path(__file__).resolve().parents[2],
                                            {"operation": kind, "operation_id": operation_id})
            return {**result, "operation_id": result["preparation"]["operation_id"]}

    @staticmethod
    def _source_path(value):
        if not isinstance(value, str) or not Path(value).expanduser().is_absolute():
            raise ValueError("MOSS 源目录必须是绝对路径")
        return value

    def prepare(self, body):
        check_fields(body, {"source_path"}, "准备参数")
        source = body.get("source_path")
        return self._start_operation("prepare", ["--source", self._source_path(source)] if source else [])

    def bind_model(self, body):
        check_fields(body, {"source_path"}, "绑定参数")
        return self._start_operation("bind", [self._source_path(body.get("source_path"))])

    def _budget(self, prompt, negative_prompt=""):
        return self.runtime.inspect_prompt(prompt, negative_prompt, MAX_TOKENS)

    def compile(self, body):
        request = normalize_compile(body)
        fingerprint = request["input_fingerprint"]
        if request["kind"] == "import":
            receipt = import_draft(request["draft_json"])
            return {"ok": True, **receipt, "input_fingerprint": fingerprint}
        compiled = compile_layout(request["mode"], request["width"], request["height"], request["layout_draft"],
                                  request["prompt"])
        return {"ok": True, "kind": "compiled", "compiled": compiled, "token_budget": self._budget(compiled["prompt"], request["negative_prompt"]),
                "input_fingerprint": fingerprint,
                "model_fingerprint": self.models.public(request["base_model_id"]).get("fingerprint")}

    def list_loras(self):
        return {"ok": True, "loras": self.loras.list(), "scan_errors": self.loras.scan_errors()}

    def import_lora(self, stream, size, filename):
        return {"ok": True, "lora": self.loras.import_stream(stream, size, filename)}

    def delete_lora(self, asset_id):
        asset_id = normalize_asset_id(asset_id)
        with self._lock:
            if any(item.get("asset_id") == asset_id for task in self._active_tasks()
                   for item in (task.get("params") or {}).get("loras") or []):
                raise RuntimeError("该 LoRA 正被 MOSS 任务使用")
            return {"ok": True, "lora": self.loras.delete(asset_id)}

    def _require_ready(self, model_id):
        if self._operation_running():
            raise RuntimeError("MOSS 正在准备或绑定，请完成后再生成")
        status = self.runtime.status()
        if not status.get("ready"):
            raise RuntimeError((status.get("reasons") or ["MOSS 环境尚未就绪"])[0])
        try:
            return self.models.resolve(model_id)
        except ValueError as error:
            raise RuntimeError(str(error)) from error

    def _require_budget(self, prompt, negative_prompt=""):
        budget = self._budget(prompt, negative_prompt)
        if not budget.get("checked"):
            raise RuntimeError(budget.get("reason") or "token 预算未检查")
        if not budget.get("valid"):
            raise ValueError(budget.get("reason") or "提示词超过 token 上限")
        return budget

    def _model_label(self, job):
        preset = PRESETS[job["preset"]]["label"]
        if job["base_model_id"] == DEFAULT_MODEL_ID:
            return f"MOSS · {preset}"
        return f"MOSS · {self.models.public(job['base_model_id']).get('label')} · {preset}"

    def _params(self, job, compiled, model, loras, budget):
        snapshot = copy.deepcopy({key: value for key, value in job.items() if key != "prompt"})
        return {**snapshot, "provider": ENGINE, "raw_prompt": job["prompt"], "loras": loras,
                "main_model": self._model_label(job), "prompt_hash": compiled["prompt_hash"],
                "geometry_spec": copy.deepcopy(compiled["geometry_spec"]), "geometry_hash": compiled["geometry_hash"],
                "compile_warnings": compiled["warnings"], "model_fingerprint": model.fingerprint,
                "token_budget": budget}

    def submit(self, body):
        job = normalize_job(body)
        _check_text_sources(job)
        compiled = compile_layout(job["mode"], job["width"], job["height"], job["layout_draft"], job["prompt"])
        with self._lock:
            model = self._require_ready(job["base_model_id"])
            budget = self._require_budget(compiled["prompt"], job["negative_prompt"])
            resolved = [self.loras.resolve(item["asset_id"]) for item in job["loras"]]
            public = [{**item, "name": meta.get("name", "LoRA")} for item, (_, meta) in zip(job["loras"], resolved)]
            task_id = "moss_" + uuid.uuid4().hex
            directory = self.root / "jobs" / task_id
            directory.mkdir(parents=True, exist_ok=False)
            spec = worker_spec(copy.deepcopy(job), model, resolved, compiled["prompt"], state_root=self.root)
            params = self._params(job, compiled, model, public, budget)
            try:
                self.queue.enqueue(task_id, spec, lambda: self.create_task(
                    task_id, compiled["prompt"], params, status="queued", task_type=TASK_TYPE))
            except Exception:
                directory.rmdir()
                raise
        return {"ok": True, "task_id": task_id, "status": "queued", "type": TASK_TYPE, "seed": job["seed"]}

    def _record(self, task_id, outcome):
        self.update_task_fields(task_id, params=json.dumps(outcome["params"], ensure_ascii=False))
        self.update_task(task_id, outcome["status"], result_file=outcome["result_file"],
                         result_files=json.dumps(outcome["result_files"]), stage="done", progress=100,
                         progress_text="MOSS 生成完成，原图已归档")

    def _publish(self, task_id, result):
        task = self.get_task(task_id)
        if not task:
            raise RuntimeError("MOSS 任务状态不存在")
        outcome = self.publisher(task_id, task, result, job_dir=self.root / "jobs" / task_id,
                                 daily_output_dir=self.daily_output_dir,
                                 write_prompt_sidecar=self.write_prompt_sidecar, send_document=self.send_document,
                                 on_archived=lambda archived: self._record(task_id, archived))
        if not outcome["published"]:
            return
        if outcome["status"] == "succeeded":
            self.update_task(task_id, "succeeded", stage="done", progress=100,
                             progress_text="MOSS 生成完成，已发送 Telegram")
        elif outcome["status"] == "telegram_failed":
            self.update_task(task_id, "telegram_failed", stage="telegram", progress=100,
                             progress_text="原图已归档，Telegram 发送失败", error=outcome["telegram_error"])
        for path in result.get("paths") or []:
            Path(path).unlink(missing_ok=True)

    def cancel(self, task_id):
        task = self.get_task(str(task_id or ""))
        if not task or task.get("type") != TASK_TYPE:
            raise ValueError("MOSS 任务不存在")
        self.queue.cancel(task["task_id"])
        return {"ok": True, **(self.get_task(task["task_id"]) or task)}

    def recover(self):
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") == TASK_TYPE and task.get("status") not in TERMINAL:
                self.update_task(task["task_id"], "failed", error="服务重启，请重新提交 MOSS 任务",
                                 stage="failed", progress=100, progress_text="服务已重启")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.queue.close()
        self.conversion.close()
        self.preparation.close()
        self.runtime.close()
