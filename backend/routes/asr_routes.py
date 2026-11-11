"""Authenticated ASR routes: environment status and the user-triggered prepare operation.

Transcription itself is not exposed here; video_edit calls the service's port with a server-made WAV."""
from __future__ import annotations

from .base import ProtectedRouter


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
            handler.send_json({"ok": False, "error": "语音识别本地文件读写失败"}, 500)

    def prepare(handler):
        size = int(handler.headers.get("Content-Length") or 0)
        if size > 4096:
            raise ValueError("请求过大")
        handler.rfile.read(size)  # the body carries no options; drain it for keep-alive
        return service.prepare()

    return ProtectedRouter({
        ("GET", "/api/asr/status"): lambda handler: respond(handler, service.status),
        ("POST", "/api/asr/prepare"): lambda handler: respond(handler, lambda: prepare(handler), 202),
    })
