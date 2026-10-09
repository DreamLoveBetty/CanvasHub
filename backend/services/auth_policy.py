"""Password, login throttle and Telegram/session authentication policies.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _load_auth_password(*, get_miniapp_access_password):
    return get_miniapp_access_password()


def _effective_access_password_configured(settings=None, *, AUTH_PASSWORD, _settings_dict, os):
    env_password = (
        os.environ.get("MINIAPP_ACCESS_PASSWORD")
        or os.environ.get("MINIAPP_AUTH_PASSWORD")
        or ""
    ).strip()
    if env_password:
        return True
    if settings is None:
        return bool(AUTH_PASSWORD)
    return bool(str(_settings_dict(settings).get("miniapp_access_password") or "").strip())


def _validate_public_mode_password(
    settings=None,
    *,
    server_config=None,
    _effective_access_password_configured,
    get_server_config,
):
    cfg = server_config or get_server_config()
    if cfg.get("public_mode") and not _effective_access_password_configured(settings):
        raise ValueError("公网模式必须先设置访问密码")


def _server_config_from_settings_snapshot(settings, *, _coerce_bool, _settings_dict, os):
    section = _settings_dict(_settings_dict(settings).get("server"))
    public_mode = _coerce_bool(
        os.environ.get("MINIAPP_PUBLIC_MODE")
        or os.environ.get("PUBLIC_MODE")
        or section.get("public_mode"),
        False,
    )
    try:
        port = int(
            os.environ.get("PORT")
            or os.environ.get("MINIAPP_PORT")
            or section.get("port")
            or 18463
        )
    except (TypeError, ValueError):
        port = 18463
    port = max(1, min(65535, port))
    requested_host = str(
        os.environ.get("HOST")
        or os.environ.get("BIND_HOST")
        or os.environ.get("MINIAPP_HOST")
        or section.get("host")
        or ""
    ).strip()
    if public_mode:
        host = requested_host or "0.0.0.0"
    else:
        host = "127.0.0.1"
    return {
        "host": host,
        "requested_host": requested_host,
        "port": port,
        "public_mode": public_mode,
    }


def _auth_enabled(*, AUTH_PASSWORD):
    return bool(AUTH_PASSWORD)


def _request_client_ip(headers, client_address):
    cf_ip = str(headers.get('CF-Connecting-IP') or '').strip()
    if cf_ip:
        return cf_ip
    xff = str(headers.get('X-Forwarded-For') or '').strip()
    if xff:
        return xff.split(',', 1)[0].strip()
    real_ip = str(headers.get('X-Real-IP') or '').strip()
    if real_ip:
        return real_ip
    try:
        return str(client_address[0] or '').strip()
    except Exception:
        return ''


def _login_lock_state(
    client_ip,
    now=None,
    *,
    _LOGIN_FAILURES,
    _LOGIN_FAILURE_LIMIT,
    _LOGIN_FAILURE_LOCK,
    _LOGIN_FAILURE_WINDOW_SECONDS,
    _LOGIN_LOCKOUT_SECONDS,
    time,
):
    now = now or time.time()
    with _LOGIN_FAILURE_LOCK:
        failures = [
            ts for ts in _LOGIN_FAILURES.get(client_ip, [])
            if now - ts < _LOGIN_FAILURE_WINDOW_SECONDS
        ]
        if failures:
            _LOGIN_FAILURES[client_ip] = failures
        else:
            _LOGIN_FAILURES.pop(client_ip, None)
        if len(failures) < _LOGIN_FAILURE_LIMIT:
            return False, 0
        retry_after = max(1, int(_LOGIN_LOCKOUT_SECONDS - (now - failures[-1])))
        if retry_after <= 0:
            _LOGIN_FAILURES.pop(client_ip, None)
            return False, 0
        return True, retry_after


def _record_login_failure(
    client_ip,
    now=None,
    *,
    _LOGIN_FAILURES,
    _LOGIN_FAILURE_LIMIT,
    _LOGIN_FAILURE_LOCK,
    _LOGIN_FAILURE_WINDOW_SECONDS,
    _LOGIN_LOCKOUT_SECONDS,
    time,
):
    now = now or time.time()
    with _LOGIN_FAILURE_LOCK:
        failures = [
            ts for ts in _LOGIN_FAILURES.get(client_ip, [])
            if now - ts < _LOGIN_FAILURE_WINDOW_SECONDS
        ]
        failures.append(now)
        _LOGIN_FAILURES[client_ip] = failures
        if len(failures) < _LOGIN_FAILURE_LIMIT:
            return False, 0
        retry_after = max(1, int(_LOGIN_LOCKOUT_SECONDS - (now - failures[-1])))
        return True, retry_after


def _clear_login_failures(client_ip, *, _LOGIN_FAILURES, _LOGIN_FAILURE_LOCK):
    with _LOGIN_FAILURE_LOCK:
        _LOGIN_FAILURES.pop(client_ip, None)


def _login_locked_payload(retry_after):
    return {
        "ok": False,
        "error": "TooManyLoginAttempts",
        "message": "登录失败次数过多，请稍后重试",
        "retry_after_seconds": retry_after,
    }


def _sensitive_db_base_paths(*, DIRECTORY, Path, get_chatgpt_pool_config, get_database_path):
    paths = [
        Path(get_database_path()),
        Path(DIRECTORY) / 'assets.db',
        Path(DIRECTORY) / 'prompt_sources.db',
        Path(DIRECTORY) / 'prompt_library.db',
    ]
    try:
        pool_db = get_chatgpt_pool_config().get('db_path')
        if pool_db:
            paths.append(Path(pool_db))
    except Exception as exc:
        print(f"⚠️ ChatGPT 账号池 DB 路径读取失败: {exc}")
    unique = []
    seen = set()
    for path in paths:
        key = str(path.expanduser())
        if key not in seen:
            unique.append(path.expanduser())
            seen.add(key)
    return unique


def _ensure_db_file_permissions(*, Path, _sensitive_db_base_paths):
    changed = []
    for db_path in _sensitive_db_base_paths():
        try:
            if db_path.parent.exists() and db_path.name == 'accounts.db':
                db_path.parent.chmod(0o700)
            for candidate in (
                db_path,
                Path(f"{db_path}-wal"),
                Path(f"{db_path}-shm"),
                Path(f"{db_path}-journal"),
            ):
                if candidate.exists() and candidate.is_file():
                    candidate.chmod(0o600)
                    changed.append(str(candidate))
        except Exception as exc:
            print(f"⚠️ DB 文件权限收紧失败：{db_path} - {exc}")
    if changed:
        print(f"🔒 已收紧 {len(changed)} 个敏感 DB 文件权限")


def _load_telegram_auth_config(*, get_telegram_auth_config):
    try:
        cfg = get_telegram_auth_config()
        bot_token = str(cfg.get('bot_token', '') or '').strip()
        allowed_ids = cfg.get('allowed_user_ids') or set()
        return bot_token, {str(x).strip() for x in allowed_ids if str(x).strip()}
    except Exception as e:
        print(f"⚠️ Telegram 鉴权配置读取失败: {e}")
        return '', set()


def _verify_telegram_init_data(
    init_data,
    *,
    TELEGRAM_AUTH_ALLOWED_IDS,
    TELEGRAM_AUTH_BOT_TOKEN,
    hashlib,
    hmac,
    json,
    os,
    time,
    urllib,
):
    if not init_data or not TELEGRAM_AUTH_BOT_TOKEN:
        return False
    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop('hash', '')
        if not received_hash:
            return False

        data_check_string = '\n'.join(f"{key}={value}" for key, value in sorted(data.items()))
        secret_key = hmac.new(
            b'WebAppData',
            TELEGRAM_AUTH_BOT_TOKEN.encode('utf-8'),
            hashlib.sha256,
        ).digest()
        expected_hash = hmac.new(
            secret_key,
            data_check_string.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            return False

        user_raw = data.get('user') or '{}'
        try:
            user = json.loads(user_raw)
        except Exception:
            user = {}
        user_id = str(user.get('id') or '').strip()
        if TELEGRAM_AUTH_ALLOWED_IDS and user_id not in TELEGRAM_AUTH_ALLOWED_IDS:
            print(f"⚠️ Telegram WebApp 鉴权拒绝：user_id={user_id}")
            return False

        auth_date_raw = str(data.get('auth_date') or '')
        if auth_date_raw.isdigit():
            max_age = int(os.environ.get('MINIAPP_TELEGRAM_AUTH_MAX_AGE', str(7 * 24 * 60 * 60)))
            if int(auth_date_raw) + max_age < int(time.time()):
                return False

        return True
    except Exception as e:
        print(f"⚠️ Telegram initData 校验失败: {e}")
        return False


def _auth_secret(*, AUTH_PASSWORD, DIRECTORY, hashlib):
    seed = f"{AUTH_PASSWORD}|{DIRECTORY}|miniapp-auth-v1"
    return hashlib.sha256(seed.encode('utf-8')).digest()


def _build_auth_cookie_value(issued_at=None, *, _auth_secret, hashlib, hmac, time):
    issued_at = int(issued_at or time.time())
    payload = str(issued_at)
    signature = hmac.new(_auth_secret(), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _verify_auth_cookie_value(cookie_value, *, AUTH_COOKIE_MAX_AGE, _auth_enabled, _auth_secret, hashlib, hmac, time):
    if not _auth_enabled():
        return True
    if not cookie_value or '.' not in cookie_value:
        return False
    issued_at_raw, signature = cookie_value.split('.', 1)
    if not issued_at_raw.isdigit() or not signature:
        return False
    expected = hmac.new(_auth_secret(), issued_at_raw.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    issued_at = int(issued_at_raw)
    if issued_at + AUTH_COOKIE_MAX_AGE < int(time.time()):
        return False
    return True
