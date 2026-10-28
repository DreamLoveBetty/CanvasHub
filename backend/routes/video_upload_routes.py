"""Authenticated HTTP adapter for canvas video-node uploads (POST /api/video/upload?name=...).

Transport only: the raw file body goes to backend.services.video_upload, which owns validation and storage.
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
        except OSError:
            handler.send_json({'error': '视频保存失败，请检查归档目录'}, 500)

    return ProtectedRouter({('POST', '/api/video/upload'): upload})
