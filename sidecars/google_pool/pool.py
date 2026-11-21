"""Google-only account leases, token refresh and per-model availability."""

from __future__ import annotations
import re
import threading
import time
from .errors import GoogleError
from .quota_groups import has_usable_quota_groups, normalize_quota_summary, sanitize_quota_groups
from .upstream import quota_request_payload, valid_cloud_code_project_id
from .wire import (
    is_image_model,
    is_text_model,
    normalize_model,
    normalize_text_model,
    prepare_request,
    prepare_text_request,
)



MAX_IMAGE_ACCOUNT_ATTEMPTS = 3
_SAFE_REASON = re.compile(r'[A-Z][A-Z0-9._-]{0,63}')
POLICY_REASONS = frozenset(
    {
        'TOS_VIOLATION',
        'TERMS_OF_SERVICE',
        'USER_TOS_VIOLATION',
        'ACCOUNT_SUSPENDED',
        'SERVICE_DISABLED',
    }
)
SAFE_SWITCH_CODES = frozenset(
    {
        'google_quota_exhausted',
        'google_model_unavailable',
        'google_auth_expired',
        'google_project_unavailable',
    }
)


def _error_reasons(error):
    values = []
    for item in getattr(error, 'reasons', ()) or ():
        if isinstance(item, str):
            values.append(item)
    for item in _SAFE_REASON.findall(str(error)):
        values.append(item)
    return tuple(dict.fromkeys(values))


def is_policy_restriction(error):
    return any(reason in POLICY_REASONS or 'TOS' in reason for reason in _error_reasons(error))


def can_retry_other_account(error, *, submitted):
    if not isinstance(error, GoogleError):
        return False
    if error.code in ('cancelled', 'google_pool_disabled'):
        return False
    if is_policy_restriction(error):
        return False
    if error.status == 403 and error.code not in SAFE_SWITCH_CODES:
        return False
    if not submitted:
        return True
    # After the generate POST is issued, only a complete HTTP status rejection
    # from that endpoint — before SSE starts and before any output — can switch.
    # Nested error.status / mid-stream 429 or 401 is not proof that nothing billed.
    if not getattr(error, 'http_status_rejection', False):
        return False
    if error.status == 429 and error.code == 'google_quota_exhausted':
        return True
    if error.status == 401 and error.code == 'google_auth_expired':
        return True
    return False


class GooglePool:
    def __init__(self, store, upstream):
        self.store, self.upstream = store, upstream
        self.lock = threading.RLock()
        self.account_locks = {}
        self.inflight = set()
        self.cooldowns = {}
        self._rr_after_id = None

    def account_lock(self, account_id):
        with self.lock:
            return self.account_locks.setdefault(account_id, threading.RLock())

    def ensure_token(self, account_id, force=False):
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
            return a

    def credentials(self, account_id, force=False):
        with self.account_lock(account_id):
            a = self.ensure_token(account_id, force)
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
            a = self.ensure_token(account_id, force)
            info = self.upstream.metadata(
                a['access_token'],
                'fetchAvailableModels',
                quota_request_payload(a.get('project_id')),
                is_gcp_tos=a.get('is_gcp_tos'),
            )
            models = []
            raw = info.get('models')
            if not isinstance(raw, dict):
                raise GoogleError('Google 模型目录格式无效')
            for name, value in raw.items():
                if not isinstance(value, dict) or not (
                    is_image_model(name) or is_text_model(name)
                ):
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
            a = self._refresh_quota_groups(account_id, a)
            return self.store.public(a)


    def _refresh_quota_groups(self, account_id, account):
        # Best-effort grouped buckets. Failures must not undo a successful catalog
        # refresh, invent 0% bars, or change account eligibility.
        now = int(time.time())
        previous = sanitize_quota_groups(account.get('quota_groups'))
        had_cache = has_usable_quota_groups(previous)

        def keep(status):
            return self.store.patch(
                account_id,
                {
                    'quota_groups_status': status,
                    'quota_groups_last_attempt_at': now,
                },
            )

        try:
            raw = self.upstream.quota_summary(
                account.get('access_token'),
                valid_cloud_code_project_id(account.get('project_id')),
                is_gcp_tos=account.get('is_gcp_tos'),
            )
            normalized = normalize_quota_summary(raw)
            if normalized is None:
                raise GoogleError('Google 分组额度格式无效', 502, 'google_upstream_error')
            groups = normalized['groups']
            if not has_usable_quota_groups(groups):
                if had_cache:
                    return keep('stale_empty')
                return self.store.patch(
                    account_id,
                    {
                        'quota_groups': [],
                        'quota_groups_updated_at': now,
                        'quota_groups_last_attempt_at': now,
                        'quota_groups_status': 'empty',
                    },
                )
            return self.store.patch(
                account_id,
                {
                    'quota_groups': groups,
                    'quota_groups_updated_at': now,
                    'quota_groups_last_attempt_at': now,
                    'quota_groups_status': 'ok',
                },
            )
        except (GoogleError, TypeError, ValueError):
            return keep('stale' if had_cache else 'error')

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

    @staticmethod
    def resolve_text_model(model, account):
        models = {
            m['name']: m
            for m in account.get('models', [])
            if isinstance(m, dict) and m.get('name')
        }
        if model in models and models[model].get('percentage') != 0:
            return model
        raise GoogleError(
            f'此账号没有可用的 {model} 模型额度',
            429,
            'google_model_unavailable',
        )

    def _candidate_accounts(self, model):
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
            return candidates

    def stream_text(self, model, body, cancelled=None):
        if not self.store.enabled():
            raise GoogleError('Google OAuth 账号池未启用', 503, 'google_pool_disabled')
        model = normalize_text_model(model)
        request = prepare_text_request(body)
        candidates = self._candidate_accounts(model)
        last = None
        for candidate in candidates:
            account_id = candidate['id']
            with self.lock:
                if account_id in self.inflight:
                    continue
                self.inflight.add(account_id)
            yielded = False
            try:
                if cancelled and cancelled.is_set():
                    raise GoogleError('推理已取消', 499, 'cancelled')
                a = self.credentials(account_id)
                has_text_catalog = any(
                    is_text_model(m.get('name'))
                    for m in (a.get('models') or [])
                    if isinstance(m, dict)
                )
                if (
                    not a.get('models_checked_at')
                    or time.time() - a['models_checked_at'] > 300
                    or not has_text_catalog
                ):
                    self.refresh(account_id)
                    a = self.store.get(account_id)
                resolved = self.resolve_text_model(model, a)
                if cancelled and cancelled.is_set():
                    raise GoogleError('推理已取消', 499, 'cancelled')
                if not self.store.enabled() or not self.store.get(account_id).get(
                    'enabled'
                ):
                    raise GoogleError(
                        'Google 账号池或账号已禁用', 503, 'google_pool_disabled'
                    )
                for event_type, value in self.upstream.stream_text(
                    a, resolved, request, cancelled=cancelled
                ):
                    if event_type == 'delta':
                        yielded = True
                        yield ('delta', value)
                    elif event_type == 'done':
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
                            pass
                        value['google_pool'] = {
                            'requested_model': model,
                            'resolved_model': resolved,
                            'account_id': account_id,
                        }
                        yield ('done', value)
                        return
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
                if yielded or e.code in ('cancelled', 'google_pool_disabled'):
                    raise
            finally:
                with self.lock:
                    self.inflight.discard(account_id)
        raise last or GoogleError(
            '没有空闲的 Google 账号，请添加授权或等待当前任务结束',
            429,
            'google_pool_unavailable',
        )

    def generate_text(self, model, body, cancelled=None):
        result = None
        for event_type, value in self.stream_text(model, body, cancelled=cancelled):
            if event_type == 'done':
                result = value
        if result is None:
            raise GoogleError('Google 模型未返回有效文本', 502, 'google_empty_text')
        return result

    def _acquire_image_account(self, model, tried):
        with self.lock:
            eligible = [
                a
                for a in self.store.private_accounts()
                if a.get('enabled')
                and not a.get('requires_relogin')
                and a['id'] not in self.inflight
                and a['id'] not in tried
                and self.cooldowns.get((a['id'], model), 0) <= time.monotonic()
            ]
            eligible.sort(key=lambda a: a['id'])
            if not eligible:
                return None
            chosen = eligible[0]
            cursor = self._rr_after_id
            if cursor:
                for account in eligible:
                    if account['id'] > cursor:
                        chosen = account
                        break
            self.inflight.add(chosen['id'])
            self._rr_after_id = chosen['id']
            return chosen

    def _record_image_failure(self, account_id, error, model):
        try:
            account = self.store.get(account_id)
            self.store.patch(
                account_id,
                {
                    'last_error': str(error),
                    'failure_count': account.get('failure_count', 0) + 1,
                    'requires_relogin': error.code == 'google_auth_expired',
                },
            )
        except GoogleError:
            pass
        if error.status == 429:
            with self.lock:
                self.cooldowns[(account_id, model)] = time.monotonic() + 60

    @staticmethod
    def _annotate_image_error(error, account_id, attempt):
        error.account_id = account_id
        error.attempt = attempt
        return error

    def generate(self, model, body, cancelled=None):
        if is_text_model(model):
            return self.generate_text(model, body, cancelled=cancelled)
        if not self.store.enabled():
            raise GoogleError('Google OAuth 账号池未启用', 503, 'google_pool_disabled')
        model = normalize_model(model)
        request = prepare_request(body)
        last = None
        tried = set()
        attempts = 0
        while attempts < MAX_IMAGE_ACCOUNT_ATTEMPTS:
            candidate = self._acquire_image_account(model, tried)
            if candidate is None:
                break
            account_id = candidate['id']
            tried.add(account_id)
            attempts += 1
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
                    'attempt': attempts,
                }
                return result
            except GoogleError as e:
                last = self._annotate_image_error(e, account_id, attempts)
                self._record_image_failure(account_id, e, model)
                # Policy limits and uncertain post-submit results stop immediately.
                if not can_retry_other_account(e, submitted=submitted):
                    raise last
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
