"""Thin authenticated HTTP adapter for the video_understand domain."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from .artifact_response import send_artifact


def create_router(service):
    def handle(handler, action: str, *, post: bool = False, status_code: int = 200):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [""])[0]
            body = {}
            if post:
                length = int(handler.headers.get("Content-Length") or 0)
                if action == "prepare":
                    if length > 4096:
                        raise ValueError("请求过大")
                    if length > 0:
                        handler.rfile.read(length)
                else:
                    if not 0 < length <= 65536:
                        raise ValueError("请求为空或超过大小限制")
                    data = handler.rfile.read(length)
                    if len(data) != length:
                        raise ValueError("请求体不完整")
                    body = json.loads(data)
                    if not isinstance(body, dict):
                        raise ValueError("请求必须为 JSON 对象")

            if action == "status":
                result = service.status()
            elif action == "prepare":
                result = service.prepare(body)
            elif action == "submit":
                result = service.submit(body)
            elif action == "job":
                result = service.job(first("id"))
            elif action == "cancel":
                result = service.cancel(body.get("id"))
            elif action == "artifact":
                send_artifact(handler, service.store.artifact(first("id"), first("name")))
                return
            else:
                raise ValueError("未知操作")
            handler.send_json(result, status_code)
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 400)
        except FileNotFoundError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 404)
        except RuntimeError as exc:
            handler.send_json({"ok": False, "error": str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({"ok": False, "error": "视频理解本地存储读写失败"}, 500)

    return ProtectedRouter(
        {
            ("GET", "/api/video_understand/status"): lambda h: handle(h, "status"),
            ("GET", "/api/video_understand/job"): lambda h: handle(h, "job"),
            ("GET", "/api/video_understand/artifact"): lambda h: handle(h, "artifact"),
            ("POST", "/api/video_understand/prepare"): lambda h: handle(h, "prepare", post=True, status_code=202),
            ("POST", "/api/video_understand/submit"): lambda h: handle(h, "submit", post=True),
            ("POST", "/api/video_understand/cancel"): lambda h: handle(h, "cancel", post=True),
        }
    )
