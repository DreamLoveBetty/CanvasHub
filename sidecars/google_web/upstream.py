"""Lazy Gemini Web adapter. Async clients and Cookie rotation stay on one loop."""
import asyncio
import base64
import importlib.util
import io
import time
from .errors import WebError
from .accounts import require_identity, discover_accounts
from .images import download_generated_image
from .download_diagnostics import DownloadDiagnostics


class GeminiWebUpstream:
    def __init__(self, settings, persist_cookies):
        self.settings, self.persist_cookies = settings, persist_cookies
        self.sessions = {}
        self.refresh_worker = None
        self.refreshed_at = {}
        self.download_diagnostics = DownloadDiagnostics(settings.db_path.parent / 'download_diagnostics')

    async def discover_accounts(self, item):
        return await discover_accounts(item, self.settings)

    @property
    def available(self):
        return all(importlib.util.find_spec(name) is not None for name in ('curl_cffi', 'orjson', 'pydantic'))

    def flush(self, account_id, client):
        entry = self.sessions.get(account_id)
        if not entry or entry['client'] is not client:
            return
        cookies = {cookie.name: cookie.value for cookie in client.cookies.jar
                   if str(cookie.domain or '').lstrip('.').endswith('google.com') and not cookie.is_expired()}
        snapshot = entry.get('cookie_snapshot', {})
        changes = {key: value for key, value in cookies.items() if snapshot.get(key) != value}
        canonical = self.persist_cookies(account_id, changes, entry['revision']) if changes else None
        if canonical:
            group = entry.get('credential_id') or account_id
            for other_id, other in self.sessions.items():
                if (other.get('credential_id') or other_id) == group:
                    other['client'].cookies = canonical
                    other['cookie_snapshot'] = dict(canonical)
        else:
            entry['cookie_snapshot'] = cookies

    async def _persist_refreshed(self):
        from .vendor.gemini_webapi.utils.rotate_1psidts import rotate_1psidts
        while True:
            await asyncio.sleep(60)
            groups = set()
            for account_id, entry in list(self.sessions.items()):
                group = entry.get('credential_id') or account_id
                client = entry['client']
                if group in groups or not client._running or not client.client:
                    continue
                groups.add(group)
                if time.monotonic() - self.refreshed_at.get(group, 0) >= 600:
                    try:
                        await rotate_1psidts(client.client)
                    except Exception:
                        pass  # Existing preflight/generation reports sanitized auth failures.
                    self.refreshed_at[group] = time.monotonic()
                self.flush(account_id, client)

    async def prepare(self, account):
        if not self.available:
            raise WebError('Gemini Web 依赖未安装，请安装 sidecars/google_web/requirements.txt 后重启账号服务',
                           503, 'web_dependencies_missing')
        from .vendor.gemini_webapi import GeminiClient
        from .vendor.gemini_webapi.exceptions import AuthError
        account_id = account['id']
        entry = self.sessions.get(account_id)
        # Pinned logical accounts revalidate before every task, before upload/POST.
        if entry and not account.get('expected_email') and entry['revision'] == account['revision'] and entry['client']._running:
            return dict(entry.get('identity', {}))
        await self.drop(account_id)
        cookies = dict(account['cookies'])
        identity = {}
        client = GeminiClient(secure_1psid=cookies.pop('__Secure-1PSID'),
                              secure_1psidts=cookies.pop('__Secure-1PSIDTS', ''),
                              proxy=self.settings.proxy_url or None, verify=True,
                              authuser=account.get('authuser', 0),
                              on_bootstrap=lambda html: identity.update(require_identity(html, account.get('authuser', 0), account.get('expected_email') or '')))
        client.cookies = cookies
        try:
            await client.init(timeout=self.settings.timeout, auto_refresh=False, refresh_interval=600,
                              watchdog_timeout=120, verbose=False)
        except AuthError:
            await client.close()
            raise WebError('Web 登录态已失效，请重新导入 Cookie', 401, 'web_auth_expired') from None
        except WebError:
            await client.close()
            raise
        except BaseException as error:
            await client.close()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise WebError('无法连接 Gemini 网页检查登录态，请检查服务端网络或代理', 502, 'web_preflight_failed') from None
        group = account.get('credential_id') or account_id
        self.refreshed_at.setdefault(group, time.monotonic())
        self.sessions[account_id] = {'client': client, 'revision': account['revision'], 'identity': identity,
                                     'credential_id': group, 'cookie_snapshot': dict(account['cookies'])}
        self.flush(account_id, client)
        if self.refresh_worker is None or self.refresh_worker.done():
            self.refresh_worker = asyncio.create_task(self._persist_refreshed())
        return dict(identity)

    async def generate(self, account_id, request, cancelled=None):
        from .vendor.gemini_webapi.exceptions import AuthError, UsageLimitExceeded, TemporarilyBlocked
        from .vendor.gemini_webapi.types import GeneratedImage
        client = self.sessions[account_id]['client']
        texts, files = [], []
        parts = [part for content in request['contents'] for part in content['parts']]
        for part in parts:
            if 'text' in part:
                texts.append(part['text'])
            else:
                image = io.BytesIO(base64.b64decode(part['inlineData']['data'], validate=True))
                image.name = 'reference.' + {'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp'}[part['inlineData']['mimeType']]
                files.append(image)
        image_config = request['generationConfig']['imageConfig']
        ratio, size = image_config['aspectRatio'], image_config['imageSize']
        prompt = (f'画幅：{ratio}；分辨率：{size}。\n\n' + '\n\n'.join(texts)
                  + '\n\nGenerate an image. Return the original image.')
        trace = None
        try:
            async with asyncio.timeout(self.settings.timeout):
                output = await client.generate_content(prompt, files=files or None, pro_image=True, temporary=True)
                images = [image for image in output.images if isinstance(image, GeneratedImage)]
                if not images:
                    raise WebError('Gemini Web 未返回图片，未重新提交', 502, 'web_no_image')
                if cancelled and cancelled.is_set():
                    raise WebError('任务已取消，未重新提交', 499, 'cancelled')
                trace = self.download_diagnostics.begin(account_id, images[0], ratio=ratio, size=size,
                    reference_count=len(files), image_count=len(images))
                raw, mime, provenance = await download_generated_image(images[0], client.client, trace=trace)
                return {'candidates': [{'content': {'role': 'model', 'parts': [{'inlineData': {
                    'mimeType': mime, 'data': base64.b64encode(raw).decode('ascii')
                }}]}, 'finishReason': 'STOP'}], 'google_pool': provenance}
        except WebError:
            raise
        except AuthError:
            raise WebError('Web 登录态已失效，未重新提交', 401, 'web_auth_expired') from None
        except (UsageLimitExceeded, TemporarilyBlocked):
            raise WebError('Gemini Web 当前限额，账号已进入冷却；未重新提交', 429, 'web_quota_exhausted') from None
        except Exception:
            raise WebError('Gemini Web 连接中断或返回无效响应；执行状态未知，未重新提交', 502, 'web_execution_unknown') from None
        finally:
            if trace and not trace.finished:
                trace.finish('interrupted')
            for file in files:
                file.close()
            self.flush(account_id, client)

    async def drop(self, account_id):
        entry = self.sessions.pop(account_id, None)
        if entry:
            # Do not flush here: an explicit re-import may have replaced these cookies.
            await entry['client'].close()

    async def close(self):
        if self.refresh_worker:
            self.refresh_worker.cancel()
            try:
                await self.refresh_worker
            except asyncio.CancelledError:
                pass
        for account_id in list(self.sessions):
            self.flush(account_id, self.sessions[account_id]['client'])
            await self.drop(account_id)
