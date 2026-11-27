"""Authenticated HTTP adapter for Kandinsky ImageSR 2.0."""
from __future__ import annotations

import uuid

from .base import ProtectedRouter
from ..kandinsky_sr.contracts import normalize_model, normalize_options


def create_router(service, *, create_task, process_task, attach_lineage):
    def status(handler):
        handler.send_json(service.status())

    def prepare(handler):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            if length > 4096:
                raise ValueError("请求过大")
            if length > 0:
                handler.rfile.read(length)
            handler.send_json(service.prepare(), 202)
        except ValueError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 503)

    def run(handler):
        try:
            data = handler.read_json_body(max_bytes=64 * 1024 * 1024)
            if not isinstance(data, dict):
                raise ValueError("请求必须为对象")
            images = data.get("images")
            if not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], str):
                raise ValueError("请连接一张图片到 Kandinsky SR 节点")
            if not images[0].startswith("data:image/"):
                raise ValueError("Kandinsky SR 需要上传图片数据")
            model = normalize_model(data.get("model"))
            options = normalize_options(data.get("options"))
            readiness = service.status()
            if not readiness.get("ready"):
                reasons = readiness.get("reasons") or []
                detail = reasons[0] if reasons else "Kandinsky SR 环境或模型尚未准备"
                handler.send_json({"error": detail}, 409)
                return
            prompt = str(data.get("prompt") or "Kandinsky SR 2.0 超分")[:2000]
            params = {
                "model": model,
                "kandinsky_sr": options,
                "archive_enabled": True,
                "telegram_enabled": data.get("telegram_enabled") is True,
            }
            attach_lineage(params, data)
            task_id = "kandinsky_sr_" + uuid.uuid4().hex
            create_task(task_id, prompt, params, status="queued", task_type="kandinsky_sr")
            if handler.start_generation_task(task_id, process_task, (task_id, prompt, images[0], params)):
                handler.send_json(
                    {
                        "task_id": task_id,
                        "status": "queued",
                        "type": "kandinsky_sr",
                        "message": "Kandinsky SR 任务已提交",
                    },
                    202,
                )
        except ValueError as exc:
            handler.send_json({"error": str(exc)}, 400)

    return ProtectedRouter(
        {
            ("GET", "/api/kandinsky_sr/status"): status,
            ("POST", "/api/kandinsky_sr/prepare"): prepare,
            ("POST", "/api/kandinsky_sr/run"): run,
        }
    )
