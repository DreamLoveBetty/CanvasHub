"""Web lifecycle and management; explicit imports only, no startup networking."""
import asyncio
import time
from .config import load_settings
from .errors import WebError
from .pool import WebPool
from .store import WebStore


class WebRuntime:
    def __init__(self, settings=None, store=None, upstream=None):
        self.settings = settings or load_settings()
        self.store = store or WebStore(self.settings.db_path)
        if upstream is None:
            from .upstream import GeminiWebUpstream
            upstream = GeminiWebUpstream(self.settings, self.store.persist_cookies)
        self.upstream = upstream
        self.pool = WebPool(self.store, upstream, self.settings)

    async def start(self):
        pass  # Clients are created lazily on explicit check/generation, on this loop.

    async def close(self):
        await self.upstream.close()

    def status(self):
        from .browser import available
        items = self.store.list_public()
        now = time.time()
        for account in items:
            account['state'] = ('disabled' if not account['enabled'] else 'busy' if account['id'] in self.pool.inflight
                else 'requires_relogin' if account['requires_relogin'] else 'cooldown' if account['cooldown_until'] > now
                else 'available' if account['checked_at'] else 'unchecked')
        return {'ok': True, 'enabled': self.store.enabled(), 'items': items,
                'stats': {'total': len(items), 'inflight': len(self.pool.inflight),
                          'available': sum(a['state'] == 'available' for a in items)},
                'capabilities': {'browser_import': available(), 'backend_available': getattr(self.upstream, 'available', True),
                                 'model': 'gemini-3-pro-image', 'resolution': 'auto'}}

    async def action(self, action, body):
        if action == 'config':
            self.store.set_enabled(body.get('enabled'))
        elif action == 'browser-profiles':
            from .browser import profiles
            return {'ok': True, 'items': profiles()}
        elif action in ('accounts-import', 'browser-import', 'account-expand'):
            if self.pool.inflight or self.pool.maintenance:
                raise WebError('Web 任务运行中，请稍后导入 Cookie', 409, 'account_busy')
            self.pool.maintenance = True
            try:
                source_credential_id = None
                if action == 'browser-import':
                    from .browser import import_profile
                    item = await asyncio.to_thread(import_profile, body.get('profile'))
                    items = await self.upstream.discover_accounts(item)
                elif action == 'account-expand':
                    item = self.store.get(str(body.get('account_id') or ''))
                    source_credential_id = item['credential_id']
                    items = await self.upstream.discover_accounts(item)
                else:
                    items = body.get('accounts')
                imported = self.store.import_accounts(items, source_credential_id=source_credential_id)
                affected = {self.store.get(item['id'])['credential_id'] for item in imported}
                for account in self.store.private_accounts():
                    if account['credential_id'] in affected:
                        await self.upstream.drop(account['id'])
            finally:
                self.pool.maintenance = False
            return dict(self.status(), imported=len(imported))
        elif action in ('account-check', 'account-update', 'account-delete'):
            if self.pool.maintenance:
                raise WebError('账号正在更新，请稍后重试', 409, 'account_busy')
            account_id = str(body.get('account_id') or '')
            self.store.get(account_id)
            if action == 'account-check':
                await self.pool.check(account_id)
            elif action == 'account-update':
                if not isinstance(body.get('enabled'), bool):
                    raise WebError('enabled 必须为布尔值', 400, 'invalid_account')
                self.store.patch(account_id, {'enabled': body['enabled']})
            else:
                if account_id in self.pool.inflight:
                    raise WebError('账号正在使用，暂不能删除', 409, 'account_busy')
                self.pool.inflight.add(account_id)
                try:
                    await self.upstream.drop(account_id)
                    self.store.delete(account_id)
                finally:
                    self.pool.inflight.discard(account_id)
        else:
            raise WebError('未知 Web 账号操作', 404, 'not_found')
        return self.status()
