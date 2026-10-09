"""Authenticated local-image HTTP adapter with explicitly bound domain limits."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter


def create_router(service, *, domain, label, max_image_upload, max_lora_upload):
    def query(handler, name, default=""):
        return parse_qs(urlparse(handler.path).query).get(name, [default])[0]

    def json_body(handler, limit=256 * 1024):
        return handler.read_json_body(max_bytes=limit)

    def handle(handler, action):
        try:
            if action == "status":
                result = service.status()
            elif action == "catalog":
                result = service.catalog()
            elif action == "lora-list":
                result = service.list_loras()
            elif action == "model-tools":
                result = service.model_tools()
            elif action in {"upload", "lora-import"}:
                maximum = max_image_upload if action == "upload" else max_lora_upload
                size = int(handler.headers.get("Content-Length") or 0)
                if size <= 0 or size > maximum:
                    raise ValueError("上传内容为空或超过大小限制")
                name = query(handler, "name", "source")
                if action == "upload":
                    content = handler.rfile.read(size)
                    if len(content) != size:
                        raise ValueError("参考图上传不完整")
                    result = service.upload_image(content, name)
                else:
                    # LoRAs may approach 2 GB; hash and validate while streaming.
                    result = service.import_lora(handler.rfile, size, name)
            elif action == "prepare":
                result = service.prepare(json_body(handler))
            elif action == "model-inspect":
                result = service.inspect_model(json_body(handler))
            elif action == "model-convert":
                result = service.convert_model(json_body(handler))
                handler.send_json(result, 202)
                return
            elif action == "model-convert-cancel":
                result = service.cancel_model_conversion()
            elif action == "model-delete":
                result = service.delete_model(json_body(handler).get("model_id"))
            elif action == "generate":
                result = service.submit(json_body(handler))
                handler.send_json(result, 202)
                return
            elif action == "cancel":
                result = service.cancel(json_body(handler).get("task_id"))
            elif action == "lora-delete":
                result = service.delete_lora(json_body(handler).get("asset_id"))
            else:
                raise ValueError(f"未知 {label} 操作")
            handler.send_json(result)
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({"ok": False, "error": f"{label} 本地文件读写失败"}, 500)
        except Exception:
            handler.send_json({"ok": False, "error": f"{label} 服务暂不可用，请稍后重试"}, 502)

    routes = {
        ("GET", f"/api/{domain}/status"): lambda h: handle(h, "status"),
        ("GET", f"/api/{domain}/catalog"): lambda h: handle(h, "catalog"),
        ("GET", f"/api/{domain}/lora-list"): lambda h: handle(h, "lora-list"),
        ("GET", f"/api/{domain}/model-tools"): lambda h: handle(h, "model-tools"),
    }
    routes.update({
        ("POST", f"/api/{domain}/prepare"): lambda h: handle(h, "prepare"),
        ("POST", f"/api/{domain}/model-inspect"): lambda h: handle(h, "model-inspect"),
        ("POST", f"/api/{domain}/model-convert"): lambda h: handle(h, "model-convert"),
        ("POST", f"/api/{domain}/model-convert-cancel"): lambda h: handle(h, "model-convert-cancel"),
        ("POST", f"/api/{domain}/model-delete"): lambda h: handle(h, "model-delete"),
        ("POST", f"/api/{domain}/upload"): lambda h: handle(h, "upload"),
        ("POST", f"/api/{domain}/lora-import"): lambda h: handle(h, "lora-import"),
        ("POST", f"/api/{domain}/lora-delete"): lambda h: handle(h, "lora-delete"),
        ("POST", f"/api/{domain}/generate"): lambda h: handle(h, "generate"),
        ("POST", f"/api/{domain}/cancel"): lambda h: handle(h, "cancel"),
    })
    return ProtectedRouter(routes)
