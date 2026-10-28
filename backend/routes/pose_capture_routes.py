"""Thin authenticated HTTP adapter for pose capture (photo recognition)."""
import json
from urllib.parse import parse_qs, urlparse

from .artifact_response import send_artifact
from .base import ProtectedRouter
from ..pose_capture.contracts import MAX_VIDEO_UPLOAD


def create_router(service):
    def handle(handler, action, post=False):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [''])[0]
            body = {}
            if post:
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= (MAX_VIDEO_UPLOAD if action == 'upload' else 4096):
                    raise ValueError('请求为空或超过大小限制')
                data = handler.rfile.read(length)
                if len(data) != length: raise ValueError('请求体不完整')
                if action == 'upload':
                    handler.send_json(service.upload(data, first('name'))); return
                body = json.loads(data)
                if not isinstance(body, dict): raise ValueError('请求必须为对象')
            if action == 'body':
                send_artifact(handler, service.body(first('id')), 'model/gltf-binary'); return
            if action == 'status': result = service.status()
            elif action == 'submit': result = service.submit(body)
            elif action == 'job': result = service.job(first('id'))
            elif action == 'result': result = service.result(first('id'))
            elif action == 'cancel': result = service.cancel(body.get('id'))
            handler.send_json(result)
        except (ValueError, TypeError, KeyError) as exc: handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc: handler.send_json({'error': str(exc)}, 404)
        except RuntimeError as exc: handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError): return
        except OSError: handler.send_json({'error': '姿态识别存储读写失败'}, 500)
    routes = {('GET', '/api/pose_capture/' + a): (lambda h, action=a: handle(h, action)) for a in ('status', 'job', 'result', 'body')}
    routes.update({('POST', '/api/pose_capture/' + a): (lambda h, action=a: handle(h, action, True)) for a in ('upload', 'submit', 'cancel')})
    return ProtectedRouter(routes)
