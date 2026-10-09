"""Shared HTTP serialization, body parsing and transport adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _apply_cors_headers(handler, *, get_allowed_cors_origins):
    if getattr(handler, '_cors_headers_applied', False):
        return
    handler._cors_headers_applied = True
    origin = str(handler.headers.get('Origin') or '').strip().rstrip('/')
    if not origin:
        return
    if origin in set(get_allowed_cors_origins()):
        handler.send_header('Access-Control-Allow-Origin', origin)
        handler.send_header('Vary', 'Origin')


def send_json(handler, data, status=200, extra_headers=None, *, gzip, json):
    """发送 JSON 响应；大响应在客户端支持时做 gzip 压缩（提示词文本可压约 10x）。"""
    body = json.dumps(data).encode()
    content_encoding = ''
    if len(body) > 51200:
        accept_encoding = str(handler.headers.get('Accept-Encoding') or '').lower()
        if 'gzip' in accept_encoding:
            try:
                body = gzip.compress(body, compresslevel=5)
                content_encoding = 'gzip'
            except Exception:
                content_encoding = ''
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    if content_encoding:
        handler.send_header('Content-Encoding', content_encoding)
        handler.send_header('Vary', 'Accept-Encoding')
    handler.send_header('Content-Length', str(len(body)))
    handler._apply_cors_headers()
    if extra_headers:
        for key, value in extra_headers.items():
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler, max_bytes=64 * 1024 * 1024, *, json):
    content_length = int(handler.headers.get('Content-Length', 0))
    if content_length > max_bytes:
        raise ValueError('请求体过大')
    body = handler.rfile.read(content_length)
    return json.loads(body or b'{}')


def send_binary_file(handler, path, *, Path, mimetypes):
    file_path = Path(path)
    content_type = mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
    handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(file_path.stat().st_size))
    handler.send_header('Cache-Control', 'private, max-age=60')
    handler._apply_cors_headers()
    handler.end_headers()
    with open(file_path, 'rb') as f:
        handler.wfile.write(f.read())


def _read_json_body(handler, *, json):
    content_length = int(handler.headers.get('Content-Length', 0))
    body = handler.rfile.read(content_length)
    if not body:
        return {}
    data = json.loads(body)
    return data if isinstance(data, dict) else {}


def _write_ndjson_event(handler, event, *, json):
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    handler.wfile.write(payload)
    handler.wfile.flush()


def log_message(handler, format, *args, re, time):
    """自定义日志格式"""
    request_line = str(args[0]) if args else ''
    request_line = re.sub(r'([?&](?:miniappAuth|authToken|auth_token)=)[^&\s]+', r'\1***', request_line)
    print(f"[{time.strftime('%H:%M:%S')}] {request_line}")
