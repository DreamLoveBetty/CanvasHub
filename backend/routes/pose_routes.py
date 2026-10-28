"""Thin authenticated HTTP adapter for the pose scene domain."""
import json
from urllib.parse import parse_qs, urlparse

from .artifact_response import send_artifact
from .base import ProtectedRouter
from ..pose_scene.contracts import MAX_EXPORT_REQUEST, identifier
from ..pose_scene.video_export import MAX_FRAME_BYTES


def create_router(service):
    def handle(handler, action, post=False):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [''])[0]
            body, data = {}, b''
            if post:
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= (MAX_FRAME_BYTES if action == 'export/video/frame' else MAX_EXPORT_REQUEST):
                    raise ValueError('请求为空或超过大小限制')
                data = handler.rfile.read(length)
                if len(data) != length: raise ValueError('请求体不完整')
                if action != 'export/video/frame':
                    body = json.loads(data)
                    if not isinstance(body, dict): raise ValueError('请求必须为对象')
            if action == 'assets/status':
                handler.send_json(service.status())
            elif action == 'glb':
                send_artifact(handler, service.glb(first('lod'), first('body')), 'model/gltf-binary')
            elif action == 'export/image':
                handler.send_json(service.save_export(body))
            elif action == 'export/artifact':
                send_artifact(handler, service.export_path(first('id')), 'image/png')
            elif action == 'export/video/start':
                handler.send_json(service.video('start', body))
            elif action == 'export/video/frame':
                index = first('index')
                if not index.isdigit(): raise ValueError('帧序号无效')
                handler.send_json(service.video('frame', ident=identifier(first('id')), index=int(index), data=data))
            elif action in ('export/video/finish', 'export/video/cancel'):
                handler.send_json(service.video(action.rsplit('/', 1)[1], ident=identifier(body.get('id'))))
            elif action == 'export/video/job':
                handler.send_json(service.video('job', ident=identifier(first('id'))))
        except (ValueError, TypeError, KeyError) as exc: handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc: handler.send_json({'error': str(exc)}, 404)
        except RuntimeError as exc: handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError): return
        except OSError: handler.send_json({'error': '姿态数据读写失败'}, 500)
    routes = {('GET', '/api/pose/' + a): (lambda h, action=a: handle(h, action)) for a in ('assets/status', 'glb', 'export/artifact', 'export/video/job')}
    routes.update({('POST', '/api/pose/' + a): (lambda h, action=a: handle(h, action, True))
                   for a in ('export/image', 'export/video/start', 'export/video/frame', 'export/video/finish', 'export/video/cancel')})
    return ProtectedRouter(routes)
