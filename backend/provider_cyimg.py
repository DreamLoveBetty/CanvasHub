"""Official 绘栾 task API adapter and live model-catalog normalization.

No Canvas, database, or local storage dependency belongs in this module.
"""
from __future__ import annotations

import ipaddress
import json
import math
import socket
import threading
import time
from urllib.parse import quote, urljoin, urlparse

import requests


TASK_URL = "https://task.cyimg.cn/backend/api/image_tasks.php"
SITE_URL = "https://cyimg.cn"
TICKET_URL = SITE_URL + "/backend/api/canvas_llm_ticket.php?service=task&public_config=1"
UPLOAD_URL = SITE_URL + "/backend/api/upload_file.php"
CATALOG_TTL = 300
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
_cache_lock = threading.Lock()
_cache = {"at": 0.0, "catalog": None}
MODEL_TASKS = (("shizhuang", "image"), ("i2v", "video"),
               ("seedance", "video"), ("Minimax", "video"))


def _numeric_credit(value):
    """Percentage-based tariffs are not safely representable as a flat estimate."""
    try:
        number = float(value or 0)
        return number if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError):
        return None


def _message(payload, fallback):
    message = str(payload.get("message") or payload.get("error_message") or fallback)[:300]
    return message if message.lower() not in {"true", "false"} else fallback


def _json(response, fallback):
    try:
        value = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise RuntimeError(f"绘栾响应不是 JSON（HTTP {response.status_code}）") from exc
    if not isinstance(value, dict):
        raise RuntimeError("绘栾响应格式无效")
    if not response.ok or value.get("error") is True:
        raise RuntimeError(_message(value, f"{fallback}（HTTP {response.status_code}）"))
    return value


def _fields_for_channel(parameters, channel):
    result = []
    seen = set()
    for raw in parameters:
        # API submissions use public parameter names. api_target is an internal
        # upstream mapping (e.g. model -> mode/model_code), not a second field.
        key = str(raw.get("name_en") or raw.get("name") or "").strip()
        channels = raw.get("api_channel") or []
        if channels and channel not in channels or not key or key in {"model", "prompt"}:
            continue
        if key in seen:
            continue
        seen.add(key)
        kind = str(raw.get("type") or "text")
        if kind not in {"image", "video", "audio", "custom_radio", "number", "boolean", "text"}:
            continue
        options = [
            {"label": str(item.get("label") or item.get("value") or ""),
             "value": item.get("value"), "extra_credit": item.get("extraCredit") or 0}
            for item in raw.get("options") or [] if isinstance(item, dict) and item.get("value") is not None
        ]
        result.append({"name": key, "label": str(raw.get("name") or key), "type": kind,
                       "required": bool(raw.get("required")), "default": raw.get("default"),
                       "options": options, "resource_count": int(raw.get("resource_count") or 1),
                       "visible": raw.get("visible") is not False})
    return result


def normalize_catalog(payload):
    """Keep channel and model together: the same model value occurs on many routes."""
    configs = payload.get("configs") or {}
    models = {"image": [], "video": []}
    for task_id, kind in MODEL_TASKS:
        config = configs.get(task_id) or {}
        if not config.get("h5_enabled"):
            continue
        parameters = config.get("parameters") or []
        for raw in parameters:
            if raw.get("name_en") != "model":
                continue
            for channel in raw.get("api_channel") or []:
                for option in raw.get("options") or []:
                    model = str(option.get("value") or "").strip()
                    if not model:
                        continue
                    ident = f"{task_id}::{channel}::{model}"
                    if any(item["id"] == ident for item in models[kind]):
                        continue
                    base_cost = _numeric_credit(config.get("creditCost"))
                    model_extra = _numeric_credit(option.get("extraCredit"))
                    models[kind].append({
                        "id": ident, "task_id": task_id, "channel": channel, "model": model,
                        "label": str(option.get("label") or model),
                        "credit_estimate": base_cost + model_extra
                        if base_cost is not None and model_extra is not None else None,
                        "fields": _fields_for_channel(parameters, channel),
                    })
    if not models["image"] or not models["video"]:
        raise RuntimeError("绘栾模型目录缺少图像或视频配置")
    return {"models": models, "fetched_at": int(time.time())}


def _validate_public_https(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("绘栾结果地址无效")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("绘栾结果地址不是公网 HTTPS")
    try:
        literal_address = ipaddress.ip_address(host)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise ValueError("绘栾结果地址不是公网 HTTPS")
    try:
        addresses = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise ValueError("绘栾结果域名无法解析") from exc
    # Local proxy/TUN DNS can map public domains to 198.18/15 fake IPs.
    # Keep private destinations blocked, including literal fake-IP URLs.
    if not addresses:
        raise ValueError("绘栾结果地址不是公网 HTTPS")
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if not address.is_global and address not in PROXY_FAKE_IP_NETWORK:
            raise ValueError("绘栾结果地址不是公网 HTTPS")
    return parsed.geturl()


class CyimgClient:
    def __init__(self, api_key="", session=None):
        self.api_key = str(api_key or "").strip()
        self.session = session or requests.Session()
        self.session.trust_env = False

    def _headers(self):
        return {"X-API-Key": self.api_key} if self.api_key else {}

    def catalog(self, force=False):
        now = time.monotonic()
        with _cache_lock:
            if not force and _cache["catalog"] and now - _cache["at"] < CATALOG_TTL:
                return _cache["catalog"]
        response = None
        if self.api_key:
            try:
                response = self.session.get(TASK_URL, params={"action": "configs", "platform": "h5"},
                                            headers=self._headers(), timeout=20)
                catalog = normalize_catalog(_json(response, "绘栾目录读取失败"))
                with _cache_lock:
                    _cache.update(at=now, catalog=catalog)
                return catalog
            except (requests.RequestException, RuntimeError, ValueError):
                pass
        # Public config is available through the site's short-lived ticket. This
        # fallback is also needed when an API Key can generate but not read configs.
        try:
            ticket = _json(self.session.post(TICKET_URL, json={}, timeout=15), "绘栾目录票据获取失败")
            token = ticket.get("ticket") or (ticket.get("data") or {}).get("ticket")
            if not token:
                raise RuntimeError("绘栾未返回目录票据")
            response = self.session.get(TASK_URL, params={"action": "configs", "platform": "h5"},
                headers={"X-Canvas-Llm-Ticket": token, "X-Site-Page": "/api_docs.php", "Origin": SITE_URL}, timeout=20)
            catalog = normalize_catalog(_json(response, "绘栾目录读取失败"))
        except Exception:
            with _cache_lock:
                if _cache["catalog"]:
                    return _cache["catalog"]
            raise
        with _cache_lock:
            _cache.update(at=now, catalog=catalog)
        return catalog

    def upload(self, content, filename, mime):
        if not self.api_key:
            raise ValueError("请先在设置中填写绘栾 API Key")
        response = self.session.post(UPLOAD_URL, headers=self._headers(),
            files={"file": (filename, content, mime)}, timeout=120)
        payload = _json(response, "绘栾素材上传失败")
        value = (payload.get("data") or {}).get("file_url") or payload.get("file_url")
        if not isinstance(value, str) or not value:
            raise RuntimeError("绘栾上传成功但未返回素材地址")
        url = urljoin(SITE_URL + "/", value)
        if not url.startswith(SITE_URL + "/"):
            _validate_public_https(url)
        return url

    def submit(self, body):
        if not self.api_key:
            raise ValueError("请先在设置中填写绘栾 API Key")
        response = self.session.post(TASK_URL, params={"action": "generate"},
            headers=self._headers(), json=body, timeout=45)
        payload = _json(response, "绘栾任务提交失败")
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError("绘栾未返回任务 ID；请检查站点任务历史，避免重复扣费")
        return task_id

    def status(self, task_id):
        response = self.session.get(TASK_URL, params={"action": "task_status", "task_id": task_id},
            headers=self._headers(), timeout=30)
        return _json(response, "绘栾任务状态查询失败")

    def download(self, url, max_bytes):
        url = _validate_public_https(url)
        response = self.session.get(url, stream=True, allow_redirects=False, timeout=(15, 90))
        if response.is_redirect:
            location = response.headers.get("Location")
            response.close()
            url = _validate_public_https(urljoin(url, location or ""))
            response = self.session.get(url, stream=True, allow_redirects=False, timeout=(15, 90))
        response.raise_for_status()
        data = bytearray()
        try:
            for chunk in response.iter_content(1024 * 1024):
                data.extend(chunk)
                if len(data) > max_bytes:
                    raise ValueError("绘栾结果文件过大")
        finally:
            response.close()
        if not data:
            raise RuntimeError("绘栾结果文件为空")
        return bytes(data), response.headers.get("Content-Type", ""), url
