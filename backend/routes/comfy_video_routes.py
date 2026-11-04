"""Authenticated HTTP adapter for ComfyUI video sources (POST /api/comfy/upload_video?name=...).

Transport only: the raw file body goes to backend.services.comfy_video.ComfyVideoUploads.
"""
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..services.video_upload import MAX_UPLOAD


def create_router(uploads):
    def upload(handler):
        try:
            length = int(handler.headers.get('Content-Length') or 0)
            if not 0 < length <= MAX_UPLOAD:
                raise ValueError('视频为空或超过 200 MiB')
            data = handler.rfile.read(length)
            if len(data) != length:
                raise ValueError('上传不完整，请重试')
            name = parse_qs(urlparse(handler.path).query).get('name', [''])[0]
            handler.send_json(uploads.upload(data, name))
        except ValueError as exc:
            handler.send_json({'error': str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            print(f'❌ ComfyUI 视频上传失败：{exc}')
            handler.send_json({'error': f'视频上传到 ComfyUI 失败：{str(exc)[:200]}'}, 502)

    return ProtectedRouter({('POST', '/api/comfy/upload_video'): upload})
