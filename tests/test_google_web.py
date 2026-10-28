"""Offline Google Web contracts; credentials and images are synthetic."""
import asyncio
import base64
import io
import json
import os
import importlib.util
from pathlib import Path
import tempfile
import unittest
import inspect
import time
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image


def picture():
    out = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(out, 'PNG')
    return {'candidates': [{'content': {'parts': [{'inlineData': {
        'mimeType': 'image/png', 'data': base64.b64encode(out.getvalue()).decode()
    }}]}}]}


BODY = {'contents': [{'role': 'user', 'parts': [{'text': 'synthetic red square'}]}],
        'generationConfig': {'imageConfig': {'aspectRatio': '1:1', 'imageSize': '2K'}}}


class GoogleWebBrowserTest(unittest.TestCase):
    def test_profile_directory_denial_requires_host_permission_without_exposing_paths(self):
        from sidecars.google_web.browser import profiles
        from sidecars.google_web.errors import WebError
        for errno in (1, 13):
            with self.subTest(errno=errno), patch('sidecars.google_web.browser.available', return_value=True), \
                    patch.object(Path, 'iterdir', side_effect=PermissionError(errno, 'fixture-private-path')):
                with self.assertRaises(WebError) as caught:
                    profiles()
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(caught.exception.code, 'browser_permission_required')
                self.assertIn('完全磁盘访问权限', str(caught.exception))
                self.assertNotIn('fixture-private-path', str(caught.exception))


class GoogleWebStoreTest(unittest.TestCase):
    def setUp(self):
        from sidecars.google_web.store import WebStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WebStore(Path(self.temp.name) / 'accounts.db')

    def test_cookie_formats_are_normalized_and_never_returned(self):
        values = [
            {'__Secure-1PSID': 'fixture-a', 'irrelevant': 'noise'},
            {'cookies': {'__Secure-1PSID': 'fixture-b'}},
            [{'name': '__Secure-1PSID', 'value': 'fixture-c', 'domain': '.google.com'}],
            {'cookies': [{'name': '__Secure-1PSID', 'value': 'fixture-d'}]},
        ]
        for value in values:
            self.store.import_accounts([{'label': 'Fixture', 'cookies': value}])
        public = json.dumps(self.store.list_public())
        self.assertEqual(len(self.store.list_public()), 4)
        for secret in ['fixture-a', 'fixture-b', 'fixture-c', 'fixture-d', '__Secure-1PSID', 'noise']:
            self.assertNotIn(secret, public)
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

    def test_invalid_batch_import_is_atomic(self):
        from sidecars.google_web.errors import WebError
        with self.assertRaises(WebError):
            self.store.import_accounts([
                {'cookies': {'__Secure-1PSID': 'fixture-a'}},
                {'cookies': {'NID': 'not-auth'}},
            ])
        self.assertEqual(self.store.list_public(), [])

    def test_cookie_rotation_preserves_account_identity_and_redacts_fields(self):
        account = self.store.import_accounts([{'cookies': {'__Secure-1PSID': 'fixture-a'}}])[0]
        self.store.persist_cookies(account['id'], {'__Secure-1PSID': 'fixture-a', '__Secure-1PSIDTS': 'rotated-secret'})
        again = self.store.import_accounts([{'cookies': {'__Secure-1PSID': 'fixture-a'}}])[0]
        self.assertEqual(again['id'], account['id'])
        self.assertNotIn('rotated-secret', json.dumps(self.store.list_public()))


class FakeUpstream:
    def __init__(self):
        self.submitted = []
        self.preflight_errors = set()
        self.fail_generate = False
        self.block = None

    async def prepare(self, account):
        from sidecars.google_web.errors import WebError
        if account['id'] in self.preflight_errors:
            raise WebError('登录已失效', 401, 'web_auth_expired')

    async def generate(self, account_id, request, cancelled=None):
        from sidecars.google_web.errors import WebError
        self.submitted.append(account_id)
        if self.block:
            await self.block.wait()
        if self.fail_generate:
            raise WebError('执行状态未知', 502, 'web_execution_unknown')
        return picture()

    async def drop(self, account_id):
        pass

    async def close(self):
        pass


class GoogleWebPoolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.upstream = FakeUpstream()
        self.runtime = WebRuntime(WebSettings(Path(self.temp.name) / 'accounts.db'), upstream=self.upstream)
        self.store = self.runtime.store
        self.accounts = self.store.import_accounts([
            {'label': 'A', 'cookies': {'__Secure-1PSID': 'fixture-a'}},
            {'label': 'B', 'cookies': {'__Secure-1PSID': 'fixture-b'}},
        ])
        self.store.set_enabled(True)
        self.addAsyncCleanup(self.runtime.close)

    async def test_new_tasks_rotate_across_accounts(self):
        for _ in range(3):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        a, b = [item['id'] for item in self.accounts]
        self.assertEqual(self.upstream.submitted, [a, b, a])
        public = json.dumps(self.runtime.status())
        self.assertNotIn('fixture-a', public)
        self.assertNotIn('fixture-b', public)

    async def test_login_check_persists_public_identity_and_reimport_clears_stale_name(self):
        async def prepare(_):
            return {'display_name': 'Synthetic Name', 'email': 'active@example.test', 'token': 'never-public'}
        self.upstream.prepare = prepare
        account_id = self.accounts[0]['id']
        result = await self.runtime.action('account-check', {'account_id': account_id})
        public = next(item for item in result['items'] if item['id'] == account_id)
        self.assertEqual(public.get('display_name'), 'Synthetic Name')
        self.assertEqual(public.get('email'), 'active@example.test')
        self.assertNotIn('never-public', json.dumps(result))
        imported = self.store.import_accounts([{'cookies': {'__Secure-1PSID': 'fixture-a'}}])[0]
        self.assertFalse(imported.get('display_name'))
        self.assertFalse(imported.get('email'))

    async def test_generation_keeps_safe_download_provenance_and_discards_signed_urls(self):
        async def generate(*_):
            return dict(picture(), google_pool={'web_image_source': 'preview_fallback',
                'web_original_verified': False, 'web_original_error': 'rpc_unavailable',
                'signed_url': 'https://fixture-secret.test/signed', 'cookies': 'fixture-secret'})
        self.upstream.generate = generate
        result = await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.assertEqual(result['google_pool'].get('web_image_source'), 'preview_fallback')
        self.assertIs(result['google_pool'].get('web_original_verified'), False)
        self.assertEqual(result['google_pool'].get('web_original_error'), 'rpc_unavailable')
        self.assertNotIn('fixture-secret', json.dumps(result))

    async def test_preflight_can_failover_without_replaying_generation(self):
        a, b = [item['id'] for item in self.accounts]
        self.upstream.preflight_errors.add(a)
        result = await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.assertEqual(self.upstream.submitted, [b])
        self.assertEqual(result['google_pool']['account_id'], b)
        self.assertTrue(self.store.get(a)['requires_relogin'])

    async def test_submitted_failure_never_tries_another_account(self):
        from sidecars.google_web.errors import WebError
        self.upstream.fail_generate = True
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.assertEqual(len(self.upstream.submitted), 1)
        self.assertEqual(self.runtime.pool.inflight, set())

    async def test_concurrent_requests_lease_distinct_accounts(self):
        from sidecars.google_web.errors import WebError
        self.upstream.block = asyncio.Event()
        one = asyncio.create_task(self.runtime.pool.generate('gemini-3-pro-image', BODY))
        two = asyncio.create_task(self.runtime.pool.generate('gemini-3-pro-image', BODY))
        for _ in range(10):
            if len(self.upstream.submitted) == 2:
                break
            await asyncio.sleep(0)
        self.assertEqual(len(set(self.upstream.submitted)), 2)
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.upstream.block.set()
        await asyncio.gather(one, two)
        self.assertEqual(self.runtime.pool.inflight, set())

    async def test_zero_image_is_a_failure_not_a_success(self):
        from sidecars.google_web.errors import WebError
        async def no_image(*args):
            return {'text': 'no image'}
        self.upstream.generate = no_image
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.assertEqual(sum(a['success_count'] for a in self.store.list_public()), 0)

    async def test_disabled_pool_and_cancelled_request_do_not_submit(self):
        from sidecars.google_web.errors import WebError
        self.store.set_enabled(False)
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY)
        self.store.set_enabled(True)
        cancelled = asyncio.Event(); cancelled.set()
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3-pro-image', BODY, cancelled)
        self.assertEqual(self.upstream.submitted, [])

    async def test_web_does_not_silently_accept_flash(self):
        from sidecars.google_web.errors import WebError
        with self.assertRaises(WebError):
            await self.runtime.pool.generate('gemini-3.1-flash-image', BODY)
        self.assertEqual(self.upstream.submitted, [])

    async def test_import_is_blocked_while_account_is_busy(self):
        from sidecars.google_web.errors import WebError
        self.upstream.block = asyncio.Event()
        task = asyncio.create_task(self.runtime.pool.generate('gemini-3-pro-image', BODY))
        while not self.upstream.submitted:
            await asyncio.sleep(0)
        try:
            with self.assertRaises(WebError):
                await self.runtime.action('accounts-import', {'accounts': [{'cookies': {'__Secure-1PSID': 'new-secret'}}]})
        finally:
            self.upstream.block.set()
            await task

    async def test_cancelled_downstream_keeps_lease_until_upstream_finishes(self):
        cancelled = asyncio.Event()
        self.upstream.block = asyncio.Event()
        task = asyncio.create_task(self.runtime.pool.generate('gemini-3-pro-image', BODY, cancelled))
        while not self.upstream.submitted:
            await asyncio.sleep(0)
        account_id = self.upstream.submitted[0]
        cancelled.set()
        await asyncio.sleep(0)
        self.assertIn(account_id, self.runtime.pool.inflight)
        self.assertEqual(len(self.upstream.submitted), 1)
        self.upstream.block.set()
        await task
        self.assertNotIn(account_id, self.runtime.pool.inflight)


@unittest.skipUnless(importlib.util.find_spec('fastapi') and importlib.util.find_spec('httpx'), 'Requires sidecar FastAPI and httpx')
class GoogleWebApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_browser_directory_denial_returns_actionable_error_not_generic_bad_request(self):
        from fastapi import FastAPI
        import httpx
        from sidecars.google_web.api import create_router
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        with tempfile.TemporaryDirectory() as temp:
            runtime = WebRuntime(WebSettings(Path(temp) / 'accounts.db'), upstream=FakeUpstream())
            app = FastAPI()
            app.include_router(create_router(runtime, lambda _: None))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                with patch('sidecars.google_web.browser.available', return_value=True), \
                        patch.object(Path, 'iterdir', side_effect=PermissionError(1, 'fixture-private-path')):
                    response = await client.post('/api/google-web/browser-profiles', json={})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()['error_code'], 'browser_permission_required')
            self.assertIn('完全磁盘访问权限', response.json()['error'])
            self.assertNotIn('fixture-private-path', response.text)
            self.assertEqual(runtime.store.list_public(), [])
            await runtime.close()

    async def test_browser_action_unexpected_error_is_logged_without_credentials(self):
        from fastapi import FastAPI
        import httpx
        from sidecars.google_web.api import create_router
        runtime = Mock()
        runtime.action = AsyncMock(side_effect=RuntimeError('fixture-secret-cookie'))
        app = FastAPI()
        app.include_router(create_router(runtime, lambda _: None))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
            with self.assertLogs('sidecars.google_web.api', level='WARNING') as logs:
                response = await client.post('/api/google-web/browser-profiles', json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error_code'], 'web_control_error')
        self.assertIn('browser-profiles', '\n'.join(logs.output))
        self.assertIn('RuntimeError', '\n'.join(logs.output))
        self.assertNotIn('fixture-secret-cookie', response.text + '\n'.join(logs.output))

    async def test_auth_native_sse_and_cookie_redaction(self):
        from fastapi import FastAPI, HTTPException
        import httpx
        from sidecars.google_web.api import create_router
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        with tempfile.TemporaryDirectory() as temp:
            runtime = WebRuntime(WebSettings(Path(temp) / 'accounts.db'), upstream=FakeUpstream())
            def auth(value):
                if value != 'Bearer fixture-local-auth':
                    raise HTTPException(401)
            app = FastAPI(); app.include_router(create_router(runtime, auth))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                self.assertEqual((await client.get('/api/google-web/status')).status_code, 401)
                headers = {'Authorization': 'Bearer fixture-local-auth'}
                imported = await client.post('/api/google-web/accounts-import', headers=headers,
                    json={'accounts': [{'label': 'Synthetic', 'cookies': {'__Secure-1PSID': 'fixture-secret'}}]})
                self.assertEqual(imported.status_code, 200)
                self.assertNotIn('fixture-secret', imported.text)
                await client.post('/api/google-web/config', headers=headers, json={'enabled': True})
                result = await client.post('/api/google-web/models/gemini-3-pro-image:streamGenerateContent', headers=headers, json=BODY)
                self.assertEqual(result.status_code, 200)
                self.assertIn('text/event-stream', result.headers['content-type'])
                document = json.loads(result.text.split('data: ', 1)[1].strip())
                self.assertEqual(document['candidates'][0]['content']['parts'][0]['inlineData']['mimeType'], 'image/png')
                self.assertEqual(len(runtime.upstream.submitted), 1)
                self.assertNotIn('fixture-secret', (await client.get('/api/google-web/status', headers=headers)).text)
            await runtime.close()


@unittest.skipUnless(importlib.util.find_spec('curl_cffi') and importlib.util.find_spec('orjson'), 'Requires Web dependencies')
class GoogleWebVendorTest(unittest.IsolatedAsyncioTestCase):
    async def test_web_generation_post_is_not_replayed_on_server_error(self):
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from sidecars.google_web.vendor.gemini_webapi.constants import Model
        from sidecars.google_web.vendor.gemini_webapi.exceptions import APIError
        from curl_cffi.requests import Cookies
        class Response:
            status_code = 500
        class Stream:
            async def __aenter__(self): return Response()
            async def __aexit__(self, *args): pass
        class Session:
            cookies = Cookies()
            calls = 0
            def stream(self, method, url, **kwargs):
                self.calls += 1
                return Stream()
            async def close(self): pass
        session = Session()
        client = GeminiClient(secure_1psid='fixture-not-a-real-cookie')
        client.client = session; client._running = True
        with self.assertRaises(APIError):
            async for _ in client._generate('fixture', model=Model.UNSPECIFIED, pro_image=True):
                pass
        self.assertEqual(session.calls, 1)


class GoogleWebRoutingTest(unittest.TestCase):
    def test_explicit_web_route_never_falls_back_to_gpt(self):
        from backend.services.google_generation import _should_fallback_to_gpt
        self.assertFalse(_should_fallback_to_gpt({'google_provider_route':'google_web', 'caller':'skill'},
            'timeout', _is_retryable_generation_error=lambda _: True))

    def test_web_provider_reads_native_sse_and_keeps_original_bytes(self):
        from backend.provider_google_pool import GooglePoolProvider
        from backend.services.google_pool import GooglePoolClient
        raw = base64.b64decode(picture()['candidates'][0]['content']['parts'][0]['inlineData']['data'])
        calls = []
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def iter_content(self,chunk_size):
                yield b': heartbeat\n\n'
                yield b'data: ' + json.dumps(picture()).encode() + b'\n\n'
        class Session:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def post(self,url,**kwargs):
                calls.append((url,kwargs)); return Response()
        client = GooglePoolClient(lambda: {'base_url':'http://fixture', 'auth_key':'fixture-key'}, session_factory=Session, domain='google-web')
        result, meta = GooglePoolProvider(client, route='google_web').generate('synthetic', aspect_ratio='9:16', model='gemini-3-pro-image')
        self.assertEqual(result, raw)
        self.assertEqual(meta['google_provider_route'], 'google_web')
        self.assertEqual(meta['requested_resolution'], '2k')
        self.assertIn('/2K', meta['output_size_warning'])
        self.assertIn('9:16', meta['output_size_warning'])
        self.assertEqual(calls[0][0], 'http://fixture/api/google-web/models/gemini-3-pro-image:streamGenerateContent?alt=sse')
        self.assertEqual(calls[0][1]['headers'], {'Authorization':'Bearer fixture-key'})

    def test_web_generate_edit_archive_and_delivery_use_existing_workers(self):
        from backend.services import google_generation as service
        from backend.api_client import save_image
        from backend.storage_paths import write_obsidian_prompt_sidecar
        raw = base64.b64decode(picture()['candidates'][0]['content']['parts'][0]['inlineData']['data'])
        for edit in (False, True):
            with self.subTest(edit=edit), tempfile.TemporaryDirectory() as temp, patch('builtins.print'), patch('backend.api_client.edit_image') as old_edit:
                worker = service.process_edit_task if edit else service.process_task
                deps = {name: Mock() for name, parameter in inspect.signature(worker).parameters.items()
                        if parameter.kind == inspect.Parameter.KEYWORD_ONLY}
                deps.update(DEFAULT_GOOGLE_IMAGE_MODEL='gemini-3-pro-image', Path=Path, os=os, time=time,
                    _effective_image_ratio=lambda p,r,default:r or default,
                    _is_generic_19_fidelity_prompt=lambda _:False, _coerce_google_max_tokens=lambda _:4096,
                    _coerce_google_output_controls=lambda p:(True,True), _should_fallback_to_gpt=lambda p,e:False,
                    daily_output_dir=lambda _:Path(temp), save_image=save_image,
                    write_obsidian_prompt_sidecar=write_obsidian_prompt_sidecar)
                if edit: deps['json']=json
                selected = deps['google_web_edit' if edit else 'google_web_generate']
                selected.return_value = (raw, {'google_provider_route':'google_web'})
                deps['send_telegram'].return_value = True
                args = ['synthetic-task','synthetic prompt'] + ([['unused-synthetic-reference']] if edit else []) + [
                    {'google_provider_route':'google_web','model':'gemini-3-pro-image','ratio':'1:1','quality':'2k'}]
                worker(*args, **deps)
                images = list(Path(temp).glob('*.png'))
                self.assertEqual(len(images), 1)
                self.assertEqual(images[0].read_bytes(), raw)
                self.assertEqual(images[0].with_suffix('.txt').read_text(), 'synthetic prompt')
                self.assertTrue(images[0].with_suffix('.md').is_file())
                selected.assert_called_once()
                self.assertEqual(selected.call_args.kwargs['task_id'], 'synthetic-task')
                deps['google_pool_edit' if edit else 'google_pool_generate'].assert_not_called()
                deps['generate_image_gpt_pool'].assert_not_called()
                old_edit.assert_not_called()
                deps['send_telegram'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
