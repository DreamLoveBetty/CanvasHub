"""绘栾 task orchestration: validation, durable task state and original archiving."""
from __future__ import annotations

import json
import math
import mimetypes
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests

from ..provider_cyimg import CyimgClient


TASK_TYPES = {"image": "cyimg-image", "video": "cyimg-video"}
TERMINAL = {"succeeded", "succeeded_no_telegram", "failed", "telegram_failed", "canceled"}
MAX_UPLOAD = 200 * 1024 * 1024
MAX_OUTPUT = {"image": 64 * 1024 * 1024, "video": 512 * 1024 * 1024}


class CyimgService:
    def __init__(self, *, get_config, create_task, get_task, get_all_tasks, update_task,
                 update_task_status, update_task_fields, daily_output_dir, send_document):
        self.get_config = get_config
        self.create_task = create_task
        self.get_task = get_task
        self.get_all_tasks = get_all_tasks
        self.update_task = update_task
        self.update_task_status = update_task_status
        self.update_task_fields = update_task_fields
        self.daily_output_dir = daily_output_dir
        self.send_document = send_document
        self._uploads = {}
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(8)

    def _client(self):
        return CyimgClient(self.get_config()["api_key"])

    def catalog(self):
        data = self._client().catalog()
        return {"ok": True, "api_key_configured": self.get_config()["api_key_configured"], **data}

    def upload(self, content, filename, mime):
        if not content or len(content) > MAX_UPLOAD:
            raise ValueError("素材为空或超过 200 MB")
        kind = mime.split("/", 1)[0].lower()
        if kind not in {"image", "video", "audio"}:
            raise ValueError("仅支持图像、视频和音频素材")
        suffix = Path(filename or "").suffix.lower()
        suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else mimetypes.guess_extension(mime) or ".bin"
        clean_name = f"cyimg-input-{uuid.uuid4().hex}{suffix}"
        url = self._client().upload(content, clean_name, mime)
        token = uuid.uuid4().hex
        with self._lock:
            self._uploads = {k: v for k, v in self._uploads.items() if v[2] > time.time()}
            self._uploads[token] = (url, kind, time.time() + 3600)
        return {"ok": True, "upload_token": token}

    def _media_url(self, token, kind):
        with self._lock:
            record = self._uploads.get(str(token or ""))
        if not record or record[1] != kind or record[2] < time.time():
            raise ValueError(f"{kind} 素材已过期，请重新上传")
        return record[0]

    def _prepare(self, data):
        if not isinstance(data, dict):
            raise ValueError("请求必须为对象")
        kind = str(data.get("kind") or "")
        if kind not in TASK_TYPES:
            raise ValueError("仅支持绘栾图像或视频任务")
        prompt = str(data.get("prompt") or "").strip()
        if not prompt or len(prompt) > 10000:
            raise ValueError("请输入有效的提示词（不超过 10000 字）")
        model_id = str(data.get("model_id") or "")
        model = next((item for item in self._client().catalog()["models"][kind]
                      if item["id"] == model_id), None)
        if not model:
            raise ValueError("绘栾模型已变化，请刷新目录后重新选择")
        incoming = data.get("parameters") or {}
        if not isinstance(incoming, dict):
            raise ValueError("模型参数必须为对象")
        body = {"task_id": model["task_id"], "channel": model["channel"],
                "model": model["model"], "prompt": prompt}
        for field in model["fields"]:
            name, field_type = field["name"], field["type"]
            if field_type in {"image", "video", "audio"}:
                tokens = data.get(f"{field_type}_upload_tokens") or []
                if not isinstance(tokens, list):
                    raise ValueError("素材列表格式无效")
                urls = [self._media_url(token, field_type) for token in tokens[:field["resource_count"]]]
                if field["required"] and not urls:
                    raise ValueError(f"当前模型需要{field['label']}")
                if urls:
                    if field["resource_count"] > 1:
                        for index, url in enumerate(urls, 1):
                            body[f"{name}{index}"] = url
                    else:
                        body[name] = urls[0]
                continue
            value = incoming.get(name, field["default"])
            if value in (None, ""):
                if field["required"]:
                    raise ValueError(f"请填写{field['label']}")
                continue
            if field_type == "custom_radio":
                allowed = [choice["value"] for choice in field["options"]]
                if value not in allowed and str(value) not in [str(item) for item in allowed]:
                    raise ValueError(f"{field['label']}选项已变化")
            elif field_type == "boolean":
                if not isinstance(value, bool):
                    raise ValueError(f"{field['label']}必须是布尔值")
            elif field_type == "number":
                try:
                    value = float(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{field['label']}必须是数字") from exc
                if not 0 <= value <= 300:
                    raise ValueError(f"{field['label']}超出可用范围")
                value = int(value) if value.is_integer() else value
            elif field_type == "text":
                value = str(value)[:10000]
            body[name] = value
        return kind, prompt, model, body

    def _spawn(self, task_id, body):
        def work():
            try:
                self.run(task_id, body)
            finally:
                self._slots.release()
        threading.Thread(target=work, name=f"cyimg-{task_id[-8:]}", daemon=True).start()

    def submit(self, data):
        if not self.get_config()["api_key_configured"]:
            raise ValueError("请先在设置中填写绘栾 API Key")
        kind, prompt, model, body = self._prepare(data)
        if not self._slots.acquire(blocking=False):
            raise RuntimeError("绘栾并发任务已满，请稍后再试")
        local_id = "cyimg_" + uuid.uuid4().hex
        estimate = model["credit_estimate"]
        for field in model["fields"]:
            if field["type"] == "custom_radio":
                choice = next((item for item in field["options"]
                               if str(item["value"]) == str(body.get(field["name"]))), None)
                extra = str((choice or {}).get("extra_credit") or 0)
                if estimate is not None:
                    try:
                        numeric_extra = float(extra)
                        estimate = estimate + numeric_extra if math.isfinite(numeric_extra) and numeric_extra >= 0 else None
                    except ValueError:
                        estimate = None
        params = {"provider": "cyimg", "kind": kind, "model_id": model["id"],
                  "model_label": model["label"], "credit_estimate": estimate,
                  "parameters": {k: v for k, v in body.items() if k not in {"prompt", "image", "video", "audio"}
                                 and not re.fullmatch(r"(?:image|video|audio)\d+", k)},
                  "telegram_enabled": data.get("telegram_enabled") is True}
        try:
            self.create_task(local_id, prompt, params, status="queued", task_type=TASK_TYPES[kind])
            self._spawn(local_id, body)
        except Exception:
            self._slots.release()
            raise
        return {"ok": True, "task_id": local_id, "status": "queued", "type": TASK_TYPES[kind]}

    def _store_remote_id(self, task_id, remote_id):
        task = self.get_task(task_id)
        params = dict(task.get("params") or {})
        params["remote_task_id"] = remote_id
        self.update_task_fields(task_id, params=json.dumps(params, ensure_ascii=False))

    @staticmethod
    def _result_urls(payload):
        primary = payload.get("original_result_url") or payload.get("result")
        urls = [primary] if isinstance(primary, str) and primary else []
        for item in payload.get("extra_results") or []:
            if isinstance(item, str) and item and item not in urls:
                urls.append(item)
        return urls

    @staticmethod
    def _extension(kind, content_type, url):
        content_type = str(content_type or "").split(";", 1)[0].lower()
        allowed = {"image": {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/avif": ".avif"},
                   "video": {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm"}}[kind]
        if content_type in allowed:
            return allowed[content_type]
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in allowed.values():
            return suffix
        raise RuntimeError("绘栾结果类型与所选节点不符")

    def _archive(self, task_id, task, payload, client):
        kind = task["params"]["kind"]
        urls = self._result_urls(payload)
        if not urls:
            raise RuntimeError("绘栾任务已完成但没有结果地址")
        folder = self.daily_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, url in enumerate(urls[:8], 1):
            content, mime, resolved = client.download(url, MAX_OUTPUT[kind])
            ext = self._extension(kind, mime, resolved)
            path = folder / f"cyimg_{task_id}_{index}{ext}"
            temp = path.with_suffix(path.suffix + ".part")
            temp.write_bytes(content)
            temp.replace(path)
            path.with_suffix(".txt").write_text(task["prompt"] + "\n", encoding="utf-8")
            paths.append(path)
        return paths

    def run(self, task_id, body=None):
        try:
            task = self.get_task(task_id)
            if not task or task["status"] in TERMINAL:
                return
            client = self._client()
            remote_id = (task.get("params") or {}).get("remote_task_id")
            if not remote_id:
                if body is None:
                    raise RuntimeError("服务重启时提交结果未确认；请到绘栾任务历史核对，避免重复扣费")
                # Never replay this POST after an ambiguous network failure.
                remote_id = client.submit(body)
                self._store_remote_id(task_id, remote_id)
            deadline = time.monotonic() + self.get_config()["task_timeout_seconds"]
            failures = 0
            while time.monotonic() < deadline:
                if (self.get_task(task_id) or {}).get("status") == "canceled":
                    return
                try:
                    result = client.status(remote_id)
                    failures = 0
                except (requests.RequestException, RuntimeError):
                    failures += 1
                    if failures >= 5:
                        raise RuntimeError("绘栾状态查询连续失败；任务 ID 已保留，请在站点核对")
                    time.sleep(3)
                    continue
                state = str(result.get("status") or "").lower()
                if state in {"failed", "failure", "error", "cancelled", "canceled"}:
                    result_reason = result.get("result") if isinstance(result.get("result"), str) else ""
                    raise RuntimeError(str(
                        result.get("error_message")
                        or result.get("message")
                        or result_reason
                        or "绘栾生成失败"
                    )[:300])
                if state in {"completed", "success", "succeeded"}:
                    self.update_task_status(task_id, "queued", "下载并归档原始结果", stage="archiving", progress=90)
                    task = self.get_task(task_id)
                    paths = self._archive(task_id, task, result, client)
                    if (self.get_task(task_id) or {}).get("status") == "canceled":
                        return
                    names = [path.name for path in paths]
                    self.update_task(task_id, "succeeded_no_telegram", result_file=names[0],
                                     result_files=json.dumps(names, ensure_ascii=False),
                                     stage="done", progress=100, progress_text="绘栾生成完成，原始文件已归档")
                    if task["params"].get("telegram_enabled"):
                        try:
                            for path in paths:
                                self.send_document(path, f"绘栾 · {task['params'].get('model_label', '')}"[:100])
                            self.update_task(task_id, "succeeded", result_file=names[0], stage="done", progress_text="绘栾生成完成，已发送 Telegram")
                        except Exception as exc:
                            self.update_task(task_id, "telegram_failed", result_file=names[0],
                                             error=f"结果已归档，Telegram 发送失败：{exc}", stage="telegram")
                    return
                self.update_task_status(task_id, "queued", str(result.get("message") or "绘栾正在处理")[:200],
                                        stage=state or "processing", progress=15 if state in {"queued", "pending"} else 45)
                time.sleep(3)
            raise RuntimeError("绘栾任务等待超时；任务 ID 已保留，请在站点核对")
        except Exception as exc:
            if (self.get_task(task_id) or {}).get("status") != "canceled":
                message = str(exc)[:400] or "绘栾任务失败"
                self.update_task(task_id, "failed", error=message, stage="failed", progress_text=message, progress=100)

    def recover(self):
        """Resume known remote tasks; never resubmit an unconfirmed POST."""
        pending = []
        for task in self.get_all_tasks(limit=5000):
            if task.get("type") not in TASK_TYPES.values() or task.get("status") in TERMINAL:
                continue
            remote_id = (task.get("params") or {}).get("remote_task_id")
            if not remote_id:
                self.update_task(task["task_id"], "failed", error="提交结果未确认；请在绘栾任务历史核对，避免重复扣费")
            else:
                pending.append(task["task_id"])
        # Bounded poller count; no extra service process or release-local state.
        for index in range(min(4, len(pending))):
            batch = pending[index::4]
            threading.Thread(target=lambda ids=batch: [self.run(task_id) for task_id in ids],
                             name=f"cyimg-recover-{index}", daemon=True).start()
