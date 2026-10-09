"""HTTP password login, session and Telegram authentication adapters.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _get_cookie_value(handler, name, *, SimpleCookie):
    raw = handler.headers.get('Cookie', '')
    if not raw:
        return ''
    try:
        cookie = SimpleCookie()
        cookie.load(raw)
        morsel = cookie.get(name)
        return morsel.value if morsel else ''
    except Exception:
        return ''


def is_authenticated(
    handler,
    *,
    AUTH_COOKIE_NAME,
    AUTH_HEADER_NAME,
    TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME,
    TELEGRAM_INIT_DATA_HEADER_NAME,
    _auth_enabled,
    _verify_auth_cookie_value,
    _verify_telegram_init_data,
    urllib,
):
    if not _auth_enabled():
        return True
    init_data = handler.headers.get(TELEGRAM_INIT_DATA_HEADER_NAME, '')
    encoded_init_data = handler.headers.get(TELEGRAM_INIT_DATA_ENCODED_HEADER_NAME, '')
    if not init_data and encoded_init_data:
        try:
            init_data = urllib.parse.unquote(encoded_init_data)
        except Exception:
            init_data = ''
    if init_data and _verify_telegram_init_data(init_data):
        return True
    header_token = handler.headers.get(AUTH_HEADER_NAME, '')
    if header_token and _verify_auth_cookie_value(header_token):
        return True
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(getattr(handler, 'path', '') or '').query)
        query_token = (
            query.get('miniappAuth', [''])[0]
            or query.get('authToken', [''])[0]
            or query.get('auth_token', [''])[0]
        )
        if query_token and _verify_auth_cookie_value(query_token):
            return True
    except Exception:
        pass
    return _verify_auth_cookie_value(handler._get_cookie_value(AUTH_COOKIE_NAME))


def require_auth(handler):
    if handler.is_authenticated():
        return True
    handler.send_json({
        "ok": False,
        "error": "Unauthorized",
        "message": "需要先输入访问密码"
    }, 401)
    return False


def handle_login(
    handler,
    *,
    AUTH_COOKIE_MAX_AGE,
    AUTH_COOKIE_NAME,
    AUTH_PASSWORD,
    _auth_enabled,
    _build_auth_cookie_value,
    _clear_login_failures,
    _login_lock_state,
    _login_locked_payload,
    _record_login_failure,
    _request_client_ip,
    json,
):
    """处理密码登录并写入 HttpOnly Cookie"""
    if not _auth_enabled():
        handler.send_json({
            "ok": True,
            "auth_enabled": False,
            "message": "未配置访问密码，鉴权自动关闭"
        })
        return

    client_ip = _request_client_ip(handler.headers, handler.client_address)
    locked, retry_after = _login_lock_state(client_ip)
    if locked:
        handler.send_json(_login_locked_payload(retry_after), 429)
        return

    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        body = handler.rfile.read(content_length)
        data = json.loads(body or b'{}')
    except Exception:
        handler.send_json({"ok": False, "error": "请求体格式错误"}, 400)
        return

    password = str(data.get('password') or data.get('apiKey') or '').strip()
    if password != AUTH_PASSWORD:
        locked, retry_after = _record_login_failure(client_ip)
        if locked:
            handler.send_json(_login_locked_payload(retry_after), 429)
            return
        handler.send_json({"ok": False, "error": "密码错误"}, 401)
        return

    _clear_login_failures(client_ip)
    cookie_value = _build_auth_cookie_value()
    cookie_parts = [
        f"{AUTH_COOKIE_NAME}={cookie_value}",
        f"Max-Age={AUTH_COOKIE_MAX_AGE}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    handler.send_json({
        "ok": True,
        "auth_enabled": True,
        "auth_token": cookie_value,
        "max_age": AUTH_COOKIE_MAX_AGE,
        "message": "登录成功"
    }, extra_headers={"Set-Cookie": "; ".join(cookie_parts)})


def handle_auth_verify(handler, *, _auth_enabled):
    """验证当前 Cookie 是否有效"""
    if not _auth_enabled():
        handler.send_json({
            "ok": True,
            "auth_enabled": False,
            "message": "未配置访问密码，鉴权自动关闭"
        })
        return

    if handler.is_authenticated():
        handler._send_auth_success_cookie("验证成功", cookie_value=handler._reusable_auth_token() or None)
        return

    handler.send_json({
        "ok": False,
        "auth_enabled": True,
        "error": "Unauthorized",
        "message": "需要先输入访问密码"
    }, 401)


def _presented_auth_token(handler, *, AUTH_COOKIE_NAME, AUTH_HEADER_NAME, urllib):
    """按 is_authenticated 的优先级取出请求携带的鉴权 token。"""
    header_token = handler.headers.get(AUTH_HEADER_NAME, '')
    if header_token:
        return header_token
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(getattr(handler, 'path', '') or '').query)
        query_token = (
            query.get('miniappAuth', [''])[0]
            or query.get('authToken', [''])[0]
            or query.get('auth_token', [''])[0]
        )
        if query_token:
            return query_token
    except Exception:
        pass
    return handler._get_cookie_value(AUTH_COOKIE_NAME)


def _reusable_auth_token(handler, *, AUTH_COOKIE_MAX_AGE, _verify_auth_cookie_value, time):
    """仍在前半有效期内的合法 token 原样复用，保持媒体 URL 跨启动稳定（浏览器缓存命中）。"""
    token = str(handler._presented_auth_token() or '')
    if not token or '.' not in token:
        return ''
    try:
        # token 可能来自 query/header 的不可信字节（如非 ASCII），校验失败一律回退铸新
        if not _verify_auth_cookie_value(token):
            return ''
    except Exception:
        return ''
    issued_at_raw = token.split('.', 1)[0]
    if not issued_at_raw.isdigit():
        return ''
    if int(issued_at_raw) + AUTH_COOKIE_MAX_AGE // 2 < int(time.time()):
        return ''
    return token


def _send_auth_success_cookie(
    handler,
    message,
    cookie_value=None,
    *,
    AUTH_COOKIE_MAX_AGE,
    AUTH_COOKIE_NAME,
    _build_auth_cookie_value,
):
    cookie_value = cookie_value or _build_auth_cookie_value()
    cookie_parts = [
        f"{AUTH_COOKIE_NAME}={cookie_value}",
        f"Max-Age={AUTH_COOKIE_MAX_AGE}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
    ]
    handler.send_json({
        "ok": True,
        "auth_enabled": True,
        "auth_token": cookie_value,
        "max_age": AUTH_COOKIE_MAX_AGE,
        "message": message
    }, extra_headers={"Set-Cookie": "; ".join(cookie_parts)})
