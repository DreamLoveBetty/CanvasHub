"""Authenticated HTTP adapter for the separate Topaz Video task domain.

The adapter owns transport only. Model selection, job state and asset storage
belong to ``backend.topaz_video``; no Topaz Video logic is added to server.py.
"""

import json
import mimetypes
from urllib.parse import parse_qs, urlparse

from .artifact_response import send_artifact
from .base import ProtectedRouter
from ..topaz_video.contracts import MAX_UPLOAD


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
                if len(data) != length:
                    raise ValueError('请求体不完整')
                if action == 'upload':
                    handler.send_json(service.upload(data, first('name')))
                    return
                body = json.loads(data)
                if not isinstance(body, dict):
                    raise ValueError('请求必须为对象')

            if action == 'status':
                result = service.status()
            elif action == 'submit':
                result = service.submit(body)
            elif action == 'job':
                result = service.job(first('id'))
            elif action == 'cancel':
                result = service.cancel(body.get('id'))
            elif action == 'source':
                path = service.store.asset(first('id'))
                info = json.loads(path.with_suffix('.json').read_text())
                mime = mimetypes.guess_type(info.get('name', ''))[0]
                send_artifact(handler, path, mime if mime and mime.startswith('video/') else 'video/mp4')
                return
            elif action == 'artifact':
                send_artifact(handler, service.store.artifact(first('id'), first('name')))
                return
            else:
                raise ValueError('未知 Topaz Video 操作')
            handler.send_json(result, 202 if action == 'submit' and result.get('status') == 'queued' else 200)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            handler.send_json({'error': str(exc)}, 404)
        except RuntimeError as exc:
            handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({'error': 'Topaz Video 存储读写失败'}, 500)

    routes = {('GET', '/api/topaz_video/' + action):
              (lambda handler, selected=action: handle(handler, selected))
              for action in ('status', 'job', 'artifact', 'source')}
    routes.update({('POST', '/api/topaz_video/' + action):
                   (lambda handler, selected=action: handle(handler, selected, True))
                   for action in ('upload', 'submit', 'cancel')})
    return ProtectedRouter(routes)
