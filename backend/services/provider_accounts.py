"""Account-pool access, managed verification and public status helpers.

Dependencies are supplied explicitly by the compatibility entrypoints.
Preserve existing operation order, payloads and failure semantics.
"""
from __future__ import annotations


def _collect_chatgpt_pool_status(*, get_chatgpt_pool_config, get_chatgpt_pool_public_config, requests):
    """Return safe sidecar health/config without exposing the Bearer auth key."""
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    status = get_chatgpt_pool_public_config()
    status.update({
        "online": False,
        "health_error": "",
        "stats": {},
    })
    try:
        session = requests.Session()
        session.trust_env = False
        response = session.get(f"{cfg['base_url'].rstrip('/')}/health", timeout=2)
        data = response.json() if response.text else {}
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        status["online"] = bool(data.get("ok", True)) if isinstance(data, dict) else True
        if isinstance(data, dict):
            status["stats"] = data.get("stats") if isinstance(data.get("stats"), dict) else {}
            status["model"] = data.get("model") or status.get("generation_model")
            stats = status["stats"]
            status["summary"] = {
                "total": int(stats.get("total") or 0),
                "active": int(stats.get("active") or 0),
                "available": int(stats.get("available") or 0),
                "inflight": int(stats.get("inflight") or 0),
                "limited": int(stats.get("limited") or 0),
                "abnormal": int(stats.get("abnormal") or 0),
                "refreshable": int(stats.get("refreshable") or 0),
            }
    except Exception as exc:
        status["health_error"] = str(exc)[:240]
    return status


def _chatgpt_pool_request(method, path, payload=None, timeout=None, *, get_chatgpt_pool_config, requests):
    cfg = get_chatgpt_pool_config(ensure_auth_key=True)
    auth_key = str(cfg.get("auth_key") or "").strip()
    if not auth_key:
        raise RuntimeError("ChatGPT pool auth key missing")
    endpoint = f"{str(cfg.get('base_url') or '').rstrip('/')}{path}"
    session = requests.Session()
    session.trust_env = False
    headers = {
        "Authorization": f"Bearer {auth_key}",
        "Content-Type": "application/json",
    }
    response = session.request(
        str(method or "GET").upper(),
        endpoint,
        headers=headers,
        json=payload if payload is not None else None,
        timeout=timeout or min(30, int(cfg.get("timeout_seconds") or 30)),
    )
    data = response.json() if response.text else {}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else ""
        if isinstance(detail, dict):
            detail = detail.get("error") or detail.get("message") or detail
        message = detail
        if not message and isinstance(data, dict):
            message = data.get("error") or data.get("message")
        if not message:
            message = response.text[:300] or f"HTTP {response.status_code}"
        raise RuntimeError(str(message))
    return data if isinstance(data, dict) else {"ok": True, "data": data}


def _chatgpt_pool_safe_auth_candidates(*, Path, get_gpt_provider_auth_status):
    """Return local Codex auth files that diagnostics already considers valid."""
    status = get_gpt_provider_auth_status()
    candidates = []
    for item in status.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("exists") or not item.get("readable") or not item.get("has_access_token"):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        try:
            candidates.append(Path(path).expanduser().resolve())
        except Exception:
            continue
    selected = str(status.get("selected_path") or "").strip()
    if selected:
        try:
            selected_path = Path(selected).expanduser().resolve()
            if selected_path not in candidates and selected_path.exists():
                candidates.insert(0, selected_path)
        except Exception:
            pass
    return candidates


def _chatgpt_pool_build_local_auth_account(requested_path='', *, Path, _chatgpt_pool_safe_auth_candidates, json):
    """Load one safe local Codex auth file and normalize it for sidecar import."""
    candidates = _chatgpt_pool_safe_auth_candidates()
    if not candidates:
        raise RuntimeError("未找到可导入的本机 Codex Auth 文件")

    if requested_path:
        target = Path(str(requested_path)).expanduser().resolve()
        if target not in candidates:
            raise RuntimeError("只能导入本机诊断页识别到的 Codex Auth 文件")
    else:
        target = candidates[0]

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"本机 Auth JSON 读取失败：{target}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError("本机 Auth JSON 格式错误")

    token_obj = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else raw
    access_token = str(token_obj.get("access_token") or raw.get("access_token") or "").strip()
    refresh_token = str(token_obj.get("refresh_token") or raw.get("refresh_token") or "").strip()
    id_token = str(token_obj.get("id_token") or raw.get("id_token") or "").strip()
    if not access_token:
        raise RuntimeError("本机 Auth 缺少 access_token")
    if not refresh_token:
        raise RuntimeError("本机 Auth 缺少 refresh_token，无法加入可自动续期的账号池")

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "account_id": str(token_obj.get("account_id") or raw.get("account_id") or "").strip(),
        "email": str(token_obj.get("email") or raw.get("email") or "").strip(),
        "source_type": "local_codex_auth",
    }, str(target)


def _chatgpt_pool_open_authorize_url_clean(authorize_url, *, Path, subprocess, tempfile, urllib):
    """Open an OpenAI authorize URL in an isolated Chrome profile."""
    url = str(authorize_url or "").strip()
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.scheme != "https" or parsed.netloc != "auth.openai.com" or parsed.path != "/api/accounts/authorize":
        raise RuntimeError("只能打开 OpenAI 授权链接")
    if (query.get("client_id") or [""])[0] != "app_2SKx67EdpoN0G6j64rFvigXD":
        raise RuntimeError("授权链接 client_id 不匹配")
    if (query.get("redirect_uri") or [""])[0] != "https://platform.openai.com/auth/callback":
        raise RuntimeError("授权链接 redirect_uri 不匹配")

    profile_dir = Path(tempfile.gettempdir()) / "tg-mini-app-chatgpt-pool-oauth-chrome"
    profile_dir.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            "open",
            "-na",
            "Google Chrome",
            "--args",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-extensions",
            "--new-window",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "profile_dir": str(profile_dir)}


def _chatgpt_pool_account_by_id(account_id, *, _chatgpt_pool_request):
    target_id = str(account_id or "").strip()
    if not target_id:
        raise RuntimeError("缺少账号 ID")
    accounts_payload = _chatgpt_pool_request("GET", "/accounts")
    accounts = accounts_payload.get("items") if isinstance(accounts_payload, dict) else []
    account = next(
        (
            item
            for item in accounts or []
            if isinstance(item, dict)
            and str(item.get("account_id") or "").strip() == target_id
        ),
        None,
    )
    if not account:
        raise RuntimeError("账号不存在或已删除")
    return account


def _chatgpt_pool_verification_profile_dir(account_or_id, *, APP_DATA_DIR, re):
    root = APP_DATA_DIR / "chatgpt_pool" / "verify_chrome_profiles"
    email = ""
    if isinstance(account_or_id, dict):
        email = str(account_or_id.get("email") or "").strip()
        raw_key = (
            str(account_or_id.get("user_id") or "").strip()
            or email
            or str(account_or_id.get("account_id") or "").strip()
        )
    else:
        raw_key = str(account_or_id or "").strip()
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_key)[:96] or "account"
    stable_dir = root / safe_id
    if stable_dir.exists() or not email or not root.exists():
        return stable_dir
    try:
        for candidate in root.iterdir():
            prefs = candidate / "Default" / "Preferences"
            if not prefs.exists() or not candidate.is_dir():
                continue
            text = prefs.read_text(encoding="utf-8", errors="ignore")
            if email in text:
                return candidate
    except Exception:
        pass
    return stable_dir


def _chatgpt_pool_find_free_port(*, socket):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chatgpt_pool_complete_account_verification(
    account_id,
    debug_port=None,
    *,
    _chatgpt_pool_account_by_id,
    _chatgpt_pool_request,
    _chatgpt_pool_verification_profile_dir,
):
    target_id = str(account_id or "").strip()
    if not target_id:
        raise RuntimeError("缺少账号 ID")
    account = _chatgpt_pool_account_by_id(target_id)
    email = str(account.get("email") or "").strip()
    profile_dir = _chatgpt_pool_verification_profile_dir(account)
    data = _chatgpt_pool_request(
        "POST",
        "/accounts/update",
        {
            "account_id": target_id,
            "status": "正常",
            "image_quota_unknown": True,
            "restore_at": "",
            "last_refresh_error": "",
        },
    )
    if isinstance(data, dict):
        data.update({
            "ok": True,
            "account_id": target_id,
            "email": email,
            "profile_dir": str(profile_dir),
            "message": "账号已恢复为正常，后续请求使用轻量 HTTP 链路",
        })
    return data
