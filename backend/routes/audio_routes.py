"""Authenticated audio HTTP adapter; existing handler retains auth/CORS ownership."""
import json
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..audio.contracts import MAX_UPLOAD
from ..audio.service import score_action


from .artifact_response import send_artifact


def create_router(service):
    def handle(handler, action, post=False):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [''])[0]
            body = {}
            if post:
                limit = MAX_UPLOAD if action == 'upload' else 512 * 1024
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= limit:
                    raise ValueError('请求体为空或超过大小限制')
                data = handler.rfile.read(length)
                if len(data) != length: raise ValueError('请求体不完整')
                if action == 'upload':
                    handler.send_json(service.upload(data, first('name')))
                    return
                body = json.loads(data)
                if not isinstance(body, dict): raise ValueError('请求必须是 JSON 对象')
            if action == 'status': result = service.status()
            elif action == 'submit': result = service.submit(body)
            elif action == 'job': result = service.store.get(first('id'))
            elif action == 'jobs': result = {'jobs': service.store.list()}
            elif action == 'cancel': result = service.cancel(body.get('id', ''))
            elif action == 'score': result = score_action(body)
            elif action == 'artifact':
                send_artifact(handler, service.store.artifact(first('id'), first('name')))
                return
            handler.send_json(result)
        except (ValueError, TypeError, KeyError) as exc:
            handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            handler.send_json({'error': str(exc)}, 404)
        except RuntimeError as exc:
            handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({'error': '音频存储读写失败，请检查磁盘和目录权限'}, 500)
    routes = {('GET', '/api/audio/' + a): (lambda h, action=a: handle(h, action))
              for a in ('status', 'job', 'jobs', 'artifact')}
    routes.update({('POST', '/api/audio/' + a): (lambda h, action=a: handle(h, action, True))
                   for a in ('upload', 'submit', 'cancel', 'score')})
    return ProtectedRouter(routes)
