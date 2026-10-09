"""Google-only account leases, token refresh and per-model availability."""

from __future__ import annotations
import threading
import time
from .errors import GoogleError
from .wire import normalize_model, prepare_request


class GooglePool:
    def __init__(self, store, upstream):
        self.store, self.upstream = store, upstream
        self.lock = threading.RLock()
        self.account_locks = {}
        self.inflight = set()
        self.cooldowns = {}

    def account_lock(self, account_id):
        with self.lock:
            return self.account_locks.setdefault(account_id, threading.RLock())

    def credentials(self, account_id, force=False):
        with self.account_lock(account_id):
            a = self.store.get(account_id)
            if not a.get('enabled'):
                raise GoogleError('Google 账号已禁用', 409, 'account_disabled')
            if (
                force
                or not a.get('access_token')
                or int(a.get('expires_at') or 0) <= time.time() + 300
            ):
                if not a.get('refresh_token'):
                    raise GoogleError(
                        '此账号不可刷新，请重新导入或登录', 401, 'google_auth_expired'
                    )
                try:
                    token = self.upstream.token(
                        {
                            'refresh_token': a['refresh_token'],
                            'grant_type': 'refresh_token',
                        }
                    )
                except GoogleError as e:
                    self.store.patch(
                        account_id,
                        {
                            'last_error': str(e),
                            'requires_relogin': e.code == 'google_auth_expired',
                        },
                    )
                    raise
                a = self.store.patch(
                    account_id,
                    {
                        'access_token': token['access_token'],
                        'refresh_token': token.get('refresh_token')
                        or a['refresh_token'],
                        'expires_at': int(time.time())
                        + int(token.get('expires_in') or 3600),
                        'requires_relogin': False,
                        'last_error': '',
                    },
                )
            if not a.get('project_id'):
                info = self.upstream.metadata(
                    a['access_token'],
                    'loadCodeAssist',
                    {'metadata': {'ideType': 'ANTIGRAVITY'}},
                )
                project = info.get('cloudaicompanionProject')
                if isinstance(project, dict):
                    project = project.get('id')
                if not isinstance(project, str) or not project.strip():
                    raise GoogleError(
                        '账号尚未开通 Antigravity，无法取得 project_id',
                        403,
                        'google_project_unavailable',
                    )
                a = self.store.patch(account_id, {'project_id': project})
            return a

    def refresh(self, account_id, force=False):
        with self.account_lock(account_id):
            a = self.credentials(account_id, force)
            info = self.upstream.metadata(
                a['access_token'], 'fetchAvailableModels', {'project': a['project_id']}
            )
            models = []
            raw = info.get('models')
            if not isinstance(raw, dict):
                raise GoogleError('Google 模型目录格式无效')
            for name, value in raw.items():
                if not isinstance(value, dict) or '-image' not in name:
                    continue
                quota = (
                    value.get('quotaInfo')
                    if isinstance(value.get('quotaInfo'), dict)
                    else {}
                )
                fraction = quota.get('remainingFraction')
                try:
                    percentage = (
                        None
                        if fraction is None
                        else max(0, min(100, round(float(fraction) * 100)))
                    )
                except (ValueError, TypeError, OverflowError):
                    percentage = None
                models.append(
                    {
                        'name': name,
                        'percentage': percentage,
                        'reset_time': str(quota.get('resetTime') or '')[:80],
                    }
                )
            a = self.store.patch(
                account_id,
                {
                    'models': models,
                    'models_checked_at': int(time.time()),
                    'last_error': '',
                },
            )
            return self.store.public(a)

    @staticmethod
    def resolve_model(model, account):
        family = (
            ('gemini-3-pro-image', 'gemini-3.1-pro-image')
            if '-pro-image' in model
            else ('gemini-3-flash-image', 'gemini-3.1-flash-image')
        )
        models = {m['name']: m for m in account.get('models', [])}
        for name in dict.fromkeys([model, *family]):
            if name in models and models[name].get('percentage') != 0:
                return name
        raise GoogleError(
            '此账号没有所请求档位的可用图像模型；不会自动 Pro 降 Flash',
            429,
            'google_model_unavailable',
        )

    def generate(self, model, body, cancelled=None):
        if not self.store.enabled():
            raise GoogleError('Google OAuth 账号池未启用', 503, 'google_pool_disabled')
        model = normalize_model(model)
        request = prepare_request(body)
        with self.lock:
            candidates = [
                a
                for a in self.store.private_accounts()
                if a.get('enabled')
                and not a.get('requires_relogin')
                and a['id'] not in self.inflight
                and self.cooldowns.get((a['id'], model), 0) <= time.monotonic()
            ]
            candidates.sort(key=lambda a: a.get('last_used_at') or 0)
        last = None
        for candidate in candidates:
            account_id = candidate['id']
            with self.lock:
                if account_id in self.inflight:
                    continue
                self.inflight.add(account_id)
            submitted = False
            try:
                if cancelled and cancelled.is_set():
                    raise GoogleError('生成已取消', 499, 'cancelled')
                a = self.credentials(account_id)
                if (
                    not a.get('models_checked_at')
                    or time.time() - a['models_checked_at'] > 300
                ):
                    self.refresh(account_id)
                    a = self.store.get(account_id)
                resolved = self.resolve_model(model, a)
                if cancelled and cancelled.is_set():
                    raise GoogleError('生成已取消', 499, 'cancelled')
                if not self.store.enabled() or not self.store.get(account_id).get(
                    'enabled'
                ):
                    raise GoogleError(
                        'Google 账号池或账号已禁用', 503, 'google_pool_disabled'
                    )
                submitted = True
                result = self.upstream.generate(a, resolved, request, cancelled)
                try:
                    self.store.patch(
                        account_id,
                        {
                            'last_used_at': int(time.time()),
                            'last_error': '',
                            'success_count': a.get('success_count', 0) + 1,
                        },
                    )
                except GoogleError:
                    pass  # Deletion must not discard an already generated image.
                result['google_pool'] = {
                    'requested_model': model,
                    'resolved_model': resolved,
                    'account_id': account_id,
                }
                return result
            except GoogleError as e:
                last = e
                try:
                    a = self.store.get(account_id)
                    self.store.patch(
                        account_id,
                        {
                            'last_error': str(e),
                            'failure_count': a.get('failure_count', 0) + 1,
                            'requires_relogin': e.code == 'google_auth_expired',
                        },
                    )
                except GoogleError:
                    pass
                if e.status == 429:
                    with self.lock:
                        self.cooldowns[(account_id, model)] = time.monotonic() + 60
                # Only preflight can try another account. Never resubmit a generation POST.
                if submitted or e.code in ('cancelled', 'google_pool_disabled'):
                    raise
            finally:
                with self.lock:
                    self.inflight.discard(account_id)
        raise last or GoogleError(
            '没有空闲的 Google 账号，请添加授权或等待当前任务结束',
            429,
            'google_pool_unavailable',
        )

    def stats(self):
        accounts = self.store.list_public()
        with self.lock:
            return {
                'total': len(accounts),
                'enabled': sum(a['enabled'] is True for a in accounts),
                'inflight': len(self.inflight),
            }
