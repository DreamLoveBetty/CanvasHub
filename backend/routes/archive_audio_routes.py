"""Authenticated asset-library audio endpoints over the archive's `audio/` subtree.

Undo stays on the shared `/api/assets/undo-delete` journal. Responses carry archive-relative
paths only, never absolute local paths.
"""
from urllib.parse import parse_qs, urlparse

from .artifact_response import send_artifact
from .base import ProtectedRouter
from ..services.archive_audio import mime_type


def _int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def create_router(archive):
    def query(handler):
        values = parse_qs(urlparse(handler.path).query)
        return lambda key: values.get(key, [''])[0]

    def guarded(action):
        def run(handler):
            try:
                action(handler)
            except FileNotFoundError as exc:
                handler.send_json({'ok': False, 'error': str(exc)}, 404)
            except (ValueError, TypeError) as exc:
                handler.send_json({'ok': False, 'error': str(exc)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as exc:
                print(f'❌ audio assets failed: {exc}')
                handler.send_json({'ok': False, 'error': '音频资产读写失败，请检查归档目录'}, 500)
        return run

    def list_assets(handler):
        first = query(handler)
        handler.send_json(archive.list(first('query'), limit=_int(first('limit'), 200, 1, 500),
                                       offset=_int(first('offset'), 0, 0, 100000)))

    def send_file(handler):
        path = archive.resolve(query(handler)('path'))
        send_artifact(handler, path, mime_type(path))

    def peaks(handler):
        handler.send_json(archive.peaks(query(handler)('path')))

    def delete(handler):
        paths = handler.read_json_body(max_bytes=64 * 1024).get('paths')
        if not isinstance(paths, list):
            raise ValueError('paths 必须是列表')
        handler.send_json(archive.delete(paths))

    return ProtectedRouter({
        ('GET', '/api/assets/audio'): guarded(list_assets),
        ('GET', '/api/assets/audio/file'): guarded(send_file),
        ('GET', '/api/assets/audio/peaks'): guarded(peaks),
        ('POST', '/api/assets/audio/delete'): guarded(delete),
    })
