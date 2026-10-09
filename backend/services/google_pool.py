"""Google pool management transport. Host injects service URL/auth configuration.

No dependency on GPT account storage, OAuth or generation modules.
"""

from __future__ import annotations
import requests


class GooglePoolClient:
    def __init__(self, get_transport, session_factory=requests.Session):
        self.get_transport = get_transport
        self.session_factory = session_factory

    def connection(self):
        cfg = self.get_transport()
        base = str(cfg.get('base_url') or 'http://127.0.0.1:18080').rstrip('/')
        key = str(cfg.get('auth_key') or '')
        if not key:
            raise RuntimeError('账号服务认证未配置，请先配置 sidecar')
        return base, {'Authorization': 'Bearer ' + key}

    def request(self, action='status', body=None):
        allowed = {
            'status',
            'config',
            'oauth-start',
            'oauth-finish',
            'accounts-import',
            'account-refresh',
            'account-update',
            'account-delete',
        }
        if action not in allowed:
            raise ValueError('未知 Google 账号池操作')
        base, headers = self.connection()
        try:
            with self.session_factory() as s:
                s.trust_env = False
                with s.request(
                    'GET' if body is None else 'POST',
                    base + '/api/google-pool/' + action,
                    headers=headers,
                    json=body,
                    timeout=(5, 150),
                    allow_redirects=False,
                ) as r:
                    data = r.json()
                    if not 200 <= r.status_code < 300:
                        message = data.get('error') if isinstance(data, dict) else None
                        raise RuntimeError(
                            message or f'Google账号服务返回HTTP {r.status_code}'
                        )
                    if not isinstance(data, dict):
                        raise ValueError()
                    return data
        except requests.RequestException:
            raise RuntimeError(
                'Google账号服务无法连接，请检查组合sidecar是否已启动'
            ) from None
        except ValueError:
            raise RuntimeError('Google账号服务返回无效响应') from None
