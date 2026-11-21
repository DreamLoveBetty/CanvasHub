"""Google OAuth / Cloud Code HTTP only; no persistence or account selection.

Single POST per generation: a timeout/disconnect never triggers a blind retry.
"""

from __future__ import annotations
import json
import platform
import logging
import re
import time
import uuid
import requests
from .errors import GoogleError

# Structured Google RPC symbols only; never treat reason/message as free text.
_SAFE_REASON_RE = re.compile(r'^[A-Z][A-Z0-9._-]{0,63}$')
_ERROR_BODY_LIMIT = 8192
_MAX_REASONS = 2
_MAX_DETAILS = 8

logger = logging.getLogger(__name__)
CONNECT_TIMEOUT = 15
# requests applies the connect timeout to the whole body upload (socket sendall is
# bounded in total, not per write), so reference images need time proportional to size.
MIN_UPLOAD_BYTES_PER_SECOND = 64 * 1024
MAX_UPLOAD_TIMEOUT = 600


def upload_timeout(size):
    return min(MAX_UPLOAD_TIMEOUT, CONNECT_TIMEOUT + size / MIN_UPLOAD_BYTES_PER_SECOND)

TOKEN_URL = 'https://oauth2.googleapis.com/token'
PROFILE_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'


PLACEHOLDER_CLOUD_CODE_PROJECT = 'aicode-consumers'
OFFICIAL_DAILY_UPSTREAM = 'https://daily-cloudcode-pa.googleapis.com/v1internal'
OFFICIAL_PROD_UPSTREAM = 'https://cloudcode-pa.googleapis.com/v1internal'
DEFAULT_CLOUD_CODE_IDE_VERSION = '2.25.0'
CLOUD_CODE_CL = '1003475615'
CLOUD_CODE_IDE_VERSION = '2.33.0'


def valid_cloud_code_project_id(project):
    if not isinstance(project, str):
        return None
    value = project.strip()
    if not value or value == PLACEHOLDER_CLOUD_CODE_PROJECT:
        return None
    return value


def quota_request_payload(project=None):
    value = valid_cloud_code_project_id(project)
    return {'project': value} if value else {}


def quota_upstream_url(project=None, is_gcp_tos=None):
    if is_gcp_tos is True and valid_cloud_code_project_id(project):
        return OFFICIAL_PROD_UPSTREAM
    return OFFICIAL_DAILY_UPSTREAM

def _parse_semver_tuple(version):
    if not isinstance(version, str):
        return None
    parts = []
    current = ''
    for char in version.strip().lstrip('v'):
        if char.isdigit():
            current += char
        elif current:
            parts.append(current)
            current = ''
        if len(parts) == 3:
            break
    if current and len(parts) < 3:
        parts.append(current)
    if not parts:
        return None
    try:
        numbers = [int(parts[0]), int(parts[1]) if len(parts) > 1 else 0, int(parts[2]) if len(parts) > 2 else 0]
    except ValueError:
        return None
    return tuple(numbers)


def resolve_cloud_code_ide_version(version=None):
    raw = DEFAULT_CLOUD_CODE_IDE_VERSION if version is None else str(version)
    detected = _parse_semver_tuple(raw)
    minimum = _parse_semver_tuple(DEFAULT_CLOUD_CODE_IDE_VERSION)
    if detected and minimum and detected >= minimum:
        return raw.strip()
    return DEFAULT_CLOUD_CODE_IDE_VERSION


def cloud_code_os_name(value=None):
    raw = (value or platform.system() or '').strip().lower()
    if raw in ('darwin', 'macos', 'osx', 'mac'):
        return 'darwin'
    if raw in ('windows', 'win32', 'win'):
        return 'windows'
    if raw == 'linux':
        return 'linux'
    return 'darwin'


def cloud_code_arch(value=None):
    raw = (value or platform.machine() or '').strip().lower()
    if raw in ('x86_64', 'amd64', 'x64'):
        return 'amd64'
    if raw in ('aarch64', 'arm64'):
        return 'arm64'
    return 'arm64'


def build_cloud_code_user_agent(ide_version=None, os_name=None, arch=None):
    version = resolve_cloud_code_ide_version(
        CLOUD_CODE_IDE_VERSION if ide_version is None else ide_version
    )
    os_value = cloud_code_os_name(os_name)
    arch_value = cloud_code_arch(arch)
    return (
        f'antigravity/{version} (aidev_client; os_type={os_value}; '
        f'arch={arch_value}; cl={CLOUD_CODE_CL})'
    )





def _safe_reason(value):
    if not isinstance(value, str):
        return None
    symbol = value.strip()
    return symbol if _SAFE_REASON_RE.fullmatch(symbol) else None


def _bounded_error_bytes(response, limit=_ERROR_BODY_LIMIT):
    buf = bytearray()
    iterator = getattr(response, 'iter_content', None)
    if not callable(iterator):
        return b''
    try:
        stream = iterator(chunk_size=min(1024, limit))
    except TypeError:
        try:
            stream = iterator()
        except Exception:
            return b''
    try:
        for chunk in stream:
            if not chunk:
                continue
            if isinstance(chunk, str):
                chunk = chunk.encode('utf-8', 'replace')
            elif not isinstance(chunk, (bytes, bytearray)):
                continue
            remaining = limit - len(buf)
            if remaining <= 0:
                break
            buf.extend(chunk[:remaining])
            if len(buf) >= limit:
                break
    except Exception:
        pass
    return bytes(buf)


def _parse_error_payload(raw):
    if not raw:
        return None
    try:
        value = json.loads(raw.decode('utf-8', 'replace'))
    except (UnicodeError, ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_upstream_reasons(payload):
    reasons = []

    def add(value):
        symbol = _safe_reason(value)
        if symbol and symbol not in reasons:
            reasons.append(symbol)

    if not isinstance(payload, dict):
        return reasons
    error = payload.get('error')
    if not isinstance(error, dict):
        return reasons
    details = error.get('details')
    if isinstance(details, list):
        for item in details[:_MAX_DETAILS]:
            if not isinstance(item, dict):
                continue
            add(item.get('reason'))
            info = item.get('errorInfo')
            if isinstance(info, dict):
                add(info.get('reason'))
            if len(reasons) >= _MAX_REASONS:
                return reasons[:_MAX_REASONS]
    # status/code are fallbacks only when details did not yield a safe reason.
    if not reasons:
        add(error.get('status'))
        code = error.get('code')
        if isinstance(code, str):
            add(code)
    return reasons[:_MAX_REASONS]


class GoogleUpstream:
    def __init__(self, settings, session_factory=requests.Session):
        self.settings = settings
        self.session_factory = session_factory

    def session(self):
        s = self.session_factory()
        s.trust_env = False
        if self.settings.proxy_url:
            s.proxies.update(
                {'http': self.settings.proxy_url, 'https': self.settings.proxy_url}
            )
        return s

    @staticmethod
    def checked_json(response, operation):
        if not 200 <= response.status_code < 300:
            code = (
                'google_auth_expired'
                if response.status_code == 401
                else 'google_upstream_error'
            )
            if response.status_code == 429:
                code = 'google_quota_exhausted'
            # Bounded, allowlisted reason symbols only. Never echo body/headers/message.
            reasons = _safe_upstream_reasons(_parse_error_payload(_bounded_error_bytes(response)))
            detail = f'（HTTP {response.status_code}）'
            if reasons:
                detail = f'（HTTP {response.status_code}，{"，".join(reasons)}）'
            raise GoogleError(
                f'{operation}失败{detail}',
                response.status_code if 400 <= response.status_code < 600 else 502,
                code,
                reasons=reasons,
                http_status_rejection=True,
            )
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise GoogleError(f'{operation}返回了无效 JSON')

    def token(self, values):
        data = dict(
            values,
            client_id=self.settings.client_id,
            client_secret=self.settings.client_secret,
        )
        try:
            with self.session() as s, s.post(
                TOKEN_URL, data=data, timeout=(15, 45), allow_redirects=False
            ) as r:
                if r.status_code == 400:
                    try:
                        if r.json().get('error') == 'invalid_grant':
                            raise GoogleError(
                                'Google 授权失效，请重新登录',
                                401,
                                'google_auth_expired',
                            )
                    except ValueError:
                        pass
                result = self.checked_json(r, 'Google OAuth')
                if (
                    not isinstance(result.get('access_token'), str)
                    or not result['access_token']
                ):
                    raise GoogleError('OAuth 响应缺少 access_token')
                try:
                    result['expires_in'] = max(1, int(result.get('expires_in') or 3600))
                except (ValueError, TypeError):
                    raise GoogleError('OAuth 响应的到期时间无效') from None
                return result
        except requests.RequestException:
            raise GoogleError(
                'Google OAuth 网络请求失败', 502, 'google_network_error'
            ) from None

    def profile(self, access):
        try:
            with self.session() as s, s.get(
                PROFILE_URL,
                headers={'Authorization': 'Bearer ' + access},
                timeout=(15, 30),
                allow_redirects=False,
            ) as r:
                return self.checked_json(r, 'Google 账号信息')
        except requests.RequestException:
            raise GoogleError('Google 账号信息网络请求失败') from None

    def metadata(self, access, method, payload, *, is_gcp_tos=None):
        if method not in ('loadCodeAssist', 'fetchAvailableModels'):
            raise ValueError('Unsupported metadata operation')
        body = payload
        if method == 'fetchAvailableModels':
            project = payload.get('project') if isinstance(payload, dict) else None
            body = quota_request_payload(project)
            url = quota_upstream_url(project=body.get('project'), is_gcp_tos=is_gcp_tos)
        else:
            url = self.settings.upstream
        request_headers = (
            self.quota_headers(access)
            if method == 'fetchAvailableModels'
            else self.headers(access)
        )
        try:
            with self.session() as s, s.post(
                url + ':' + method,
                json=body,
                headers=request_headers,
                timeout=(15, 45),
                allow_redirects=False,
            ) as r:
                return self.checked_json(r, 'Google 模型信息')
        except requests.RequestException:
            raise GoogleError('Google 模型信息网络请求失败') from None

    def quota_summary(self, access, project=None, *, is_gcp_tos=None):
        payload = quota_request_payload(project)
        url = quota_upstream_url(project=payload.get('project'), is_gcp_tos=is_gcp_tos)
        try:
            with self.session() as s, s.post(
                url + ':retrieveUserQuotaSummary',
                json=payload,
                headers=self.quota_headers(access),
                timeout=(15, 45),
                allow_redirects=False,
            ) as r:
                return self.checked_json(r, 'Google 分组额度')
        except requests.RequestException:
            raise GoogleError('Google 分组额度网络请求失败') from None

    @staticmethod
    def headers(access):
        return {
            'Authorization': 'Bearer ' + access,
            'User-Agent': 'antigravity',
            'x-client-name': 'antigravity',
            'Content-Type': 'application/json',
        }

    def quota_headers(self, access):
        version = getattr(self.settings, 'cloud_code_ide_version', None) or CLOUD_CODE_IDE_VERSION
        return {
            'Authorization': 'Bearer ' + access,
            'User-Agent': build_cloud_code_user_agent(ide_version=version),
            'Accept-Encoding': 'gzip',
            'Content-Type': 'application/json',
        }

    def generate(self, account, model, request, cancelled=None):
        payload = {
            'project': account['project_id'],
            'model': model,
            'userAgent': 'antigravity',
            'requestType': 'image_gen',
            'requestId': f'agent/{int(time.time() * 1000)}/{uuid.uuid4().hex[:8]}',
            'request': request,
        }
        size = len(json.dumps(payload))
        started = time.monotonic()
        deadline = started + self.settings.timeout
        phase = 'connect'
        decoder = None
        try:
            with self.session() as s, s.post(
                self.settings.upstream + ':streamGenerateContent?alt=sse',
                json=payload,
                headers=self.headers(account['access_token']),
                stream=True,
                timeout=(upload_timeout(size), self.settings.timeout),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    self.checked_json(r, 'Google 图像生成')
                from .wire import ImageResponse

                phase = 'stream'
                decoder = ImageResponse()
                for chunk in r.iter_content(chunk_size=8192):
                    if cancelled and cancelled.is_set():
                        raise GoogleError(
                            'Google 生成已取消；未重新提交', 499, 'cancelled'
                        )
                    if time.monotonic() > deadline:
                        raise GoogleError(
                            'Google 生成超过等待期限；未重新提交', 504, 'google_timeout'
                        )
                    result = decoder.feed(chunk)
                    if result is not None:
                        return result
                result = decoder.finish()
                if result is None:
                    raise GoogleError('Google 未返回图片', 502, 'google_no_image')
                return result
        except requests.RequestException as e:
            # The cause is the only clue to where the request died; keep it, minus URLs/headers.
            kind = type(e).__name__
            elapsed = time.monotonic() - started
            received = decoder.total if decoder else 0
            logger.warning(
                'Google image stream failed: %s phase=%s elapsed=%.1fs sent=%d bytes=%d '
                'mode=%s account=%s model=%s request=%s',
                kind, phase, elapsed, size, received, decoder.mode if decoder else None,
                account.get('id'), model, payload['requestId'],
            )
            raise GoogleError(
                f'Google 图像连接中断或超时（{kind}，{phase}，{elapsed:.0f}s，'
                f'请求 {size / 1048576:.1f}MB，已收 {received} 字节）；'
                '上游执行状态未知，未重新提交',
                502,
                'google_execution_unknown',
            ) from None

    def stream_text(self, account, model, request, cancelled=None):
        payload = {
            'project': account['project_id'],
            'model': model,
            'userAgent': 'antigravity',
            'requestType': 'agent',
            'requestId': f'agent/{int(time.time() * 1000)}/{uuid.uuid4().hex[:8]}',
            'request': request,
        }
        size = len(json.dumps(payload))
        started = time.monotonic()
        deadline = started + self.settings.timeout
        phase = 'connect'
        decoder = None
        try:
            with self.session() as s, s.post(
                self.settings.upstream + ':streamGenerateContent?alt=sse',
                json=payload,
                headers=self.headers(account['access_token']),
                stream=True,
                timeout=(upload_timeout(size), self.settings.timeout),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    self.checked_json(r, 'Google LLM 推理')
                from .wire import TextResponse

                phase = 'stream'
                decoder = TextResponse()
                for chunk in r.iter_content(chunk_size=8192):
                    if cancelled and cancelled.is_set():
                        raise GoogleError(
                            'Google 推理已取消', 499, 'cancelled'
                        )
                    if time.monotonic() > deadline:
                        raise GoogleError(
                            'Google 推理超过等待期限', 504, 'google_timeout'
                        )
                    for delta in decoder.feed(chunk):
                        if delta:
                            yield ('delta', delta)
                result = decoder.finish()
                yield ('done', result)
        except requests.RequestException as e:
            kind = type(e).__name__
            elapsed = time.monotonic() - started
            received = decoder.total if decoder else 0
            logger.warning(
                'Google LLM stream failed: %s phase=%s elapsed=%.1fs sent=%d bytes=%d '
                'mode=%s account=%s model=%s request=%s',
                kind, phase, elapsed, size, received, decoder.mode if decoder else None,
                account.get('id'), model, payload['requestId'],
            )
            raise GoogleError(
                f'Google LLM 连接中断或超时（{kind}，{phase}，{elapsed:.0f}s，已收 {received} 字节）',
                502,
                'google_network_error' if received == 0 else 'google_execution_unknown',
            ) from None

    def generate_text(self, account, model, request, cancelled=None):
        result = None
        for event_type, value in self.stream_text(account, model, request, cancelled=cancelled):
            if event_type == 'done':
                result = value
        if result is None:
            raise GoogleError('Google 模型未返回有效文本', 502, 'google_empty_text')
        return result
