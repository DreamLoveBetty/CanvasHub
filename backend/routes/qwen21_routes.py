"""Qwen 2.1 authenticated route binding; no business logic."""
from .local_image_routes import create_router as _create
from .base import ProtectedRouter
from ..qwen21.contracts import MAX_IMAGE_UPLOAD, MAX_LORA_UPLOAD

def create_router(service):
    base = _create(service, domain="qwen21", label="Qwen 2.1",
                   max_image_upload=MAX_IMAGE_UPLOAD, max_lora_upload=MAX_LORA_UPLOAD)

    def handle(handler, action):
        try:
            body = handler.read_json_body(max_bytes=16 * 1024)
            if not isinstance(body, dict):
                raise ValueError("请求参数必须是对象")
            handler.send_json(action(body))
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 503)
        except OSError:
            handler.send_json({"ok": False, "error": "VAE 本地文件读写失败"}, 500)

    vae = ProtectedRouter({
        ("POST", "/api/qwen21/vae-import"): lambda h: handle(h, service.import_vae),
        ("POST", "/api/qwen21/vae-select"): lambda h: handle(h, service.select_vae),
    })

    class Router:
        def dispatch(self, handler, method, path):
            return vae.dispatch(handler, method, path) or base.dispatch(handler, method, path)

    return Router()
