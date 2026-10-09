"""Shared authenticated file response with byte-range support."""
import mimetypes
import re


def send_artifact(handler, path, content_type=None):
    size = path.stat().st_size
    start, end, status = 0, size - 1, 200
    header = handler.headers.get('Range')
    if header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', header)
        if not match or not any(match.groups()):
            handler.send_json({'error': '无效 Range'}, 416, {'Content-Range': f'bytes */{size}'})
            return
        left, right = match.groups()
        if left:
            start = int(left); end = min(int(right), size - 1) if right else size - 1
        else: start = max(0, size - int(right))
        if start > end or start >= size:
            handler.send_json({'error': 'Range 超出文件'}, 416, {'Content-Range': f'bytes */{size}'})
            return
        status = 206
    handler.send_response(status)
    handler.send_header('Content-Type', content_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
    handler.send_header('Content-Length', str(max(0, end - start + 1)))
    handler.send_header('Accept-Ranges', 'bytes')
    handler.send_header('Cache-Control', 'private, no-cache')
    handler.send_header('X-Content-Type-Options', 'nosniff')
    if status == 206: handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
    handler._apply_cors_headers()
    handler.end_headers()
    with path.open('rb') as stream:
        stream.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = stream.read(min(remaining, 256 * 1024))
            if not chunk: break
            handler.wfile.write(chunk)
            remaining -= len(chunk)

