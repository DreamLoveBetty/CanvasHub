"""Google-only FastAPI router; auth and host lifespan are explicit dependencies."""

from __future__ import annotations
import asyncio
import json
import threading
from contextlib import asynccontextmanager
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from .config import load_settings
from .store import GoogleStore
from .upstream import GoogleUpstream
from .pool import GooglePool
from .oauth import GoogleOAuth
from .errors import GoogleError

MAX_REQUEST_BYTES = 70 * 1024 * 1024


class GoogleRuntime:
    def __init__(self, settings=None, store=None, upstream=None):
        self.settings = settings or load_settings()
        self.store = store or GoogleStore(self.settings.db_path)
        self.upstream = upstream or GoogleUpstream(self.settings)
        self.pool = GooglePool(self.store, self.upstream)
        self.oauth = GoogleOAuth(self.settings, self.store, self.upstream)
        self.stop = threading.Event()
        self.worker = None

    def start(self):
        if self.worker and self.worker.is_alive():
            return

        def watch():
            while not self.stop.wait(60):
                if not self.store.enabled():
                    continue
                for account in self.store.private_accounts():
                    if self.stop.is_set():
                        return
                    if (
                        account.get('enabled')
                        and account.get('refresh_token')
                        and not account.get('requires_relogin')
                    ):
                        try:
                            self.pool.credentials(account['id'])
                        except GoogleError:
                            pass

        self.stop.clear()
        self.worker = threading.Thread(
            target=watch, name='google-pool-refresh', daemon=True
        )
        self.worker.start()

    def close(self):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=2)

    def status(self):
        return {
            'ok': True,
            'enabled': self.store.enabled(),
            'stats': self.pool.stats(),
            'items': self.store.list_public(),
            'oauth_configured': bool(
                self.settings.client_id and self.settings.client_secret
            ),
        }

    def action(self, name, body):
        if name == 'config':
            self.store.set_enabled(body.get('enabled'))
            return self.status()
        if name == 'oauth-start':
            return dict(ok=True, **self.oauth.start())
        if name == 'oauth-finish':
            return self.oauth.finish(
                body.get('callback', ''), body.get('session_id', '')
            )
        if name == 'accounts-import':
            accounts = body.get('accounts')
            if not isinstance(accounts, list) or not 1 <= len(accounts) <= 50:
                raise GoogleError('需要 1–50 个账号 JSON', 400, 'invalid_account')
            items = self.store.import_accounts(accounts)
            return dict(self.status(), imported=len(items))
        account_id = str(body.get('account_id') or '')
        if not account_id:
            raise GoogleError('缺少 account_id', 400, 'invalid_account')
        if name == 'account-refresh':
            self.pool.refresh(
                account_id, force=bool(self.store.get(account_id).get('refresh_token'))
            )
        elif name == 'account-update':
            if not isinstance(body.get('enabled'), bool):
                raise GoogleError('enabled必须为布尔值', 400, 'invalid_account')
            self.store.patch(account_id, {'enabled': body['enabled']})
        elif name == 'account-delete':
            self.store.delete(account_id)
        else:
            raise GoogleError('未知 Google 账号池操作', 404, 'not_found')
        return self.status()


async def read_body(request, maximum=MAX_REQUEST_BYTES):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > maximum:
            raise GoogleError('请求内容过大', 413, 'request_too_large')
    try:
        value = json.loads(raw or b'{}')
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeDecodeError):
        raise GoogleError('请求必须为JSON对象', 400, 'invalid_json') from None


def create_router(runtime, require_auth):
    router = APIRouter()

    @router.get('/api/google-pool/status')
    def status(authorization: str | None = Header(default=None)):
        require_auth(authorization)
        return runtime.status()

    @router.post('/api/google-pool/{action}')
    async def control(
        action: str, request: Request, authorization: str | None = Header(default=None)
    ):
        require_auth(authorization)
        try:
            body = await read_body(request, 2 * 1024 * 1024)
            return await run_in_threadpool(runtime.action, action, body)
        except GoogleError as e:
            return JSONResponse(e.public(), status_code=e.status)

    @router.get('/oauth-callback')
    async def callback(request: Request):
        # Public only for Google redirect. OAuth service checks one-use state and exact URI.
        try:
            url = runtime.settings.redirect_uri + '?' + request.url.query
            await run_in_threadpool(runtime.oauth.finish, url)
            return HTMLResponse(
                '<meta charset="utf-8"><h2>Google 授权已保存</h2><p>返回画布设置中心，点击读取账号。</p>',
                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'},
            )
        except GoogleError as e:
            return HTMLResponse(
                '<meta charset="utf-8"><h2>授权未完成</h2><p>请回到画布重新发起授权。</p>',
                status_code=e.status,
                headers={'Cache-Control': 'no-store'},
            )

    @router.get('/v1beta/models')
    def models(authorization: str | None = Header(default=None)):
        require_auth(authorization)
        names = sorted(
            {
                m['name']
                for a in runtime.store.list_public()
                if a['enabled']
                for m in a.get('models', [])
            }
        )
        return {
            'models': [
                {
                    'name': 'models/' + m,
                    'supportedGenerationMethods': [
                        'generateContent',
                        'streamGenerateContent',
                    ],
                }
                for m in names
            ]
        }

    @router.post('/v1beta/models/{operation}')
    async def generate(
        operation: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        require_auth(authorization)
        try:
            model, sep, method = operation.rpartition(':')
            if not sep or method not in ('generateContent', 'streamGenerateContent'):
                raise GoogleError('不支持此Gemini方法', 400, 'invalid_method')
            body = await read_body(request)
            if method == 'generateContent':
                return await run_in_threadpool(runtime.pool.generate, model, body)
            # Validate before committing the SSE headers; generation runs once in a worker.
            from .wire import normalize_model, prepare_request

            normalize_model(model)
            prepare_request(body)
            if not runtime.store.enabled():
                raise GoogleError(
                    'Google OAuth账号池未启用', 503, 'google_pool_disabled'
                )

            async def events():
                cancelled = threading.Event()
                task = asyncio.create_task(
                    run_in_threadpool(runtime.pool.generate, model, body, cancelled)
                )
                try:
                    while not task.done():
                        if await request.is_disconnected():
                            return
                        done, _ = await asyncio.wait({task}, timeout=5)
                        if not done:
                            yield ': google-pool heartbeat\n\n'
                    try:
                        result = task.result()
                    except GoogleError as e:
                        result = e.public()
                    except Exception:
                        result = {
                            'error': 'Google账号池内部错误',
                            'error_code': 'google_pool_error',
                        }
                    yield 'data: ' + json.dumps(result, ensure_ascii=False) + '\n\n'
                finally:
                    cancelled.set()
                    # Consume detached thread errors after a downstream disconnect.
                    if not task.done():
                        task.add_done_callback(
                            lambda t: t.exception() if not t.cancelled() else None
                        )

            return StreamingResponse(
                events(),
                media_type='text/event-stream',
                headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
            )
        except GoogleError as e:
            return JSONResponse(e.public(), status_code=e.status)

    return router
