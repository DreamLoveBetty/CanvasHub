"""Thin authenticated HTTP adapter for the video-control domain."""
import json
import mimetypes
from urllib.parse import parse_qs, urlparse
from .base import ProtectedRouter
from .artifact_response import send_artifact
from ..video_control.contracts import MAX_UPLOAD


def create_router(service):
    def handle(handler, action, post=False):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [''])[0]
            body = {}
            if post:
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= (MAX_UPLOAD if action == 'upload' else 16384):
                    raise ValueError('请求为空或超过大小限制')
                data = handler.rfile.read(length)
                if len(data) != length: raise ValueError('请求体不完整')
                if action == 'upload':
                    handler.send_json(service.upload(data, first('name'))); return
                body = json.loads(data)
                if not isinstance(body, dict): raise ValueError('请求必须为对象')
            if action == 'status': result = service.status()
            elif action == 'submit': result = service.submit(body)
            elif action == 'job': result = service.job(first('id'))
            elif action == 'cancel': result = service.cancel(body.get('id'))
            elif action == 'source':
                path = service.store.asset(first('id'))
                info = json.loads(path.with_suffix('.json').read_text())
                mime = mimetypes.guess_type(info.get('name', ''))[0]
                send_artifact(handler, path, mime if mime and mime.startswith('video/') else 'video/mp4'); return
            elif action == 'artifact':
                send_artifact(handler, service.store.artifact(first('id'), first('name'))); return
            handler.send_json(result)
        except (ValueError, TypeError, KeyError) as exc: handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc: handler.send_json({'error': str(exc)}, 404)
        except RuntimeError as exc: handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError): return
        except OSError: handler.send_json({'error': '视频控制存储读写失败'}, 500)
    routes = {('GET', '/api/video_control/' + a): (lambda h, action=a: handle(h, action)) for a in ('status', 'job', 'artifact', 'source')}
    routes.update({('POST', '/api/video_control/' + a): (lambda h, action=a: handle(h, action, True)) for a in ('upload', 'submit', 'cancel')})
    return ProtectedRouter(routes)
