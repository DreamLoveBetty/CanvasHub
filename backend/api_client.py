#!/usr/bin/env python3
"""
API 客户端 - nano banana / Google-compatible REST 端点
"""

import base64
import hashlib
import json
import os
import re
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager

from .app_config import get_telegram_config, get_yunwu_api_base_url, get_yunwu_api_key
from . import provider_change2pro as change2pro
from .gemini_image_response import GeminiImageResponse

# ── 配置 ──────────────────────────────────────────────────────────────────────
DEFAULT_API_BASE = ''
DEFAULT_OPENAI_CHAT_IMAGE_MODEL = 'gemini-3.1-flash-image'
TIMEOUT = 1800
CONNECT_TIMEOUT = 15
EDIT_UPLOAD_SOCKET_TIMEOUT = 100
READ_TIMEOUT = 900
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
MAX_HTTP_RETRIES = 2
HTTP_RETRY_BACKOFF_SECONDS = 2
KEEPALIVE_IDLE = 60
KEEPALIVE_INTERVAL = 30
KEEPALIVE_COUNT = 4
CHUNK_SIZE = 65536
DATA_URI_RE = re.compile(r"data:image/[^;,\s]+;base64,[A-Za-z0-9+/=\s]+")
URL_RE = re.compile(r"https?://[^\s)\"']+")
GOOGLE_IMAGE_MODEL_ALIAS_FAMILIES = (
    ('gemini-3-pro-image', 'gemini-3-pro-image-preview'),
    ('gemini-3.1-flash-image', 'gemini-3.1-flash-image-preview'),
)
_GOOGLE_IMAGE_MODEL_CANONICAL = {
    alias: family[0]
    for family in GOOGLE_IMAGE_MODEL_ALIAS_FAMILIES
    for alias in family
}
_resolved_model_cache = {}
_resolved_model_cache_lock = threading.Lock()


class ModelUnavailableError(Exception):
    """Raised when an upstream explicitly says the requested model has no channel."""

    def __init__(self, message, *, status_code=None, error_code='', error_type=''):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = str(error_code or '')
        self.error_type = str(error_type or '')


def load_telegram_delivery_config():
    """从项目配置层读取 Telegram 发送配置。"""
    return get_telegram_config()


def _build_socket_options():
    opts = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    if hasattr(socket, 'TCP_NODELAY'):
        opts.append((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1))
    if hasattr(socket, 'TCP_KEEPIDLE'):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, KEEPALIVE_IDLE))
    if hasattr(socket, 'TCP_KEEPINTVL'):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, KEEPALIVE_INTERVAL))
    if hasattr(socket, 'TCP_KEEPCNT'):
        opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, KEEPALIVE_COUNT))
    return opts


class IPv4HTTPAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        pool_kwargs['socket_options'] = _build_socket_options()
        pool_kwargs['source_address'] = None
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        conn = super().get_connection_with_tls_context(request, verify, proxies=proxies, cert=cert)
        try:
            conn.conn_kw['socket_options'] = _build_socket_options()
        except Exception:
            pass
        return conn


_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (compatible; ImageGenBot/1.1)',
})
_session.trust_env = False
_session.proxies = {}
adapter = IPv4HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=0)
_session.mount('https://', adapter)
_session.mount('http://', adapter)


def _ensure_api_key() -> str:
    """Load nano banana API key lazily so the server can still boot without it."""
    api_key = get_yunwu_api_key()
    if not api_key:
        raise Exception("无法加载 nano banana API Key，请配置 NANO_BANANA_API_KEY、settings.json.nano_banana_api.api_key 或兼容旧键 settings.json.yunwu_api_key")
    _session.headers['Authorization'] = f'Bearer {api_key}'
    return api_key


def _api_base() -> str:
    base = (get_yunwu_api_base_url() or DEFAULT_API_BASE).rstrip("/")
    if not base:
        raise Exception("nano banana API URL 未配置，请在设置中心填写 API URL。")
    return base


def _url_path(value: str) -> str:
    return urlparse(str(value or "")).path.rstrip("/")


def _uses_openai_chat_endpoint(api_base: str | None = None) -> bool:
    if change2pro.uses_documented_google_api(api_base or _api_base()):
        return False
    path = _url_path(api_base or _api_base()).lower()
    if path.endswith("/chat/completions"):
        return True
    if path.endswith("/v1beta") or path.endswith("/v1beta/"):
        return False
    return True


def _chat_completions_url(api_base: str) -> str:
    base = str(api_base or DEFAULT_API_BASE).rstrip("/")
    path = _url_path(base).lower()
    if path.endswith("/chat/completions"):
        return base
    if path.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _gemini_generate_url(api_base: str, api_model: str) -> str:
    return f"{str(api_base or DEFAULT_API_BASE).rstrip('/')}/models/{api_model}:generateContent"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_progress_cb(*_args, **_kwargs):
    return None


def _classify_transport_error(exc: Exception, bytes_received: int) -> str:
    text = str(exc).lower()
    if isinstance(exc, requests.exceptions.SSLError) or "ssleoferror" in text or "unexpected_eof" in text:
        return 'ssl_eof'
    if isinstance(exc, requests.exceptions.Timeout):
        return 'read_timeout_during_download' if bytes_received > 0 else 'first_byte_timeout'
    if isinstance(exc, requests.exceptions.ConnectionError):
        if 'reset' in text or 'remote end closed' in text or 'broken pipe' in text:
            return 'connection_reset_during_download' if bytes_received > 0 else 'connection_reset_before_first_byte'
        return 'connection_error'
    if 'json' in text:
        return 'json_decode_error'
    return type(exc).__name__


def _is_retryable_request_exception(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            requests.exceptions.SSLError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    )


def _normalize_openai_chat_model(model: str | None) -> str:
    normalized = str(model or '').replace('google/', '').strip()
    return _GOOGLE_IMAGE_MODEL_CANONICAL.get(normalized, normalized) or DEFAULT_OPENAI_CHAT_IMAGE_MODEL


def _requested_native_model(model: str | None) -> str:
    return (str(model or '').strip().removeprefix('google/').removeprefix('models/')
            or DEFAULT_OPENAI_CHAT_IMAGE_MODEL)


def _model_alias_candidates(model: str | None) -> list[str]:
    canonical = _normalize_openai_chat_model(model)
    for family in GOOGLE_IMAGE_MODEL_ALIAS_FAMILIES:
        if canonical == family[0]:
            return list(family)
    return [canonical]


def _model_cache_key(api_base: str, model: str | None) -> tuple[str, str, str]:
    api_key = get_yunwu_api_key()
    key_fingerprint = hashlib.sha256(api_key.encode('utf-8')).hexdigest()[:16] if api_key else ''
    model_key = (_requested_native_model(model) if change2pro.uses_documented_google_api(api_base)
                 else _normalize_openai_chat_model(model))
    return str(api_base or '').rstrip('/'), key_fingerprint, model_key


def _ordered_model_candidates(api_base: str, model: str | None) -> list[str]:
    candidates = _model_alias_candidates(model)
    if change2pro.uses_documented_google_api(api_base):
        # Respect the exact ID from this provider's model list. Only an explicit
        # model-unavailable response may switch to an equivalent alias.
        requested = _requested_native_model(model)
        candidates = [requested, *(candidate for candidate in candidates if candidate != requested)]
    cache_key = _model_cache_key(api_base, model)
    with _resolved_model_cache_lock:
        cached = _resolved_model_cache.get(cache_key)
    if cached in candidates:
        return [cached, *(candidate for candidate in candidates if candidate != cached)]
    return candidates


def _remember_resolved_model(api_base: str, requested_model: str | None, resolved_model: str) -> None:
    with _resolved_model_cache_lock:
        _resolved_model_cache[_model_cache_key(api_base, requested_model)] = resolved_model


def _is_model_unavailable_http_error(status_code: int, error_text: str) -> bool:
    message, code, error_type = _extract_http_error_detail(error_text)
    normalized_code = str(code or '').strip().lower()
    joined = ' '.join((message, code, error_type, error_text or '')).lower()
    if normalized_code in {'model_not_found', 'model_not_available', 'unsupported_model'}:
        return True
    return any(
        marker in joined
        for marker in (
            'no available channel for model',
            'model is not available',
            'model not found',
            'unsupported model',
        )
    )


def _normalize_openai_chat_max_tokens(value) -> int:
    try:
        tokens = int(value)
    except Exception:
        tokens = 4096
    return tokens if tokens > 0 else 4096


def _openai_chat_payload(
    model,
    content,
    max_tokens=4096,
    temperature=None,
    google_image_config=None,
    preserve_model=False,
) -> dict:
    payload_model = str(model or '').replace('google/', '').strip()
    payload = {
        "model": payload_model if preserve_model and payload_model else _normalize_openai_chat_model(model),
        "stream": False,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": _normalize_openai_chat_max_tokens(max_tokens),
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if isinstance(google_image_config, dict) and google_image_config:
        payload["extra_body"] = {
            "google": {
                "image_config": {
                    key: value
                    for key, value in google_image_config.items()
                    if value is not None and value != ''
                }
            }
        }
    return payload


def _extract_http_error_detail(error_text: str) -> tuple[str, str, str]:
    try:
        data = json.loads(error_text or '{}')
    except Exception:
        return '', '', ''
    if isinstance(data, dict) and not isinstance(data.get('error'), dict):
        return (
            str(data.get('message') or '').strip(),
            str(data.get('code') or '').strip(),
            str(data.get('type') or data.get('status') or '').strip(),
        )
    error = data.get('error') if isinstance(data, dict) else {}
    if not isinstance(error, dict):
        return '', '', ''
    return (
        str(error.get('message') or '').strip(),
        str(error.get('code') or '').strip(),
        str(error.get('type') or '').strip(),
    )


def _format_http_error(status_code: int, error_text: str) -> tuple[str, str]:
    message, code, error_type = _extract_http_error_detail(error_text)
    joined = ' '.join(part for part in (message, code, error_type) if part).lower()
    if 'insufficient_quota' in joined or 'pre-consumed quota failed' in joined or 'need quota' in joined:
        detail = message or code or error_text
        return f"Google / Gemini 兼容接口额度不足：{detail[:240]}", 'quota'
    if message:
        return f"HTTP 错误 {status_code}：{message[:240]}", f'http_{status_code}'
    return f"HTTP 错误 {status_code}", f'http_{status_code}'


def _extract_image_from_json(data: dict):
    if not data.get('candidates'):
        if data.get('promptFeedback') and data['promptFeedback'].get('blockReason'):
            raise Exception(f"内容安全过滤：{data['promptFeedback']['blockReason']}")
        raise Exception("API 响应无 candidates 字段")

    candidate = data['candidates'][0]
    finish_reason = candidate.get('finishReason', '')
    if finish_reason in ['SAFETY', 'IMAGE_SAFETY', 'BLOCKLIST', 'PROHIBITED_CONTENT']:
        raise Exception(f"内容安全过滤：{finish_reason}")

    parts = candidate.get('content', {}).get('parts', [])
    if not parts:
        raise Exception("API 响应无 parts 字段")

    part = parts[0]
    if 'text' in part and 'inlineData' not in part:
        text = part.get('text', '')
        if 'error' in text.lower() or 'failed' in text.lower() or '拒绝' in text:
            raise Exception(f"服务端拒绝：{text[:200]}")
        elif 'filter' in text.lower() or '安全' in text:
            raise Exception(f"内容安全过滤：{text[:200]}")
        else:
            raise Exception(f"服务端返回文本而非图片：{text[:200]}")

    if 'inlineData' not in part:
        print(f"❌ 完整响应：{json.dumps(data, ensure_ascii=False)[:1000]}")
        raise Exception(f"API 响应缺少 inlineData: {list(part.keys())}")

    return base64.b64decode(part['inlineData']['data'])


def _looks_like_image_bytes(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or data.startswith(b"RIFF") and b"WEBP" in data[:16]
    )


def _decode_image_data_uri(value: str) -> bytes | None:
    text = str(value or "").strip()
    if not text.startswith("data:image/") or "," not in text:
        return None
    try:
        return base64.b64decode(text.split(",", 1)[1])
    except Exception:
        return None


def _decode_possible_image_base64(value: str) -> bytes | None:
    text = re.sub(r"\s+", "", str(value or ""))
    if len(text) < 32:
        return None
    try:
        data = base64.b64decode(text, validate=True)
    except Exception:
        return None
    return data if _looks_like_image_bytes(data) else None


def _download_image_url(url: str) -> bytes | None:
    cleaned = str(url or "").strip().strip(".,;")
    if not cleaned.startswith(("http://", "https://")):
        return None
    response = _session.get(cleaned, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True)
    if response.status_code >= 400:
        raise Exception(f"图片下载失败 HTTP {response.status_code}: {response.text[:200]}")
    content = response.content
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if content and (content_type.startswith("image/") or _looks_like_image_bytes(content)):
        return content
    return None


def _iter_json_values(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_json_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_json_values(item)
    else:
        yield value


def _extract_image_from_openai_chat(data: dict):
    """Extract image bytes from OpenAI-compatible chat completion variants."""
    if not isinstance(data, dict):
        raise Exception("API 响应不是 JSON 对象")

    for value in _iter_json_values(data):
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text:
            continue

        for match in DATA_URI_RE.findall(text):
            decoded = _decode_image_data_uri(match)
            if decoded:
                return decoded

        decoded = _decode_possible_image_base64(text)
        if decoded:
            return decoded

    for value in _iter_json_values(data):
        if not isinstance(value, str):
            continue
        text = value.strip()
        for url in URL_RE.findall(text):
            downloaded = _download_image_url(url)
            if downloaded:
                return downloaded

        if text.startswith(("{", "[")):
            try:
                decoded_json = json.loads(text)
            except Exception:
                decoded_json = None
            if decoded_json is not None:
                try:
                    return _extract_image_from_openai_chat(decoded_json)
                except Exception:
                    pass

    snippets = []
    for value in _iter_json_values(data):
        if isinstance(value, str) and value.strip():
            snippets.append(value.strip()[:180])
        if len(snippets) >= 3:
            break
    detail = "；".join(snippets) if snippets else json.dumps(data, ensure_ascii=False)[:300]
    raise Exception(f"API 响应未包含图片数据：{detail}")


def _perform_request(
    url,
    payload,
    progress_cb=None,
    action='generate',
    extractor=None,
    stream_response=True,
    connect_timeout=CONNECT_TIMEOUT,
):
    api_key = _ensure_api_key()
    progress_cb = progress_cb or _default_progress_cb
    extractor = extractor or _extract_image_from_json
    started_at_ms = _now_ms()
    started_monotonic = time.monotonic()
    progress_cb(stage='calling_api', progress_text=f'正在调用 AI 模型（{action}）...', heartbeat=True)

    documented_native = change2pro.is_change2pro(url) and _url_path(url).startswith('/v1beta/models/')
    # An interrupted generation POST may already have been billed upstream.
    # Do not replay it or silently redirect it to a different endpoint.
    max_attempts = 1 if documented_native else 1 + MAX_HTTP_RETRIES
    request_options = {}
    if documented_native:
        request_options = {
            'headers': {'x-goog-api-key': api_key, 'Authorization': None,
                        'Accept': 'text/event-stream' if ':streamGenerateContent' in url else 'application/json',
                        'Accept-Encoding': 'identity'},
            'allow_redirects': False,
        }
    response = None
    bytes_received = 0
    first_byte_at_ms = None

    for attempt in range(1, max_attempts + 1):
        attempt_started_ms = _now_ms()
        try:
            response = _session.post(url, json=payload,
                # requests/urllib3 also applies the first timeout while writing
                # the request body. Image-edit JSON can contain large base64 data.
                timeout=(connect_timeout, READ_TIMEOUT), stream=bool(stream_response), **request_options)
        except Exception as e:
            err_type = _classify_transport_error(e, bytes_received)
            print(f"❌ 请求发送失败: {e}")
            if _is_retryable_request_exception(e) and attempt < max_attempts:
                wait_s = HTTP_RETRY_BACKOFF_SECONDS * attempt
                print(f"⚠️ 连接异常 {err_type}，第 {attempt}/{max_attempts} 次失败，{wait_s}s 后重试")
                progress_cb(stage='retrying', progress_text=f'连接异常，准备重试：{err_type}', transport_error_type=err_type, heartbeat=True)
                time.sleep(wait_s)
                continue
            progress_cb(stage='failed', progress_text=f'请求发送失败：{str(e)[:120]}',
                transport_error_type=err_type, bytes_received=bytes_received)
            raise

        if response.status_code == 200:
            print(f"📬 已收到响应头，耗时 {(_now_ms() - attempt_started_ms) / 1000:.2f}s")
            progress_cb(stage='waiting_first_byte', progress_text='已连接上游，等待首字节...', heartbeat=True)
            break

        error_text = response.text[:500]
        response.close()
        if _is_model_unavailable_http_error(response.status_code, error_text):
            formatted_error, _ = _format_http_error(response.status_code, error_text)
            message, code, error_type = _extract_http_error_detail(error_text)
            print(f"⚠️ 当前模型渠道不可用，不再重复请求同一模型：{message or code or error_text}")
            progress_cb(
                stage='retrying',
                progress_text='当前模型名称不可用，正在自动匹配兼容名称...',
                heartbeat=True,
            )
            raise ModelUnavailableError(
                formatted_error,
                status_code=response.status_code,
                error_code=code,
                error_type=error_type,
            )
        if response.status_code in RETRYABLE_HTTP_STATUS and attempt < max_attempts:
            wait_s = HTTP_RETRY_BACKOFF_SECONDS * attempt
            print(f"⚠️ HTTP {response.status_code}，第 {attempt}/{max_attempts} 次失败，{wait_s}s 后重试")
            progress_cb(stage='retrying', progress_text=f'上游 HTTP {response.status_code}，准备重试...', heartbeat=True)
            time.sleep(wait_s)
            continue

        formatted_error, transport_type = _format_http_error(response.status_code, error_text)
        print(f"❌ HTTP 错误 {response.status_code}: {error_text}")
        progress_cb(stage='failed', progress_text=formatted_error[:160],
            transport_error_type=transport_type)
        raise Exception(formatted_error)

    if response is None:
        raise Exception('请求未获得响应')

    print('📥 接收响应数据（流式）...')
    content = bytearray()
    native_reader = GeminiImageResponse() if documented_native else None
    image_data = None
    sha256 = hashlib.sha256()
    last_heartbeat_ms = _now_ms()

    try:
        for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
            if native_reader is not None and time.monotonic() - started_monotonic >= READ_TIMEOUT:
                raise requests.exceptions.Timeout('Google 响应接收超过期限，未自动重新提交')
            now_ms = _now_ms()
            if chunk:
                if first_byte_at_ms is None:
                    first_byte_at_ms = now_ms
                    ttfb_ms = first_byte_at_ms - started_at_ms
                    print(f"🚀 收到首字节，TTFB = {ttfb_ms / 1000:.2f}s")
                    progress_cb(stage='downloading', progress_text='已收到首字节，正在接收图片数据...',
                        first_byte_at=int(first_byte_at_ms / 1000), ttfb_ms=ttfb_ms,
                        bytes_received=bytes_received, heartbeat=True)
                if native_reader is None:
                    content.extend(chunk)
                sha256.update(chunk)
                bytes_received += len(chunk)
                if bytes_received % (1024 * 1024) < CHUNK_SIZE:
                    print(f"   已接收：{bytes_received / 1024 / 1024:.1f} MB")
                if now_ms - last_heartbeat_ms >= 15000:
                    progress_cb(stage='downloading',
                        progress_text=f'正在接收数据：{bytes_received / 1024 / 1024:.1f} MB',
                        bytes_received=bytes_received, heartbeat=True)
                    last_heartbeat_ms = now_ms
                if native_reader is not None:
                    image_data = native_reader.feed(chunk)
                    if image_data is not None or native_reader.done:
                        break
            elif now_ms - last_heartbeat_ms >= 15000:
                progress_cb(stage='waiting_first_byte', progress_text='等待上游返回数据...', heartbeat=True)
                last_heartbeat_ms = now_ms

        print(f"✅ 接收完成：{bytes_received / 1024:.1f} KB")
        progress_cb(stage='download_complete',
            progress_text=f'响应接收完成：{bytes_received / 1024 / 1024:.1f} MB',
            bytes_received=bytes_received, heartbeat=True)
        if native_reader is not None:
            image_data = native_reader.finish()
        else:
            data = json.loads(bytes(content).decode('utf-8'))
            image_data = extractor(data)
        print(f"🔐 响应 SHA256：{sha256.hexdigest()[:16]}...")
        return image_data, {
            'bytes_received': bytes_received,
            'first_byte_at': int(first_byte_at_ms / 1000) if first_byte_at_ms else None,
            'ttfb_ms': (first_byte_at_ms - started_at_ms) if first_byte_at_ms else None,
            'response_sha256': sha256.hexdigest(),
            **({'response_protocol': native_reader.mode,
                'response_event_count': native_reader.event_count,
                'request_endpoint': _url_path(url),
                'response_request_id': response.headers.get('x-request-id', '')}
               if native_reader is not None else {}),
        }
    except Exception as e:
        err_type = _classify_transport_error(e, bytes_received)
        progress_cb(stage='failed', progress_text=f'上游响应失败：{str(e)[:120]}',
            transport_error_type=err_type, bytes_received=bytes_received,
            first_byte_at=int(first_byte_at_ms / 1000) if first_byte_at_ms else None,
            ttfb_ms=(first_byte_at_ms - started_at_ms) if first_byte_at_ms else None,
            heartbeat=True)
        raise
    finally:
        response.close()


def _perform_request_with_model_aliases(
    api_base,
    requested_model,
    request_builder,
    *,
    progress_cb=None,
    action='generate',
    connect_timeout=CONNECT_TIMEOUT,
):
    """Try equivalent provider model names and remember the one accepted by this key."""
    progress_cb = progress_cb or _default_progress_cb
    normalized_requested = _normalize_openai_chat_model(requested_model)
    if change2pro.uses_documented_google_api(api_base):
        normalized_requested = _requested_native_model(requested_model)
    candidates = _ordered_model_candidates(api_base, requested_model)

    for index, candidate in enumerate(candidates):
        url, payload, extractor, stream_response = request_builder(candidate)
        print(f'📡 请求模型: {candidate}')
        print(f'📡 请求 URL: {url}')
        try:
            image_data, meta = _perform_request(
                url,
                payload,
                progress_cb=progress_cb,
                action=action,
                extractor=extractor,
                stream_response=stream_response,
                connect_timeout=connect_timeout,
            )
        except ModelUnavailableError:
            if index + 1 >= len(candidates):
                raise
            next_candidate = candidates[index + 1]
            print(f'🔁 模型名称自动适配：{candidate} -> {next_candidate}')
            progress_cb(
                stage='retrying',
                progress_text=f'模型名称自动适配：{candidate} → {next_candidate}',
                heartbeat=True,
            )
            continue

        _remember_resolved_model(api_base, requested_model, candidate)
        response_meta = dict(meta or {})
        response_meta.update({
            'requested_model': normalized_requested,
            'resolved_model': candidate,
            'model_alias_fallback': candidate != normalized_requested,
        })
        return image_data, response_meta

    raise Exception('没有可用的 Google 图像模型名称')


def generate_image(
    prompt,
    aspect_ratio='1:1',
    quality='hd',
    model=DEFAULT_OPENAI_CHAT_IMAGE_MODEL,
    max_tokens=4096,
    temperature=None,
    progress_cb=None,
):
    """调用 nano banana / Google-compatible API 生成图片"""
    normalized_quality = (quality or '2k').lower()
    if normalized_quality == '1k':
        image_size = '1K'
    elif normalized_quality in ('4k', 'hd'):
        image_size = '4K'
    else:
        image_size = '2K'

    actual_prompt = prompt
    try:
        prompt_data = json.loads(prompt)
        if isinstance(prompt_data, dict):
            if 'prompt_elements' in prompt_data:
                elements = prompt_data.get('prompt_elements', {})
                parts = []
                if 'left_woman' in elements:
                    lw = elements['left_woman']
                    parts.append(f"左边女性：{lw.get('appearance', '')}，穿着{lw.get('clothing', '')}，{lw.get('legs_feet', '')}，姿势：{lw.get('pose', '')}")
                if 'right_woman' in elements:
                    rw = elements['right_woman']
                    parts.append(f"右边女性：{rw.get('appearance', '')}，穿着{rw.get('clothing', '')}，{rw.get('legs_feet', '')}，姿势：{rw.get('pose', '')}")
                if 'environment' in elements:
                    env = elements['environment']
                    parts.append(f"环境：{env.get('furniture', '')}，{env.get('background', '')}，氛围：{env.get('atmosphere', '')}")
                if 'technical' in elements:
                    tech = elements['technical']
                    parts.append(f"摄影风格：{tech.get('style', '')}，{tech.get('camera', '')}，{tech.get('lens', '')}")
                actual_prompt = '。'.join(parts)
            elif 'source_image_analysis' in prompt_data:
                analysis = prompt_data.get('source_image_analysis', {})
                actual_prompt = f"{analysis.get('subjects', '')}，{analysis.get('setting', '')}，{analysis.get('perspective', '')}，{analysis.get('lighting', '')}"
            print(f"📝 JSON prompt 已解析，实际 prompt 长度：{len(actual_prompt)}")
    except json.JSONDecodeError:
        pass

    api_base = _api_base()
    documented_native = change2pro.uses_documented_google_api(api_base)
    api_model = (_requested_native_model(model)
                 if documented_native else _normalize_openai_chat_model(model))
    
    payload = {
        'contents': [{'parts': [{'text': actual_prompt}]}],
        'generationConfig': {
            'aspectRatio': aspect_ratio,
            'imageConfig': {
                'aspectRatio': aspect_ratio,
                'imageSize': image_size,
            },
        },
    }

    uses_openai_chat = _uses_openai_chat_endpoint(api_base)
    if documented_native:
        payload = change2pro.google_payload(actual_prompt, aspect_ratio, image_size)
    elif not uses_openai_chat and 'flash' in api_model.lower():
        payload['stream'] = True
        print(f'🚀 使用流式请求 (stream: true)')

    print('📡 发送 API 请求...')
    print(f'📊 Prompt 长度：{len(actual_prompt)} 字符')
    print(f'📋 aspect_ratio: {aspect_ratio}, quality: {quality}, image_size: {image_size}')

    try:
        if uses_openai_chat:
            url = _chat_completions_url(api_base)
            chat_prompt = "\n".join([
                "Generate exactly one image from the prompt below.",
                f"Aspect ratio: {aspect_ratio}.",
                f"Requested image size: {image_size}.",
                "Return image data or an image URL in the response.",
                "",
                actual_prompt,
            ])

            def request_builder(candidate):
                chat_payload = _openai_chat_payload(
                    candidate,
                    chat_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    google_image_config={
                        "image_size": image_size,
                        "aspect_ratio": aspect_ratio,
                    },
                    preserve_model=True,
                )
                return url, chat_payload, _extract_image_from_openai_chat, False
        else:
            def request_builder(candidate):
                if documented_native:
                    return change2pro.google_url(api_base, candidate, stream=image_size == '4K'), payload, _extract_image_from_json, True
                return _gemini_generate_url(api_base, candidate), payload, _extract_image_from_json, True

        image_data, meta = _perform_request_with_model_aliases(
            api_base,
            api_model,
            request_builder,
            progress_cb=progress_cb,
            action='generate',
        )
        if documented_native:
            meta.update(change2pro.output_metadata(image_data, aspect_ratio, image_size))
        print(f"✅ API 响应成功，图片大小：{len(image_data) / 1024 / 1024:.1f} MB")
        return image_data, meta
    except requests.exceptions.Timeout:
        raise Exception('请求超时')
    except requests.exceptions.ConnectionError as e:
        error_msg = str(e)
        if 'remote end closed' in error_msg.lower() or 'connection reset' in error_msg.lower():
            raise Exception(f"服务端响应中断 ({error_msg})")
        raise
    except Exception as e:
        if not str(e).startswith('内容安全'):
            print(f'❌ 请求失败：{e}')
        raise


def edit_image(
    prompt,
    images,
    aspect_ratio='1:1',
    quality='hd',
    model=DEFAULT_OPENAI_CHAT_IMAGE_MODEL,
    max_tokens=4096,
    temperature=None,
    progress_cb=None,
):
    """调用 nano banana / Google-compatible API 编辑图片"""
    normalized_quality = (quality or 'hd').lower()
    image_size = '4K' if normalized_quality in ('4k', 'hd') else '2K'

    api_base = _api_base()
    documented_native = change2pro.uses_documented_google_api(api_base)
    if documented_native and normalized_quality == '1k':
        image_size = '1K'
    api_model = (_requested_native_model(model)
                 if documented_native else _normalize_openai_chat_model(model))
    parts = []
    for img in images:
        img_base64 = img.split(',')[1] if ',' in img else img
        parts.append({'inlineData': {'mimeType': 'image/png', 'data': img_base64}})
    parts.append({'text': prompt})

    payload = {
        'contents': [{'parts': parts}],
        'generationConfig': {
            'aspectRatio': aspect_ratio,
            'imageConfig': {
                'aspectRatio': aspect_ratio,
                'imageSize': image_size,
            },
        },
    }
    if documented_native:
        payload = change2pro.google_payload(prompt, aspect_ratio, image_size, images)

    try:
        print('📡 发送编辑 API 请求...')
        print(f'📊 图片数量：{len(images)}')
        print(f'📊 Prompt 长度：{len(prompt)} 字符')
        if _uses_openai_chat_endpoint(api_base):
            url = _chat_completions_url(api_base)
            content = [
                {
                    "type": "text",
                    "text": "\n".join([
                        "Edit the provided image(s) according to the instruction below.",
                        f"Aspect ratio: {aspect_ratio}.",
                        f"Requested image size: {image_size}.",
                        "Return the edited image data or an image URL in the response.",
                        "",
                        prompt,
                    ]),
                }
            ]
            for img in images:
                img_text = str(img or "").strip()
                image_url = img_text if img_text.startswith("data:") else f"data:image/png;base64,{img_text.split(',', 1)[-1]}"
                content.append({"type": "image_url", "image_url": {"url": image_url}})

            def request_builder(candidate):
                chat_payload = _openai_chat_payload(
                    candidate,
                    content,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    google_image_config={
                        "image_size": image_size,
                        "aspect_ratio": aspect_ratio,
                    },
                    preserve_model=True,
                )
                return url, chat_payload, _extract_image_from_openai_chat, False
        else:
            def request_builder(candidate):
                if documented_native:
                    return change2pro.google_url(api_base, candidate, stream=True), payload, _extract_image_from_json, True
                return _gemini_generate_url(api_base, candidate), payload, _extract_image_from_json, True

        image_data, meta = _perform_request_with_model_aliases(
            api_base,
            api_model,
            request_builder,
            progress_cb=progress_cb,
            action='edit',
            connect_timeout=EDIT_UPLOAD_SOCKET_TIMEOUT,
        )
        if documented_native:
            meta.update(change2pro.output_metadata(image_data, aspect_ratio, image_size))
        print(f"✅ 编辑成功，图片大小：{len(image_data) / 1024 / 1024:.1f} MB")
        return image_data, meta
    except Exception as e:
        print(f'❌ 编辑失败：{e}')
        raise


def save_image(image_data, filepath):
    """保存图片到文件"""
    with open(filepath, 'wb') as f:
        f.write(image_data)
    print(f'💾 已保存：{filepath}')
    return os.path.basename(filepath)


def send_telegram(chat_id, photo_path, caption=''):
    """发送原图到 Telegram（使用 sendDocument，不压缩）"""
    telegram_cfg = load_telegram_delivery_config()
    bot_token = telegram_cfg.get('bot_token', '')
    resolved_chat_id = str(chat_id or telegram_cfg.get('chat_id', '') or '')
    proxy_url = telegram_cfg.get('proxy_url', '')

    if not bot_token:
        print('⚠️ Telegram bot token 未配置，跳过发送')
        return False
    if not resolved_chat_id:
        print('⚠️ Telegram chat_id 未配置，跳过发送')
        return False

    url = f'https://api.telegram.org/bot{bot_token}/sendDocument'
    telegram_session = requests.Session()
    telegram_session.trust_env = False
    telegram_session.proxies = {'http': proxy_url, 'https': proxy_url} if proxy_url else {}
    telegram_session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; TelegramSendBot/1.0)'})

    try:
        if proxy_url:
            print(f'📡 Telegram 发送使用显式代理: {proxy_url}')
        with open(photo_path, 'rb') as f:
            response = telegram_session.post(url,
                data={'chat_id': resolved_chat_id, 'caption': caption},
                files={'document': f}, timeout=120)
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                print(f'✅ Telegram 发送原图成功：message_id={result.get("result", {}).get("message_id")}')
                return True
            print(f'⚠️ Telegram 返回错误：{result}')
        else:
            print(f'❌ HTTP 错误 {response.status_code}: {response.text[:200]}')
        return False
    except Exception as e:
        print(f'❌ 发送失败：{e}')
        return False
    finally:
        try:
            telegram_session.close()
        except Exception:
            pass


if __name__ == '__main__':
    print('=== 测试 nano banana API ===')
    try:
        img, meta = generate_image('a cute cat', '1:1', '2k', 'gemini-3.1-flash-image')
        print(f"✅ 成功！{len(img) / 1024 / 1024:.1f} MB, meta={meta}")
        save_image(img, Path.home() / 'Downloads' / 'test_nano_banana.png')
    except Exception as e:
        print(f'❌ 失败：{e}')
