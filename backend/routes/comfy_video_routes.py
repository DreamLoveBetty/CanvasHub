"""Authenticated HTTP adapter for ComfyUI media sources:
POST /api/comfy/upload_video?name=... and POST /api/comfy/upload_audio?name=...

Transport only: the raw file body goes to backend.services.comfy_video.ComfyVideoUploads /
backend.services.comfy_audio.ComfyAudioUploads.
"""
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..services.comfy_audio import MAX_AUDIO_UPLOAD
from ..services.video_upload import MAX_UPLOAD


def _upload_handler(uploads, *, limit, kind):
    def upload(handler):
        try:
            length = int(handler.headers.get('Content-Length') or 0)
            if not 0 < length <= limit:
                raise ValueError(f'{kind}为空或超过 {limit // (1024 * 1024)} MiB')
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
            print(f'❌ ComfyUI {kind}上传失败：{exc}')
            handler.send_json({'error': f'{kind}上传到 ComfyUI 失败：{str(exc)[:200]}'}, 502)

    return upload


def create_router(uploads, audio_uploads=None):
    routes = {('POST', '/api/comfy/upload_video'): _upload_handler(uploads, limit=MAX_UPLOAD, kind='视频')}
    if audio_uploads is not None:
        routes[('POST', '/api/comfy/upload_audio')] = _upload_handler(audio_uploads, limit=MAX_AUDIO_UPLOAD, kind='音频')
    return ProtectedRouter(routes)
