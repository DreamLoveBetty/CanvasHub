"""Private Web download evidence; synthetic accounts/images, no network or secrets."""
import importlib.util
from enum import IntEnum
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image


def generated_image(client=None):
    return SimpleNamespace(client_ref=client or SimpleNamespace(authuser=1),
        url='https://lh3.googleusercontent.com/gg/preview?sig=PRIVATE-SIGNATURE',
        cid='c_private', rid='r_private', rcid='rc_private',
        image_id='private-image', temporary=True, prompt='DO-NOT-STORE-PROMPT',
        cookies={'SID': 'DO-NOT-STORE-COOKIE'})


def png_bytes():
    output = io.BytesIO()
    Image.new('RGB', (32, 18), 'red').save(output, 'PNG')
    return output.getvalue()


def reply(raw=b'<html>PRIVATE-RESPONSE</html>', status=403, headers=None):
    return SimpleNamespace(status_code=status, content=raw, headers=headers or {},
        raise_for_status=lambda: None)


class DiagnosticStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'download_diagnostics'

    def diagnostics(self, **kwargs):
        try:
            from sidecars.google_web.download_diagnostics import DownloadDiagnostics
        except ImportError:
            self.fail('Web downloads need private, bounded evidence before a failed locator is lost')
        return DownloadDiagnostics(self.directory, **kwargs)

    def start(self, diagnostics=None):
        return (diagnostics or self.diagnostics()).begin('account-one', generated_image(),
            ratio='16:9', size='2K', reference_count=0, image_count=1)

    def test_checkpoint_is_private_and_whitelists_lookup_context_not_object_secrets(self):
        trace = self.start()
        path = self.directory / (trace.id + '.json')
        record = json.loads(path.read_text())
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(record['account_id'], 'account-one')
        self.assertEqual(record['authuser'], 1)
        self.assertEqual(record['outcome'], 'pending')
        self.assertEqual(record['image'], {'url': generated_image().url, 'cid': 'c_private',
            'rid': 'r_private', 'rcid': 'rc_private', 'image_id': 'private-image', 'temporary': True})
        self.assertEqual(record['request'], {'ratio': '16:9', 'size': '2K',
            'reference_count': 0, 'image_count': 1})
        self.assertNotIn('DO-NOT-STORE', path.read_text())

    def test_verified_original_removes_checkpoint_but_preview_and_failure_keep_it(self):
        for outcome in ('verified', 'preview', 'failed', 'interrupted'):
            with self.subTest(outcome=outcome):
                trace = self.start()
                trace.original_url('https://lh3.googleusercontent.com/gg/original?sig=PRIVATE-ORIGINAL')
                trace.finish(outcome)
                path = self.directory / (trace.id + '.json')
                self.assertEqual(path.exists(), outcome != 'verified')
                if path.exists():
                    record = json.loads(path.read_text())
                    self.assertEqual(record['outcome'], outcome)
                    self.assertIn('PRIVATE-ORIGINAL', record['original_url'])

    def test_events_and_logs_never_include_signed_urls_exception_bodies_or_unknown_fields(self):
        with self.assertLogs('sidecars.google_web.download_diagnostics', level='INFO') as logs:
            trace = self.start()
            trace.event('original', 'http_error', http_status=403, hop=2,
                host_kind='cdn', url=generated_image().url, body='PRIVATE-RESPONSE',
                exception='PRIVATE-EXCEPTION')
            trace.event('PRIVATE-STAGE', 'PRIVATE-REASON', host_kind='PRIVATE-HOST',
                http_status='PRIVATE-STATUS')
            trace.finish('failed')
        public_log = '\n'.join(logs.output)
        self.assertIn('403', public_log)
        self.assertIn(trace.id, public_log)
        self.assertNotIn('PRIVATE-', public_log)
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertEqual(record['events'][0], {'stage': 'original', 'reason': 'http_error',
            'http_status': 403, 'hop': 2, 'host_kind': 'cdn'})
        self.assertNotIn('PRIVATE-RESPONSE', json.dumps(record))

    def test_retention_is_bounded_by_age_and_count_without_touching_other_files(self):
        diagnostics = self.diagnostics(max_records=2, max_age=60)
        expired = self.start(diagnostics)
        expired_path = self.directory / (expired.id + '.json')
        os.utime(expired_path, (time.time() - 120, time.time() - 120))
        unrelated = self.directory / 'unrelated.json'
        unrelated.write_text('retain me')
        self.start(diagnostics)
        second = self.start(diagnostics)
        third = self.start(diagnostics)
        records = list(self.directory.glob('wd_*.json'))
        self.assertFalse(expired_path.exists())
        self.assertEqual(len(records), 2)
        self.assertTrue((self.directory / (second.id + '.json')).exists())
        self.assertTrue((self.directory / (third.id + '.json')).exists())
        self.assertEqual(unrelated.read_text(), 'retain me')

    def test_symlink_destination_is_not_followed_or_replaced(self):
        other = Path(self.temp.name) / 'other'
        other.mkdir()
        self.directory.symlink_to(other, target_is_directory=True)
        with self.assertLogs('sidecars.google_web.download_diagnostics', level='WARNING'):
            trace = self.start()
            trace.finish('failed')
        self.assertEqual(list(other.iterdir()), [])

    def test_checkpoint_io_failure_is_sanitized_and_does_not_escape_or_use_another_directory(self):
        diagnostics = self.diagnostics()
        with patch('pathlib.Path.mkdir', side_effect=PermissionError('PRIVATE-PERMISSION-PATH')):
            with self.assertLogs('sidecars.google_web.download_diagnostics', level='WARNING') as logs:
                trace = self.start(diagnostics)
                trace.finish('failed')
        self.assertNotIn('PRIVATE-PERMISSION-PATH', '\n'.join(logs.output))
        self.assertFalse(self.directory.exists())

    def test_failed_atomic_write_and_cleanup_do_not_replace_download_with_a_storage_error(self):
        diagnostics = self.diagnostics()
        with patch('os.replace', side_effect=PermissionError('PRIVATE-WRITE-PATH')), \
                patch('pathlib.Path.unlink', side_effect=PermissionError('PRIVATE-CLEANUP-PATH')):
            with self.assertLogs('sidecars.google_web.download_diagnostics', level='WARNING') as logs:
                try:
                    trace = self.start(diagnostics)
                    trace.finish('verified')
                except OSError:
                    self.fail('Checkpoint cleanup must not interrupt a successful download')
        self.assertNotIn('PRIVATE-', '\n'.join(logs.output))

    def test_event_count_is_bounded_without_losing_failure_outcome(self):
        trace = self.start()
        for _ in range(100):
            trace.event('original', 'response', http_status=200)
        trace.finish('failed')
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertLessEqual(len(record['events']), 24)
        self.assertEqual(record['outcome'], 'failed')

    def test_failure_summary_is_visible_at_default_warning_log_level_and_still_redacted(self):
        trace = self.start()
        trace.event('original', 'http_error', http_status=403)
        trace.original_url('https://lh3.googleusercontent.com/gg/original?sig=PRIVATE-ORIGINAL')
        with self.assertLogs('sidecars.google_web.download_diagnostics', level='WARNING') as logs:
            trace.finish('failed')
        self.assertIn('403', '\n'.join(logs.output))
        self.assertIn(trace.id, '\n'.join(logs.output))
        self.assertNotIn('PRIVATE-', '\n'.join(logs.output))


class DownloadDiagnosticFlowTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'download_diagnostics'

    def trace(self, image):
        try:
            from sidecars.google_web.download_diagnostics import DownloadDiagnostics
        except ImportError:
            self.fail('Downloads currently erase the actual original/preview failure')
        return DownloadDiagnostics(self.directory).begin('account-one', image,
            ratio='16:9', size='2K', reference_count=0, image_count=1)

    def image_and_http(self, response):
        calls = []

        async def original(**kwargs):
            calls.append(('rpc', kwargs))
            return 'https://lh3.googleusercontent.com/gg/original?sig=PRIVATE-ORIGINAL'

        async def get(url, **kwargs):
            # Checkpoint must exist BEFORE the first image download, not only after failure.
            self.assertEqual(len(list(self.directory.glob('wd_*.json'))), 1)
            calls.append(('get', url))
            if isinstance(response, BaseException):
                raise response
            return response

        image = generated_image(SimpleNamespace(authuser=1, _get_full_size_image=original))
        return image, SimpleNamespace(get=get), calls

    async def test_http_failures_remain_distinct_and_recoverable_without_rpc_or_generation_replay(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        image, http, calls = self.image_and_http(reply())
        trace = self.trace(image)
        with self.assertRaises(WebError) as caught:
            await download_generated_image(image, http, trace=trace)
        self.assertEqual(caught.exception.code, 'web_image_download_failed')
        self.assertEqual(caught.exception.status, 502)
        message = str(caught.exception)
        self.assertIn('原图 HTTP 403', message)
        self.assertIn('预览图 HTTP 403', message)
        self.assertIn(trace.id, message)
        self.assertNotIn('PRIVATE-', message)
        self.assertIn('未重新提交生成', message)
        self.assertEqual([call[0] for call in calls], ['rpc', 'get', 'get'])
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertEqual(record['outcome'], 'failed')
        self.assertEqual([(e['stage'], e['http_status']) for e in record['events']
            if e['reason'] == 'http_error'], [('original', 403), ('preview', 403)])
        self.assertIn('PRIVATE-ORIGINAL', record['original_url'])

    async def test_network_failure_is_not_misreported_as_forbidden_or_leaked(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        image, http, _ = self.image_and_http(RuntimeError('PRIVATE-TRANSPORT-URL'))
        trace = self.trace(image)
        with self.assertRaises(WebError) as caught:
            await download_generated_image(image, http, trace=trace)
        self.assertIn('网络传输失败', str(caught.exception))
        self.assertNotIn('403', str(caught.exception))
        self.assertNotIn('PRIVATE-', str(caught.exception))
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertEqual([e['stage'] for e in record['events'] if e['reason'] == 'transport_error'],
            ['original', 'preview'])

    async def test_numeric_network_error_enum_preserves_tls_code_without_exception_text(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image

        class NetworkCode(IntEnum):
            TLS_VERIFICATION = 60

        error = RuntimeError('PRIVATE-TLS-URL')
        error.code = NetworkCode.TLS_VERIFICATION
        image, http, _ = self.image_and_http(error)
        trace = self.trace(image)
        with self.assertRaises(WebError) as caught:
            await download_generated_image(image, http, trace=trace)
        self.assertIn('网络代码 60', str(caught.exception))
        self.assertNotIn('PRIVATE-', str(caught.exception))
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertEqual([e['transport_code'] for e in record['events']
            if e['reason'] == 'transport_error'], [60, 60])

    async def test_verified_bytes_and_provenance_unchanged_and_checkpoint_removed(self):
        from sidecars.google_web.images import download_generated_image
        expected = png_bytes()
        image, http, calls = self.image_and_http(reply(expected, 200))
        trace = self.trace(image)
        raw, mime, provenance = await download_generated_image(image, http, trace=trace)
        self.assertEqual((raw, mime), (expected, 'image/png'))
        self.assertEqual(provenance, {'web_image_source': 'original_rpc', 'web_original_verified': True})
        self.assertEqual([call[0] for call in calls], ['rpc', 'get'])
        self.assertEqual(list(self.directory.glob('wd_*.json')), [])

    async def test_preview_fallback_retains_original_context_without_publishing_it(self):
        from sidecars.google_web.images import download_generated_image
        image, http, _ = self.image_and_http(reply(png_bytes(), 200))

        async def unavailable(**_):
            return None

        image.client_ref._get_full_size_image = unavailable
        trace = self.trace(image)
        _, _, provenance = await download_generated_image(image, http, trace=trace)
        self.assertEqual(provenance, {'web_image_source': 'preview_fallback',
            'web_original_verified': False, 'web_original_error': 'rpc_unavailable'})
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertEqual(record['outcome'], 'preview')
        self.assertTrue(any(e['reason'] == 'rpc_no_url' for e in record['events']))
        self.assertNotIn('PRIVATE-', json.dumps(provenance))

    async def test_rpc_exception_is_not_confused_with_download_url_rejection(self):
        from sidecars.google_web.images import download_generated_image
        image, http, _ = self.image_and_http(reply(png_bytes(), 200))

        async def broken_rpc(**_):
            raise ValueError('PRIVATE-RPC-RESPONSE')

        image.client_ref._get_full_size_image = broken_rpc
        trace = self.trace(image)
        await download_generated_image(image, http, trace=trace)
        record = json.loads((self.directory / (trace.id + '.json')).read_text())
        self.assertTrue(any(e['stage'] == 'rpc' and e['reason'] == 'rpc_error' for e in record['events']))
        self.assertNotIn('PRIVATE-RPC', json.dumps(record))

    async def test_invalid_html_is_reported_as_response_not_as_image_or_account_expiry(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        image, http, calls = self.image_and_http(reply(status=200))
        trace = self.trace(image)
        with self.assertRaises(WebError) as caught:
            await download_generated_image(image, http, trace=trace)
        self.assertEqual(caught.exception.code, 'web_image_download_failed')
        self.assertIn('下载地址响应无效', str(caught.exception))
        self.assertNotIn('PRIVATE-', str(caught.exception))
        self.assertEqual([call[0] for call in calls], ['rpc', 'get', 'get'])


HAS_WEB = all(importlib.util.find_spec(name) for name in ('curl_cffi', 'orjson', 'pydantic'))


@unittest.skipUnless(HAS_WEB, 'Requires Web runtime dependencies')
class UpstreamDiagnosticAssemblyTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_original_rpc_preserves_1003_as_safe_diagnostic_not_login_failure(self):
        from curl_cffi.requests import AsyncSession
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        with tempfile.TemporaryDirectory() as temp:
            try:
                from sidecars.google_web.download_diagnostics import DownloadDiagnostics
            except ImportError:
                self.fail('The original RPC rejection needs a safe per-image trace')
            client = GeminiClient(secure_1psid='DO-NOT-STORE-COOKIE', authuser=1)
            client._running, client.access_token = True, 'DO-NOT-STORE-ACCESS-TOKEN'
            http = AsyncSession()
            self.addAsyncCleanup(http.close)
            client.client = http
            calls = []

            async def post(url, **kwargs):
                self.assertEqual(kwargs['params']['rpcids'], 'c8o8Fe')
                calls.append('rpc')
                return SimpleNamespace(status_code=200, text=json.dumps([
                    ['di', 'DO-NOT-STORE-UPSTREAM'],
                    ['wrb.fr', 'c8o8Fe', None, None, None, [3, None,
                        [['synthetic.BardErrorInfo', [1003]]]], 'generic']]))

            async def get(*_, **__):
                calls.append('preview')
                return reply()

            http.post, http.get = post, get
            image = generated_image(client)
            trace = DownloadDiagnostics(Path(temp)).begin('account-one', image,
                ratio='16:9', size='2K', reference_count=0, image_count=1)
            with self.assertLogs('sidecars.google_web.download_diagnostics', level='INFO') as logs:
                with self.assertRaises(WebError) as caught:
                    await download_generated_image(image, http, trace=trace)
            self.assertEqual(caught.exception.code, 'web_image_download_failed')
            record = json.loads((Path(temp) / (trace.id + '.json')).read_text())
            self.assertTrue(any(e['stage'] == 'rpc' and e.get('rpc_error_code') == 1003
                for e in record['events']), 'Null RPC results must not erase the explicit 1003 code')
            self.assertEqual(calls, ['rpc', 'preview'])
            self.assertNotIn('DO-NOT-STORE', json.dumps(record))
            self.assertNotIn('PRIVATE-', '\n'.join(logs.output))

    async def test_real_upstream_assembles_account_and_plain_text_context_before_failed_download(self):
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from sidecars.google_web.vendor.gemini_webapi.types import GeneratedImage
        from curl_cffi.requests import AsyncSession
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'download_diagnostics'
            upstream = GeminiWebUpstream(WebSettings(Path(temp) / 'web.db'), lambda *_: None)
            client = GeminiClient(secure_1psid='DO-NOT-STORE-COOKIE', authuser=1)
            submissions = []

            async def submit(_client, prompt, **kwargs):
                submissions.append((prompt, kwargs))
                return SimpleNamespace(images=[GeneratedImage(
                    url='https://lh3.googleusercontent.com/gg/preview?sig=PRIVATE-PREVIEW',
                    client_ref=client, cid='c_private', rid='r_private', rcid='rc_private',
                    image_id='private-image', temporary=True)])

            async def original(_client, **_):
                return 'https://lh3.googleusercontent.com/gg/original?sig=PRIVATE-ORIGINAL'

            async def get(*_, **__):
                self.assertEqual(len(list(directory.glob('wd_*.json'))), 1)
                return reply()

            http = AsyncSession()
            self.addAsyncCleanup(http.close)
            http.get = get
            client.client = http
            upstream.sessions['account-one'] = {'client': client, 'revision': 1}
            with patch.object(GeminiClient, 'generate_content', new=submit), \
                    patch.object(GeminiClient, '_get_full_size_image', new=original):
                with self.assertRaises(WebError) as caught:
                    await upstream.generate('account-one', {
                        'contents': [{'parts': [{'text': 'DO-NOT-STORE-PROMPT'}]}],
                        'generationConfig': {'imageConfig': {'aspectRatio': '16:9', 'imageSize': '2K'}}})
            self.assertEqual(len(submissions), 1, 'No extra generation for diagnostic capture')
            records = list(directory.glob('wd_*.json'))
            self.assertEqual(len(records), 1)
            record = json.loads(records[0].read_text())
            self.assertEqual(record['account_id'], 'account-one')
            self.assertEqual(record['authuser'], 1)
            self.assertEqual(record['request']['reference_count'], 0)
            self.assertEqual(record['request']['ratio'], '16:9')
            self.assertEqual(record['request']['size'], '2K')
            self.assertIn(record['trace_id'], str(caught.exception))
            self.assertNotIn('DO-NOT-STORE', records[0].read_text())


if __name__ == '__main__':
    unittest.main()
