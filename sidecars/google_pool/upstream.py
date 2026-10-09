"""Google OAuth / Cloud Code HTTP only; no persistence or account selection.

Single POST per generation: a timeout/disconnect never triggers a blind retry.
"""

from __future__ import annotations
import json
import time
import uuid
import requests
from .errors import GoogleError

TOKEN_URL = 'https://oauth2.googleapis.com/token'
PROFILE_URL = 'https://www.googleapis.com/oauth2/v2/userinfo'


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
            # Do not echo OAuth/upstream error bodies (may contain credentials/prompt).
            raise GoogleError(
                f'{operation}失败（HTTP {response.status_code}）',
                response.status_code if 400 <= response.status_code < 600 else 502,
                code,
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

    def metadata(self, access, method, payload):
        if method not in ('loadCodeAssist', 'fetchAvailableModels'):
            raise ValueError('Unsupported metadata operation')
        try:
            with self.session() as s, s.post(
                self.settings.upstream + ':' + method,
                json=payload,
                headers=self.headers(access),
                timeout=(15, 45),
                allow_redirects=False,
            ) as r:
                return self.checked_json(r, 'Google 模型信息')
        except requests.RequestException:
            raise GoogleError('Google 模型信息网络请求失败') from None

    @staticmethod
    def headers(access):
        return {
            'Authorization': 'Bearer ' + access,
            'User-Agent': 'antigravity',
            'x-client-name': 'antigravity',
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
        deadline = time.monotonic() + self.settings.timeout
        try:
            with self.session() as s, s.post(
                self.settings.upstream + ':streamGenerateContent?alt=sse',
                json=payload,
                headers=self.headers(account['access_token']),
                stream=True,
                timeout=(15, self.settings.timeout),
                allow_redirects=False,
            ) as r:
                if not 200 <= r.status_code < 300:
                    self.checked_json(r, 'Google 图像生成')
                from .wire import ImageResponse

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
        except requests.RequestException:
            raise GoogleError(
                'Google 图像连接中断或超时；上游执行状态未知，未重新提交',
                502,
                'google_execution_unknown',
            ) from None
