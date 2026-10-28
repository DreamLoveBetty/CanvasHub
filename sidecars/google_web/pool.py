"""Async Web account leases and round-robin; never replay submitted generation."""
import asyncio
import time
from ..google_pool.wire import prepare_request, find_image_response
from ..google_pool.errors import GoogleError
from .errors import WebError

WEB_MODEL = 'gemini-3-pro-image'


class WebPool:
    def __init__(self, store, upstream, settings):
        self.store, self.upstream, self.settings = store, upstream, settings
        self.lock = asyncio.Lock()
        self.inflight = set()
        self.cursor = 0
        self.maintenance = False

    async def prepare(self, account):
        identity = await self.upstream.prepare(account) or {}
        self.store.record_identity(account['id'], identity)

    async def check(self, account_id):
        async with self.lock:
            if self.maintenance:
                raise WebError('账号正在更新，请稍后重试', 409, 'account_busy')
            if account_id in self.inflight:
                raise WebError('账号正在使用，请稍后检查', 409, 'account_busy')
            self.store.get(account_id)
            self.inflight.add(account_id)
        try:
            await self.prepare(self.store.get(account_id))
            self.store.patch(account_id, {'last_error': ''})
        except WebError as error:
            self.failure(account_id, error)
            raise
        finally:
            self.inflight.discard(account_id)

    def failure(self, account_id, error):
        try:
            account = self.store.get(account_id)
            self.store.patch(account_id, {
                'last_error': str(error), 'failure_count': account.get('failure_count', 0) + 1,
                'requires_relogin': error.code in ('web_auth_expired', 'web_account_changed'),
                'cooldown_until': time.time() + self.settings.cooldown_seconds if error.status == 429 or error.code == 'web_execution_unknown' else 0,
            })
        except WebError:
            pass

    async def generate(self, model, body, cancelled=None):
        if model.removesuffix('-preview') != WEB_MODEL:
            raise WebError('Gemini Web 仅支持网页 Pro 生图模式', 400, 'invalid_web_model')
        try:
            request = prepare_request(body)
        except GoogleError as error:
            raise WebError(str(error), error.status, error.code) from None
        if not self.store.enabled():
            raise WebError('Gemini Web 账号池未启用', 503, 'web_pool_disabled')
        async with self.lock:
            if self.maintenance:
                raise WebError('账号正在更新，请稍后重试', 409, 'account_busy')
            accounts = self.store.private_accounts()
            if accounts:
                start = self.cursor % len(accounts)
                accounts = accounts[start:] + accounts[:start]
        last = None
        for candidate in accounts:
            account_id = candidate['id']
            async with self.lock:
                if self.maintenance:
                    raise WebError('账号正在更新，请稍后重试', 409, 'account_busy')
                try:
                    account = self.store.get(account_id)
                except WebError:
                    continue  # Deleted between candidate snapshot and lease.
                if (not account['enabled'] or account.get('requires_relogin') or account_id in self.inflight
                        or account.get('cooldown_until', 0) > time.time()):
                    continue
                self.inflight.add(account_id)
                ids = [item['id'] for item in self.store.private_accounts()]
                self.cursor = ids.index(account_id) + 1
            submitted = False
            try:
                if cancelled and cancelled.is_set():
                    raise WebError('任务已取消，未提交', 499, 'cancelled')
                await self.prepare(account)
                if cancelled and cancelled.is_set():
                    raise WebError('任务已取消，未提交', 499, 'cancelled')
                if not self.store.enabled() or not self.store.get(account_id)['enabled']:
                    raise WebError('Web 账号池或账号已关闭', 503, 'web_pool_disabled')
                submitted = True
                raw = await self.upstream.generate(account_id, request, cancelled)
                try:
                    result = find_image_response(raw)
                except GoogleError:
                    result = None
                if result is None:
                    raise WebError('Gemini Web 未返回有效图片，未重新提交', 502, 'web_no_image')
                self.store.patch(account_id, {'last_used_at': time.time(), 'last_error': '',
                    'success_count': account.get('success_count', 0) + 1, 'cooldown_until': 0})
                result['google_pool'] = {'requested_model': model, 'resolved_model': 'gemini-web-pro-image', 'account_id': account_id}
                info = raw.get('google_pool', {})
                if isinstance(info, dict) and info.get('web_image_source') in ('original_rpc', 'preview_fallback'):
                    result['google_pool'].update({'web_image_source': info['web_image_source'],
                        'web_original_verified': info['web_image_source'] == 'original_rpc' and info.get('web_original_verified') is True})
                    if info.get('web_original_error') in ('rpc_missing_context', 'rpc_unavailable', 'download_failed'):
                        result['google_pool']['web_original_error'] = info['web_original_error']
                return result
            except WebError as error:
                last = error
                self.failure(account_id, error)
                if submitted or error.code in ('cancelled', 'web_pool_disabled'):
                    raise
            except Exception:
                error = WebError('Gemini Web 请求失败；执行状态未知，未重新提交' if submitted else 'Web 登录态检查失败',
                                 502, 'web_execution_unknown' if submitted else 'web_preflight_failed')
                self.failure(account_id, error)
                if submitted:
                    raise error from None
                last = error
            finally:
                self.inflight.discard(account_id)
        raise last or WebError('没有可用的 Web 账号，请检查登录态或等待当前任务完成', 429, 'web_pool_unavailable')
