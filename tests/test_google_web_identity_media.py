"""Synthetic Web session/download regressions. No real cookies or network."""
import base64
import io
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

HAS_WEB = all(importlib.util.find_spec(name) for name in ('curl_cffi', 'orjson', 'pydantic'))


def image_bytes(size):
    out = io.BytesIO()
    Image.new('RGB', size, 'red').save(out, 'PNG')
    return out.getvalue()


class Reply:
    def __init__(self, content=b'', status=200, headers=None):
        self.content, self.status_code = content, status
        self.headers = headers or {}
        self.text = content.decode('utf-8', errors='replace')

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError('synthetic transport failure')


@unittest.skipUnless(HAS_WEB, 'Requires Web runtime dependencies')
class WebIdentityMediaTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from curl_cffi.requests import AsyncSession
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = WebSettings(Path(self.temp.name) / 'web.db')
        self.upstream = GeminiWebUpstream(self.settings, lambda *_: None)
        self.account = {'id': 'synthetic-a', 'revision': 1,
                        'cookies': {'__Secure-1PSID': 'synthetic-secret'}}
        self.http = AsyncSession()
        self.addAsyncCleanup(self.cleanup_http)
        self.client = GeminiClient(secure_1psid='synthetic-secret')
        self.client.client = self.http
        self.client._running = True
        self.preview, self.original = image_bytes((768, 1376)), image_bytes((1536, 2752))
        self.calls, self.submissions = [], []

    async def cleanup_http(self):
        await self.upstream.close()
        if not self.http._closed:
            await self.http.close()

    async def bootstrap(self, html):
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        def session(**_):
            self.http.get = AsyncMock(return_value=Reply(html.encode()))
            return self.http
        with patch('sidecars.google_web.vendor.gemini_webapi.utils.get_access_token.AsyncSession', session), \
                patch.object(GeminiClient, '_init_rpc', new=AsyncMock()):
            return await self.upstream.prepare(self.account)

    async def test_active_session_name_is_not_the_chrome_profile_or_another_google_account(self):
        identity = await self.bootstrap('''<script>var x={"SNlM0e":"private-token",
            "email":"other@example.test", "oPEP7c":"active@example.test"};</script>
            <a aria-label="Google Account: Active &amp; Name&#10;(active@example.test)"></a>
            <a aria-label="Google Account: Other Name (other@example.test)"></a>''')
        self.assertEqual(identity, {'display_name': 'Active & Name', 'email': 'active@example.test'})
        self.assertEqual(await self.upstream.prepare(self.account), identity)

    async def test_an_unmatched_account_menu_cannot_supply_another_accounts_name(self):
        identity = await self.bootstrap('''<script>{"SNlM0e":"token", "oPEP7c":"active@example.test"}</script>
            <a aria-label="Google Account: Other Name (other@example.test)"></a>''')
        self.assertEqual(identity, {'display_name': '', 'email': 'active@example.test'})

    async def test_generic_emails_do_not_identify_the_active_account(self):
        identity = await self.bootstrap('<script>{"SNlM0e":"token","email":"other@example.test"}</script>')
        self.assertEqual(identity, {'display_name': '', 'email': ''})

    async def test_localized_account_menu_and_json_escaped_email(self):
        identity = await self.bootstrap(r'''<script>{"SNlM0e":"token","oPEP7c":"active\u0040example.test"}</script>
            <a aria-label="Google 账号：合成用户 (active@example.test)"></a>''')
        self.assertEqual(identity, {'display_name': '合成用户', 'email': 'active@example.test'})

    async def generate_with(self, original_url, responses, request=None):
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from sidecars.google_web.vendor.gemini_webapi.types import GeneratedImage
        self.upstream.sessions['synthetic-a'] = {'client': self.client, 'revision': 1}
        async def get(url, **kwargs):
            self.calls.append((url, kwargs))
            if url in responses:
                return responses[url]
            if str(url).startswith('https://lh3.googleusercontent.com/gg/preview'):
                return Reply(self.preview)
            raise RuntimeError('unexpected fixture request')
        self.http.get = get
        generated = GeneratedImage(url='https://lh3.googleusercontent.com/gg/preview=s1024-rj',
            client=self.http, client_ref=self.client, cid='synthetic-c', rid='synthetic-r',
            rcid='synthetic-rc', image_id='synthetic-image')
        async def submit_image(prompt, **kwargs):
            self.submissions.append({'prompt': prompt,
                'files': [(file.name, file.getvalue()) for file in kwargs.get('files') or []],
                'pro_image': kwargs.get('pro_image'), 'temporary': kwargs.get('temporary')})
            return SimpleNamespace(images=[generated])
        with patch.object(GeminiClient, '_get_full_size_image', new=AsyncMock(return_value=original_url)), \
                patch.object(GeminiClient, 'generate_content', new=AsyncMock(side_effect=submit_image)) as submit:
            result = await self.upstream.generate('synthetic-a', request or {
                'contents': [{'parts': [{'text': 'synthetic 2K'}]}],
                'generationConfig': {'imageConfig': {'aspectRatio': '9:16', 'imageSize': '2K'}}})
        self.assertEqual(submit.await_count, 1, 'Download handling must never replay generation')
        raw = base64.b64decode(result['candidates'][0]['content']['parts'][0]['inlineData']['data'])
        return raw, result.get('google_pool', {})

    async def test_generation_prepends_requested_ratio_and_resolution_before_user_text(self):
        import copy
        from sidecars.google_pool.wire import prepare_request
        for ratio, size in [('9:16', '2K'), ('16:9', '4K'), ('1:1', '1K')]:
            with self.subTest(ratio=ratio, size=size):
                body = {'contents': [{'parts': [{'text': 'first user instruction'},
                    {'text': 'second user instruction'}]}],
                    'generationConfig': {'imageConfig': {'aspectRatio': ratio, 'imageSize': size}}}
                before = copy.deepcopy(body)
                await self.generate_with(None, {}, prepare_request(body))
                sent = self.submissions[-1]
                self.assertTrue(sent['prompt'].startswith(f'画幅：{ratio}；分辨率：{size}。\n\n'))
                self.assertIn('first user instruction\n\nsecond user instruction', sent['prompt'])
                self.assertEqual(sent['prompt'].count(ratio), 1)
                self.assertEqual(sent['files'], [])
                self.assertIs(sent['pro_image'], True)
                self.assertIs(sent['temporary'], True)
                self.assertEqual(body, before, 'Prompt instructions must not rewrite the request or text nodes')

    async def test_edit_default_2k_prefix_keeps_reference_bytes_and_user_instruction(self):
        from sidecars.google_pool.wire import prepare_request
        request = prepare_request({'contents': [{'parts': [{'text': 'edit this reference'},
            {'inlineData': {'mimeType': 'image/png', 'data': base64.b64encode(self.preview).decode()}}]}],
            'generationConfig': {'imageConfig': {'aspectRatio': '4:3'}}})
        await self.generate_with(None, {}, request)
        sent = self.submissions[-1]
        self.assertTrue(sent['prompt'].startswith('画幅：4:3；分辨率：2K。\n\nedit this reference'))
        self.assertEqual(sent['files'], [('reference.png', self.preview)])

    async def test_original_rpc_may_return_image_bytes_without_two_text_hops(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(self.original)})
        self.assertEqual(raw, self.original)
        self.assertEqual(meta.get('web_image_source'), 'original_rpc')
        self.assertIs(meta.get('web_original_verified'), True)

    async def test_original_rpc_may_return_one_text_pointer_then_image(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(b'https://lh3.googleusercontent.com/rd-gg-dl/original'),
            'https://lh3.googleusercontent.com/rd-gg-dl/original': Reply(self.original)})
        self.assertEqual(raw, self.original)
        self.assertIs(meta.get('web_original_verified'), True)

    async def test_original_rpc_two_text_hops_still_work(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(b'https://lh3.googleusercontent.com/pointer'),
            'https://lh3.googleusercontent.com/pointer': Reply(b'https://lh3.googleusercontent.com/rd-gg-dl/original'),
            'https://lh3.googleusercontent.com/rd-gg-dl/original': Reply(self.original)})
        self.assertEqual(raw, self.original)
        self.assertIs(meta.get('web_original_verified'), True)

    async def test_failed_original_retrieval_is_explicitly_unverified_not_fake_2k(self):
        raw, meta = await self.generate_with(None, {})
        self.assertEqual(raw, self.preview)
        self.assertEqual(meta.get('web_image_source'), 'preview_fallback')
        self.assertIs(meta.get('web_original_verified'), False)
        self.assertEqual(meta.get('web_original_error'), 'rpc_unavailable')
        self.assertNotIn('googleusercontent', json.dumps(meta))

    async def test_download_does_not_follow_untrusted_pointer_with_account_credentials(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(b'https://untrusted.example.test/image')})
        self.assertEqual(raw, self.preview)
        self.assertIs(meta.get('web_original_verified'), False)
        self.assertTrue(all(url.startswith('https://lh3.googleusercontent.com/') for url, _ in self.calls))

    async def test_redirects_are_bounded_and_every_hop_remains_trusted(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(status=302,
                headers={'location': '/rd-gg-dl/original'}),
            'https://lh3.googleusercontent.com/rd-gg-dl/original': Reply(self.original)})
        self.assertEqual(raw, self.original)
        self.assertIs(meta.get('web_original_verified'), True)
        self.assertTrue(all(kwargs.get('allow_redirects') is False for _, kwargs in self.calls))

    async def test_redirect_loop_falls_back_without_repeating_generation(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes': Reply(status=302,
                headers={'location': 'https://lh3.googleusercontent.com/rd-gg/original=d-I?alr=yes'})})
        self.assertEqual(raw, self.preview)
        self.assertIs(meta.get('web_original_verified'), False)
        self.assertEqual(len(self.calls), 2)

    async def test_original_url_query_signature_is_not_reencoded_or_lost(self):
        raw, meta = await self.generate_with('https://lh3.googleusercontent.com/rd-gg/original?sig=a%20b&part=1&part=2', {
            'https://lh3.googleusercontent.com/rd-gg/original=d-I?sig=a%20b&part=1&part=2&alr=yes': Reply(self.original)})
        self.assertEqual(raw, self.original)
        self.assertIs(meta.get('web_original_verified'), True)


class WebDownloadRedirectTest(unittest.IsolatedAsyncioTestCase):
    def session(self, replies):
        calls = []
        async def get(url, **kwargs):
            calls.append((url, kwargs))
            return replies[url]
        return SimpleNamespace(get=get, calls=calls)

    async def test_original_rd_gg_google_gateway_keeps_full_size_bytes_not_preview(self):
        from sidecars.google_web.images import download_generated_image
        original = image_bytes((1696, 2528))
        preview = image_bytes((768, 1152))
        initial = 'https://lh3.googleusercontent.com/gg/synthetic=d-I?sig=a%20b&alr=yes'
        gateway = 'https://lh3.google.com/rd-gg/synthetic=s0-d-I?sig=a%2Bb&part=1&part=2'
        final = 'https://lh3.googleusercontent.com/rd-gg/synthetic=s0-d-I?sig=c%2Bd'
        preview_url = 'https://lh3.googleusercontent.com/gg/preview=s0'
        for redirect in (False, True):
            with self.subTest(redirect=redirect):
                session = self.session({
                    initial: Reply(status=302, headers={'location': gateway}) if redirect else Reply(gateway.encode()),
                    gateway: Reply(final.encode()), final: Reply(original), preview_url: Reply(preview)})
                image = SimpleNamespace(url='https://lh3.googleusercontent.com/gg/preview=s1024-rj',
                    client_ref=SimpleNamespace(_get_full_size_image=AsyncMock(
                        return_value='https://lh3.googleusercontent.com/gg/synthetic?sig=a%20b')),
                    cid='synthetic-c', rid='synthetic-r', rcid='synthetic-rc', image_id='synthetic-image')
                raw, mime, meta = await download_generated_image(image, session)
                self.assertEqual(raw, original, 'The original must not silently fall back to the 1K preview')
                self.assertEqual(mime, 'image/png')
                self.assertEqual(meta, {'web_image_source': 'original_rpc', 'web_original_verified': True})
                self.assertEqual([url for url, _ in session.calls], [initial, gateway, final])
                for _, kwargs in session.calls:
                    self.assertIs(kwargs['allow_redirects'], False)
                    self.assertNotIn('Cookie', kwargs['headers'])
                    self.assertNotIn('Authorization', kwargs['headers'])

    async def test_rd_gg_gateway_does_not_allow_other_google_hosts_pages_or_credentials(self):
        from sidecars.google_web.images import download_generated_image
        from sidecars.google_web.errors import WebError
        initial = 'https://lh3.googleusercontent.com/gg/synthetic=s0'
        for target in (
            'https://lh3.google.com.attacker.test/rd-gg/synthetic',
            'https://lh4.google.com/rd-gg/synthetic',
            'https://accounts.google.com/rd-gg/synthetic',
            'https://lh3.google.com/ServiceLogin',
            'https://lh3.google.com/rd-gg-dl/synthetic',
            'https://lh3.google.com/rd-gg/../ServiceLogin',
            'https://lh3.google.com/rd-gg/%2e%2e/ServiceLogin',
            'http://lh3.google.com/rd-gg/synthetic',
            'https://lh3.google.com:8443/rd-gg/synthetic',
            'https://user:private@lh3.google.com/rd-gg/synthetic',
        ):
            with self.subTest(target=target):
                session = self.session({initial: Reply(target.encode())})
                image = SimpleNamespace(url='https://lh3.googleusercontent.com/gg/synthetic',
                    client_ref=None, cid='', rid='', rcid='', image_id='')
                with self.assertRaises(WebError) as raised:
                    await download_generated_image(image, session)
                self.assertEqual(raised.exception.code, 'web_image_download_failed')
                self.assertEqual([url for url, _ in session.calls], [initial])
                self.assertNotIn(target, str(raised.exception))

    async def test_authenticated_google_image_gateway_preserves_bytes_and_provenance(self):
        from sidecars.google_web.images import download_generated_image
        from sidecars.google_web.errors import WebError
        raw = image_bytes((1536, 2752))
        gateway = 'https://work.fife.usercontent.google.com/rd-gg-dl/synthetic?sig=a%20b&part=1&part=2'
        final = 'https://lh3.googleusercontent.com/rd-gg-dl/synthetic?sig=other%2Bvalue'
        for original, initial in [
            (True, 'https://lh3.googleusercontent.com/gg-dl/synthetic=d-I?sig=a%20b&alr=yes'),
            (False, 'https://lh3.googleusercontent.com/gg-dl/synthetic=s0?sig=a%20b'),
        ]:
            with self.subTest(original=original):
                session = self.session({initial: Reply(status=302, headers={'location': gateway}),
                    gateway: Reply(status=302, headers={'location': final}), final: Reply(raw)})
                client = SimpleNamespace(_get_full_size_image=AsyncMock(
                    return_value='https://lh3.googleusercontent.com/gg-dl/synthetic?sig=a%20b')) if original else None
                image = SimpleNamespace(url='https://lh3.googleusercontent.com/gg-dl/synthetic?sig=a%20b',
                    client_ref=client, cid='synthetic-c', rid='synthetic-r', rcid='synthetic-rc', image_id='synthetic-image')
                try:
                    result, mime, meta = await download_generated_image(image, session)
                except WebError:
                    self.fail('The authenticated Google image gateway must not be rejected as an untrusted redirect')
                self.assertEqual(result, raw)
                self.assertEqual(mime, 'image/png')
                self.assertEqual(meta['web_image_source'], 'original_rpc' if original else 'preview_fallback')
                self.assertEqual(meta['web_original_verified'], original)
                self.assertEqual([url for url, _ in session.calls], [initial, gateway, final])
                for _, kwargs in session.calls:
                    self.assertIs(kwargs['allow_redirects'], False)
                    self.assertNotIn('Cookie', kwargs['headers'], 'The downloader must retain normal Cookie-domain scoping')
                    self.assertNotIn('Authorization', kwargs['headers'])
                self.assertNotIn('https://', json.dumps(meta))

    async def test_gateway_allowlist_does_not_accept_other_hosts_paths_or_credentials(self):
        from sidecars.google_web.images import download_generated_image
        from sidecars.google_web.errors import WebError
        initial = 'https://lh3.googleusercontent.com/gg-dl/synthetic=s0'
        for target in (
            'https://work.fife.usercontent.google.com.attacker.test/rd-gg-dl/synthetic',
            'https://other.usercontent.google.com/rd-gg-dl/synthetic',
            'https://accounts.google.com/rd-gg-dl/synthetic',
            'https://work.fife.usercontent.google.com/ServiceLogin',
            'http://work.fife.usercontent.google.com/rd-gg-dl/synthetic',
            'https://work.fife.usercontent.google.com:8443/rd-gg-dl/synthetic',
            'https://user:private@work.fife.usercontent.google.com/rd-gg-dl/synthetic',
        ):
            with self.subTest(target=target):
                session = self.session({initial: Reply(status=302, headers={'location': target})})
                image = SimpleNamespace(url='https://lh3.googleusercontent.com/gg-dl/synthetic', client_ref=None,
                    cid='', rid='', rcid='', image_id='')
                with self.assertRaises(WebError) as raised:
                    await download_generated_image(image, session)
                self.assertEqual(raised.exception.code, 'web_image_download_failed')
                self.assertEqual([url for url, _ in session.calls], [initial])
                self.assertNotIn(target, str(raised.exception))
                self.assertNotIn('private', str(raised.exception))

    async def test_auth_gateway_redirect_cycles_still_stop_without_more_requests(self):
        from sidecars.google_web.images import download_generated_image
        from sidecars.google_web.errors import WebError
        initial = 'https://lh3.googleusercontent.com/gg-dl/synthetic=s0'
        gateway = 'https://work.fife.usercontent.google.com/rd-gg-dl/synthetic'
        session = self.session({initial: Reply(status=302, headers={'location': gateway}),
            gateway: Reply(status=302, headers={'location': initial})})
        image = SimpleNamespace(url='https://lh3.googleusercontent.com/gg-dl/synthetic', client_ref=None,
            cid='', rid='', rcid='', image_id='')
        with self.assertRaises(WebError):
            await download_generated_image(image, session)
        self.assertEqual([url for url, _ in session.calls], [initial, gateway])


class WebProviderProvenanceTest(unittest.TestCase):
    def provider_result(self, info, route='google_web'):
        from backend.provider_google_pool import GooglePoolProvider
        from backend.services.google_pool import GooglePoolClient
        raw = image_bytes((768, 1376))
        document = {'candidates': [{'content': {'parts': [{'inlineData': {
            'mimeType': 'image/png', 'data': base64.b64encode(raw).decode()}}]}}], 'google_pool': info}
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def iter_content(self, **_):
                yield b'data: ' + json.dumps(document).encode() + b'\n\n'
        class Session:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def post(self, *_args, **_kwargs): return Response()
        client = GooglePoolClient(lambda: {'base_url': 'http://fixture', 'auth_key': 'synthetic'}, session_factory=Session)
        result, meta = GooglePoolProvider(client, route=route).generate('synthetic 2K', '9:16')
        self.assertEqual(result, raw)
        return meta

    def test_unverified_download_warns_even_when_aspect_ratio_is_correct(self):
        meta = self.provider_result({'web_image_source': 'preview_fallback', 'web_original_verified': False,
            'web_original_error': 'rpc_unavailable', 'signed_url': 'private-signed-url'})
        self.assertEqual(meta.get('web_image_source'), 'preview_fallback')
        self.assertIs(meta.get('web_original_verified'), False)
        self.assertEqual(meta.get('actual_resolution'), '1k')
        self.assertIn('原图', meta.get('output_size_warning', ''))
        self.assertIn('未确认', meta.get('output_size_warning', ''))
        self.assertNotIn('原图已保留', meta.get('output_size_warning', ''))
        self.assertNotIn('private-signed-url', json.dumps(meta))

    def test_a_verified_1k_original_is_not_relabelled_2k(self):
        meta = self.provider_result({'web_image_source': 'original_rpc', 'web_original_verified': True})
        self.assertIs(meta.get('web_original_verified'), True)
        self.assertEqual(meta.get('actual_resolution'), '1k')
        self.assertEqual(meta.get('requested_resolution'), '2k')
        self.assertIs(meta.get('resolution_mismatch'), True)
        self.assertIn('9:16/2K', meta.get('output_size_warning', ''))
        self.assertNotIn('原图下载未确认', meta.get('output_size_warning', ''))

    def test_web_provenance_does_not_change_oauth_response_metadata(self):
        meta = self.provider_result({'web_image_source': 'original_rpc', 'web_original_verified': True}, 'google_pool')
        self.assertNotIn('web_image_source', meta)
        self.assertNotIn('web_original_verified', meta)
        self.assertEqual(meta.get('requested_resolution'), '2k')


if __name__ == '__main__':
    unittest.main()
