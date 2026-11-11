"""Authenticated HTTP adapter for the video-edit domain (`backend.video_edit`).

Transport only: request parsing, status codes and the preview JPEG response. Source
resolution, FFmpeg work, jobs and archive writes belong to the domain service.
"""
import json
from urllib.parse import parse_qs, urlparse

from .base import ProtectedRouter
from ..video_edit.sources import UnsupportedSource


def create_router(service, compose=None, transcribe=None):
    """`compose` (ComposeService) owns render jobs and `transcribe` (TranscribeService) automatic-subtitle
    jobs; `job`/`cancel` route an id to whichever service holds it."""
    def owner(ident):
        for candidate in (compose, transcribe):
            if candidate is not None and candidate.owns(ident):
                return candidate
        return service

    def handle(handler, action, post=False):
        try:
            query = parse_qs(urlparse(handler.path).query)
            first = lambda key: query.get(key, [''])[0]
            body = {}
            if post:
                length = int(handler.headers.get('Content-Length') or 0)
                if not 0 < length <= 65536:
                    raise ValueError('请求为空或超过大小限制')
                data = handler.rfile.read(length)
                if len(data) != length:
                    raise ValueError('请求体不完整')
                body = json.loads(data)
                if not isinstance(body, dict):
                    raise ValueError('请求必须为对象')

            if action == 'status':
                result = service.status()
                if compose is not None:
                    result['compose'] = compose.limits()
            elif action == 'probe':
                result = service.probe(first('source_url'))
            elif action in ('preview_frame', 'filmstrip'):
                image = (service.preview_frame(first('source_url'), first('frame'), first('width')) if action == 'preview_frame'
                         else service.filmstrip(first('source_url'), first('tiles')))
                handler.send_response(200)
                handler.send_header('Content-Type', 'image/jpeg')
                handler.send_header('Content-Length', str(len(image)))
                handler.send_header('Cache-Control', 'private, max-age=600')
                handler.send_header('X-Content-Type-Options', 'nosniff')
                handler._apply_cors_headers()
                handler.end_headers()
                handler.wfile.write(image)
                return
            elif action == 'submit':
                result = service.submit(body)
            elif action == 'compose' and compose is not None:
                result = compose.submit(body)
            elif action == 'compose_recipe' and compose is not None:
                result = compose.recipe(first('source_url'))
            elif action == 'subtitle_fonts' and compose is not None:
                result = compose.subtitle_fonts()
            elif action == 'compose_check' and compose is not None:
                result = compose.check(body)
            elif action == 'transcribe' and transcribe is not None:
                result = transcribe.submit(body)
            elif action == 'job':
                result = owner(first('id')).job(first('id'))
            elif action == 'cancel':
                result = owner(body.get('id')).cancel(body.get('id'))
            else:
                raise ValueError('未知视频剪辑操作')
            handler.send_json(result, 202 if action in ('submit', 'compose', 'transcribe') else 200)
        except (UnsupportedSource, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            handler.send_json({'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            handler.send_json({'error': str(exc) or '视频不存在'}, 404)
        except RuntimeError as exc:
            handler.send_json({'error': str(exc)}, 503)
        except (BrokenPipeError, ConnectionResetError):
            return
        except OSError:
            handler.send_json({'error': '视频剪辑读写失败'}, 500)

    routes = {('GET', '/api/video_edit/' + action): (lambda handler, selected=action: handle(handler, selected))
              for action in ('status', 'probe', 'preview_frame', 'filmstrip', 'job', 'compose_recipe', 'subtitle_fonts')}
    routes.update({('POST', '/api/video_edit/' + action): (lambda handler, selected=action: handle(handler, selected, True))
                   for action in ('submit', 'cancel', 'compose', 'compose_check', 'transcribe')})
    return ProtectedRouter(routes)
