"""Authenticated JSON transport for the independent 绘栾 generation domain."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..services.cyimg_generation import MAX_UPLOAD


def create_router(service):
    def handle(handler, action):
        try:
            if action == "catalog":
                handler.send_json(service.catalog())
                return
            if action == "upload":
                size = int(handler.headers.get("Content-Length") or 0)
                if size <= 0 or size > MAX_UPLOAD:
                    raise ValueError("素材为空或超过 200 MB")
                content = handler.rfile.read(size)
                if len(content) != size:
                    raise ValueError("素材上传不完整")
                name = parse_qs(urlparse(handler.path).query).get("name", ["source"])[0]
                mime = str(handler.headers.get("Content-Type") or "application/octet-stream")
                handler.send_json(service.upload(content, name, mime))
                return
            if action == "submit":
                body = handler.read_json_body(max_bytes=64 * 1024)
                response = service.submit(body)
                handler.send_json(response, 202)
                return
            raise ValueError("未知绘栾操作")
        except (ValueError, TypeError) as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            handler.send_json({"ok": False, "error": "绘栾服务暂不可用，请稍后重试"}, 502)

    return ProtectedRouter({
        ("GET", "/api/cyimg/catalog"): lambda h: handle(h, "catalog"),
        ("POST", "/api/cyimg/upload"): lambda h: handle(h, "upload"),
        ("POST", "/api/cyimg/submit"): lambda h: handle(h, "submit"),
    })
