"""MOSS authenticated routes: an explicit whitelist, with no upload/edit/convert/delete-model action."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from ..moss.contracts import MAX_JSON_BYTES, MAX_LORA_UPLOAD, strict_json_loads
from .base import ProtectedRouter


def _strict_body(handler):
    size = int(handler.headers.get("Content-Length") or 0)
    if size <= 0 or size > MAX_JSON_BYTES:
        raise ValueError("JSON 请求为空或超过 256 KiB")
    raw = handler.rfile.read(size)
    if len(raw) != size:
        raise ValueError("JSON 请求不完整")
    return strict_json_loads(raw)


def _import_lora(service, handler):
    size = int(handler.headers.get("Content-Length") or 0)
    if size <= 0 or size > MAX_LORA_UPLOAD:
        raise ValueError("上传内容为空或超过大小限制")
    name = parse_qs(urlparse(handler.path).query).get("name", ["source"])[0]
    return service.import_lora(handler.rfile, size, name)


def create_router(service):
    def respond(handler, action, code=200):
        try:
            handler.send_json(action(), code)
        except (ValueError, TypeError, KeyError) as error:
            handler.send_json({"ok": False, "error": str(error)}, 400)
        except RuntimeError as error:
            handler.send_json({"ok": False, "error": str(error)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({"ok": False, "error": "MOSS 本地文件读写失败"}, 500)
        except Exception:
            handler.send_json({"ok": False, "error": "MOSS 服务暂不可用，请稍后重试"}, 502)

    def get(action):
        return lambda handler: respond(handler, action)

    def post(action, code=200):
        return lambda handler: respond(handler, lambda: action(_strict_body(handler)), code)

    return ProtectedRouter({
        ("GET", "/api/moss/status"): get(service.status),
        ("GET", "/api/moss/catalog"): get(service.catalog),
        ("GET", "/api/moss/lora-list"): get(service.list_loras),
        ("POST", "/api/moss/prepare"): post(service.prepare, 202),
        ("POST", "/api/moss/model-bind"): post(service.bind_model, 202),
        ("GET", "/api/moss/model-tools"): get(service.model_tools),
        ("POST", "/api/moss/model-inspect"): post(service.inspect_model),
        ("POST", "/api/moss/model-convert"): post(service.convert_model, 202),
        ("POST", "/api/moss/model-convert-cancel"): post(service.cancel_conversion),
        ("POST", "/api/moss/model-delete"): post(service.delete_model),
        ("POST", "/api/moss/layout-compile"): post(service.compile),
        ("POST", "/api/moss/generate"): post(service.submit, 202),
        ("POST", "/api/moss/cancel"): post(lambda body: service.cancel(body.get("task_id"))),
        ("POST", "/api/moss/lora-delete"): post(lambda body: service.delete_lora(body.get("asset_id"))),
        ("POST", "/api/moss/lora-import"): lambda handler: respond(handler, lambda: _import_lora(service, handler)),
    })
