"""Fair google_pool image-account rotation and conservative same-task retry.

Synthetic accounts and mocked upstream only. No live Google calls, tokens, or images.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from sidecars.google_pool import pool as google_pool
from sidecars.google_pool.config import GoogleSettings
from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.pool import GooglePool
from sidecars.google_pool.store import GoogleStore
from sidecars.google_pool.upstream import GoogleUpstream
from sidecars.google_pool.wire import prepare_request
from backend.provider_google_pool import GooglePoolProvider


MODEL = 'gemini-3.1-flash-image'
PNG = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)


def document():
    return {
        'candidates': [
            {
                'content': {
                    'parts': [
                        {'text': '图片'},
                        {'inlineData': {'mimeType': 'image/png', 'data': PNG}},
                    ]
                }
            }
        ]
    }


def body(edit=False):
    parts = [{'text': 'fixture'}]
    if edit:
        parts.append({'inlineData': {'mimeType': 'image/png', 'data': PNG}})
    return {
        'contents': [{'parts': parts}],
        'generationConfig': {'imageConfig': {'aspectRatio': '9:16', 'imageSize': '4K'}},
    }



def http_reject(message, status, code, reasons=None):
    return GoogleError(
        message,
        status,
        code,
        reasons=reasons,
        http_status_rejection=True,
    )


def sse_event(value):
    return b'data: ' + json.dumps(value, ensure_ascii=False).encode() + b'\r\n\r\n'


class HttpResponse:
    def __init__(self, payload=None, status=200, chunks=None):
        self.data = payload
        self.status_code = status
        self.chunks = chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def json(self):
        return self.data

    def iter_content(self, chunk_size=None):
        if self.chunks is None:
            if self.data is not None:
                yield json.dumps(self.data).encode()
            return
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk


def mock_session(response):
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.post.return_value = response
    session.request.return_value = response
    return session


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = GoogleSettings(
            Path(self.temp.name) / 'accounts.db',
            'public-id',
            'public-secret',
            'http://localhost:18080/oauth-callback',
        )
        self.store = GoogleStore(self.settings.db_path)
        self.upstream = Mock()
        self.upstream.token.return_value = {
            'access_token': 'fixture-new-access',
            'refresh_token': 'fixture-new-refresh',
            'expires_in': 3600,
        }
        self.upstream.profile.return_value = {'email': 'fixture@example.test'}
        self.upstream.metadata.side_effect = lambda token, method, payload, **kwargs: (
            {'cloudaicompanionProject': {'id': 'fixture-project'}}
            if method == 'loadCodeAssist'
            else {
                'models': {
                    MODEL: {
                        'quotaInfo': {
                            'remainingFraction': 0.7,
                            'resetTime': '2026-09-15T00:00:00Z',
                        }
                    }
                }
            }
        )
        self.upstream.generate.side_effect = lambda *args: document()
        self.pool = GooglePool(self.store, self.upstream)

    def ready(self, key):
        account_id = self.store.import_account(
            {
                'refresh_token': key,
                'access_token': 'fixture-access',
                'expires_in': 3600,
                'project_id': 'fixture-project',
            }
        )['id']
        self.store.set_enabled(True)
        self.pool.refresh(account_id)
        return account_id

    def ready_many(self, n):
        return [self.ready(f'fixture-{i}') for i in range(n)]

    def sorted_ids(self, ids):
        return sorted(ids)


class PolicyClassificationTests(unittest.TestCase):
    def test_tos_is_policy_restriction_and_not_retryable(self):
        error = GoogleError(
            'Google 图像生成失败（HTTP 403，TOS_VIOLATION）',
            403,
            'google_upstream_error',
            reasons=('TOS_VIOLATION',),
        )
        self.assertTrue(google_pool.is_policy_restriction(error))
        self.assertFalse(google_pool.can_retry_other_account(error, submitted=False))
        self.assertFalse(google_pool.can_retry_other_account(error, submitted=True))

    def test_unclassified_403_is_not_retryable(self):
        error = GoogleError('Google 图像生成失败（HTTP 403）', 403, 'google_upstream_error')
        self.assertFalse(google_pool.can_retry_other_account(error, submitted=False))
        self.assertFalse(google_pool.can_retry_other_account(error, submitted=True))

    def test_timeout_and_unknown_execution_are_not_retryable_after_submit(self):
        for error in (
            GoogleError('Google 生成超过等待期限；未重新提交', 504, 'google_timeout'),
            GoogleError('上游执行状态未知，未重新提交', 502, 'google_execution_unknown'),
            GoogleError('Google 未返回图片', 502, 'google_no_image'),
            GoogleError('Google 图像生成失败（HTTP 500）', 500, 'google_upstream_error'),
        ):
            with self.subTest(code=error.code, status=error.status):
                self.assertFalse(google_pool.can_retry_other_account(error, submitted=True))

    def test_quota_and_preflight_account_errors_can_switch(self):
        quota = http_reject('额度不足（HTTP 429）', 429, 'google_quota_exhausted')
        self.assertTrue(google_pool.can_retry_other_account(quota, submitted=True))
        self.assertTrue(google_pool.can_retry_other_account(quota, submitted=False))
        model = GoogleError('此账号没有所请求档位的可用图像模型', 429, 'google_model_unavailable')
        self.assertTrue(google_pool.can_retry_other_account(model, submitted=False))
        self.assertFalse(google_pool.can_retry_other_account(model, submitted=True))
        auth = http_reject('Google 授权失效，请重新登录', 401, 'google_auth_expired')
        self.assertTrue(google_pool.can_retry_other_account(auth, submitted=False))
        self.assertTrue(google_pool.can_retry_other_account(auth, submitted=True))
        preflight_auth = GoogleError('Google 授权失效，请重新登录', 401, 'google_auth_expired')
        self.assertTrue(google_pool.can_retry_other_account(preflight_auth, submitted=False))
        self.assertFalse(google_pool.can_retry_other_account(preflight_auth, submitted=True))

    def test_post_submit_switch_requires_http_status_rejection_evidence(self):
        bare_quota = GoogleError('额度不足（HTTP 429）', 429, 'google_quota_exhausted')
        bare_auth = GoogleError('Google 授权失效，请重新登录', 401, 'google_auth_expired')
        nested = GoogleError(
            'Google 流式响应返回错误；未重新提交',
            429,
            'google_quota_exhausted',
        )
        mismatched = http_reject('失败（HTTP 429）', 429, 'google_upstream_error')
        flagged_500 = http_reject('失败（HTTP 500）', 500, 'google_upstream_error')
        for error in (bare_quota, bare_auth, nested, mismatched, flagged_500):
            with self.subTest(error=str(error), code=error.code, status=error.status):
                self.assertFalse(google_pool.can_retry_other_account(error, submitted=True))

    def test_cancel_and_disabled_are_not_retryable(self):
        for error in (
            GoogleError('生成已取消', 499, 'cancelled'),
            GoogleError('Google OAuth 账号池未启用', 503, 'google_pool_disabled'),
        ):
            self.assertFalse(google_pool.can_retry_other_account(error, submitted=False))


class RotationTests(Fixture):
    def test_new_requests_rotate_fairly_even_after_failure(self):
        ids = self.sorted_ids(self.ready_many(2))
        self.upstream.generate.side_effect = [
            GoogleError(
                'Google 图像生成失败（HTTP 403，TOS_VIOLATION）',
                403,
                'google_upstream_error',
                reasons=('TOS_VIOLATION',),
            ),
            document(),
            document(),
        ]
        with self.assertRaises(GoogleError) as first:
            self.pool.generate(MODEL, body())
        self.assertIn('TOS_VIOLATION', str(first.exception))
        self.assertEqual(first.exception.account_id, ids[0])
        second = self.pool.generate(MODEL, body())
        third = self.pool.generate(MODEL, body())
        self.assertEqual(second['google_pool']['account_id'], ids[1])
        self.assertEqual(third['google_pool']['account_id'], ids[0])
        self.assertEqual(self.upstream.generate.call_count, 3)

    def test_single_eligible_account_keeps_existing_semantics(self):
        account_id = self.ready('only')
        first = self.pool.generate(MODEL, body())
        second = self.pool.generate(MODEL, body())
        self.assertEqual(first['google_pool']['account_id'], account_id)
        self.assertEqual(second['google_pool']['account_id'], account_id)
        self.assertEqual(self.upstream.generate.call_count, 2)

    def test_disabled_and_deleted_accounts_are_skipped_and_new_ones_join(self):
        first, second = self.sorted_ids(self.ready_many(2))
        self.store.patch(first, {'enabled': False})
        result = self.pool.generate(MODEL, body())
        self.assertEqual(result['google_pool']['account_id'], second)
        self.store.delete(second)
        third = self.ready('fixture-new')
        result = self.pool.generate(MODEL, body())
        self.assertEqual(result['google_pool']['account_id'], third)

    def test_concurrent_requests_do_not_lease_the_same_account(self):
        ids = set(self.ready_many(2))
        entered = threading.Event()
        release = threading.Event()
        seen = []

        def generate(account, *args, **kwargs):
            seen.append(account['id'])
            if len(seen) == 1:
                entered.set()
            release.wait(5)
            return document()

        self.upstream.generate.side_effect = generate
        results = []

        def worker():
            results.append(self.pool.generate(MODEL, body()))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        threads[0].start()
        self.assertTrue(entered.wait(2))
        threads[1].start()
        release.set()
        for thread in threads:
            thread.join(5)
        used = {item['google_pool']['account_id'] for item in results}
        self.assertEqual(used, ids)
        self.assertEqual(len(seen), 2)
        self.assertEqual(set(seen), ids)


class RetryTests(Fixture):
    def test_safe_quota_rejection_switches_account_once_each(self):
        ids = self.sorted_ids(self.ready_many(2))
        self.upstream.generate.side_effect = [
            http_reject('额度不足（HTTP 429）', 429, 'google_quota_exhausted'),
            document(),
        ]
        result = self.pool.generate(MODEL, body())
        self.assertEqual(result['google_pool']['account_id'], ids[1])
        self.assertEqual(result['google_pool']['attempt'], 2)
        self.assertEqual(self.upstream.generate.call_count, 2)
        self.assertEqual(self.store.get(ids[0])['failure_count'], 1)
        self.assertTrue(self.store.get(ids[0])['enabled'])
        self.assertFalse(self.store.get(ids[0])['requires_relogin'])

    def test_edit_request_follows_the_same_safe_retry_rules(self):
        ids = self.sorted_ids(self.ready_many(2))
        self.upstream.generate.side_effect = [
            http_reject('额度不足（HTTP 429）', 429, 'google_quota_exhausted'),
            document(),
        ]
        result = self.pool.generate(MODEL, body(edit=True))
        self.assertEqual(result['google_pool']['account_id'], ids[1])
        self.assertEqual(self.upstream.generate.call_count, 2)

    def test_tos_stops_immediately_and_does_not_disable_or_clear_account(self):
        first, second = self.sorted_ids(self.ready_many(2))
        before = self.store.get(first)
        self.upstream.generate.side_effect = GoogleError(
            'Google 图像生成失败（HTTP 403，TOS_VIOLATION）',
            403,
            'google_upstream_error',
            reasons=('TOS_VIOLATION',),
        )
        with self.assertRaises(GoogleError) as caught:
            self.pool.generate(MODEL, body())
        error = caught.exception
        self.assertIn('TOS_VIOLATION', str(error))
        self.assertEqual(error.account_id, first)
        self.assertEqual(error.attempt, 1)
        self.assertEqual(self.upstream.generate.call_count, 1)
        after = self.store.get(first)
        self.assertTrue(after['enabled'])
        self.assertFalse(after['requires_relogin'])
        self.assertEqual(after['refresh_token'], before['refresh_token'])
        self.assertEqual(after['access_token'], before['access_token'])
        self.assertEqual(after['project_id'], before['project_id'])
        self.assertEqual(after['failure_count'], 1)
        self.assertIn('TOS_VIOLATION', after['last_error'])
        self.assertEqual(self.store.get(second)['failure_count'], 0)
        public = error.public()
        self.assertEqual(public['error_code'], 'google_upstream_error')
        self.assertEqual(public['google_pool']['account_id'], first)
        self.assertEqual(public['google_pool']['attempt'], 1)
        dumped = str(public)
        for secret in (
            'fixture-access',
            'fixture-0',
            'fixture-project',
            'fixture@example.test',
            'public-secret',
        ):
            self.assertNotIn(secret, dumped)

    def test_preflight_tos_does_not_switch_or_submit(self):
        self.ready_many(2)
        self.upstream.metadata.side_effect = GoogleError(
            'Google 模型信息失败（HTTP 403，TOS_VIOLATION）',
            403,
            'google_upstream_error',
            reasons=('TOS_VIOLATION',),
        )
        # Force preflight refresh by aging the catalog.
        for item in self.store.list_public():
            self.store.patch(item['id'], {'models_checked_at': 1})
        with self.assertRaises(GoogleError) as caught:
            self.pool.generate(MODEL, body())
        self.assertIn('TOS_VIOLATION', str(caught.exception))
        self.upstream.generate.assert_not_called()

    def test_preflight_quota_zero_still_switches(self):
        first, second = self.sorted_ids(self.ready_many(2))
        self.store.patch(first, {'models': [{'name': MODEL, 'percentage': 0}]})
        result = self.pool.generate(MODEL, body())
        self.assertEqual(result['google_pool']['account_id'], second)
        self.upstream.generate.assert_called_once()

    def test_uncertain_timeout_does_not_resubmit_or_switch(self):
        self.ready_many(2)
        self.upstream.generate.side_effect = GoogleError(
            'Google 生成超过等待期限；未重新提交', 504, 'google_timeout'
        )
        with self.assertRaises(GoogleError) as caught:
            self.pool.generate(MODEL, body())
        self.assertEqual(caught.exception.code, 'google_timeout')
        self.upstream.generate.assert_called_once()

    def test_execution_unknown_and_no_image_do_not_switch(self):
        for code, message, status in (
            ('google_execution_unknown', '上游执行状态未知，未重新提交', 502),
            ('google_no_image', 'Google 未返回图片', 502),
            ('google_upstream_error', 'Google 图像生成失败（HTTP 500）', 500),
            ('google_upstream_error', 'Google 图像生成失败（HTTP 403）', 403),
        ):
            with self.subTest(code=code, status=status):
                self.setUp()
                self.ready_many(2)
                self.upstream.generate.side_effect = GoogleError(message, status, code)
                with self.assertRaises(GoogleError) as caught:
                    self.pool.generate(MODEL, body())
                self.assertEqual(caught.exception.code, code)
                self.upstream.generate.assert_called_once()

    def test_attempt_cap_and_no_second_try_on_same_account(self):
        ids = self.sorted_ids(self.ready_many(4))
        self.assertGreater(len(ids), google_pool.MAX_IMAGE_ACCOUNT_ATTEMPTS)
        self.upstream.generate.side_effect = http_reject('额度不足（HTTP 429）', 429, 'google_quota_exhausted')
        with self.assertRaises(GoogleError) as caught:
            self.pool.generate(MODEL, body())
        self.assertEqual(caught.exception.code, 'google_quota_exhausted')
        self.assertEqual(self.upstream.generate.call_count, google_pool.MAX_IMAGE_ACCOUNT_ATTEMPTS)
        self.assertEqual(caught.exception.attempt, google_pool.MAX_IMAGE_ACCOUNT_ATTEMPTS)
        used = [account['id'] for account, *_ in (call.args for call in self.upstream.generate.call_args_list)]
        self.assertEqual(used, ids[:google_pool.MAX_IMAGE_ACCOUNT_ATTEMPTS])
        self.assertEqual(len(set(used)), google_pool.MAX_IMAGE_ACCOUNT_ATTEMPTS)

    def test_success_metadata_includes_attempt_without_secrets(self):
        account_id = self.ready('only')
        result = self.pool.generate(MODEL, body())
        meta = result['google_pool']
        self.assertEqual(meta['account_id'], account_id)
        self.assertEqual(meta['attempt'], 1)
        self.assertEqual(meta['requested_model'], MODEL)
        self.assertEqual(meta['resolved_model'], MODEL)
        dumped = str(result)
        self.assertNotIn('fixture-access', dumped)
        self.assertNotIn('fixture-project', dumped)
        self.assertNotIn('fixture@example.test', dumped)

    def test_public_error_reasons_stay_allowlisted(self):
        error = GoogleError(
            'Google 图像生成失败（HTTP 403，TOS_VIOLATION）',
            403,
            'google_upstream_error',
            reasons=('TOS_VIOLATION',),
            account_id='abc123',
            attempt=1,
        )
        public = error.public()
        self.assertEqual(public['error'], 'Google 图像生成失败（HTTP 403，TOS_VIOLATION）')
        self.assertEqual(public['google_pool'], {'account_id': 'abc123', 'attempt': 1})
        self.assertNotIn('email', public)
        self.assertNotIn('token', public)
        self.assertNotIn('project_id', public)


class ProviderAttemptAnnotationTests(unittest.TestCase):
    def test_reraise_appends_anonymous_attempt_and_ignores_secrets(self):
        from backend.provider_google_pool import _reraise_with_pool_attempt

        try:
            try:
                raise ValueError('Google 流式接口错误：Google 图像生成失败（HTTP 403，TOS_VIOLATION）')
            except ValueError:
                _reraise_with_pool_attempt(
                    'google_pool',
                    {'account_id': '0898e9f10cfb47c4', 'attempt': 1, 'email': 'hidden@example.test'},
                )
        except ValueError as exc:
            text = str(exc)
            self.assertIn('account_id=0898e9f10cfb47c4', text)
            self.assertIn('attempt=1', text)
            self.assertNotIn('hidden@example.test', text)
        else:
            self.fail('expected ValueError')

    def test_reraise_ignores_non_hex_identifiers(self):
        from backend.provider_google_pool import _reraise_with_pool_attempt

        with self.assertRaises(ValueError) as caught:
            try:
                raise ValueError('boom')
            except ValueError:
                _reraise_with_pool_attempt('google_pool', {'account_id': 'user@example.test'})
        self.assertEqual(str(caught.exception), 'boom')




class AdditionalRotationTests(Fixture):
    def test_success_rotates_a_b_c_a(self):
        ids = self.sorted_ids(self.ready_many(3))
        used = [self.pool.generate(MODEL, body())['google_pool']['account_id'] for _ in range(4)]
        self.assertEqual(used, [ids[0], ids[1], ids[2], ids[0]])
        self.assertEqual(self.upstream.generate.call_count, 4)

    def test_new_task_advances_after_failed_task(self):
        ids = self.sorted_ids(self.ready_many(3))
        self.upstream.generate.side_effect = [
            GoogleError('Google 生成超过等待期限；未重新提交', 504, 'google_timeout'),
            document(),
        ]
        with self.assertRaises(GoogleError) as first:
            self.pool.generate(MODEL, body())
        self.assertEqual(first.exception.code, 'google_timeout')
        self.assertEqual(first.exception.account_id, ids[0])
        self.upstream.generate.assert_called_once()
        second = self.pool.generate(MODEL, body())
        self.assertEqual(second['google_pool']['account_id'], ids[1])
        self.assertEqual(self.upstream.generate.call_count, 2)

    def test_post_submit_http_401_switches_with_status_evidence(self):
        ids = self.sorted_ids(self.ready_many(2))
        self.upstream.generate.side_effect = [
            http_reject('Google 图像生成失败（HTTP 401）', 401, 'google_auth_expired'),
            document(),
        ]
        result = self.pool.generate(MODEL, body())
        self.assertEqual(result['google_pool']['account_id'], ids[1])
        self.assertEqual(result['google_pool']['attempt'], 2)
        self.assertEqual(self.upstream.generate.call_count, 2)
        self.assertTrue(self.store.get(ids[0])['requires_relogin'])
        self.assertTrue(self.store.get(ids[0])['enabled'])

    def test_post_submit_401_without_http_evidence_does_not_switch(self):
        self.sorted_ids(self.ready_many(2))
        self.upstream.generate.side_effect = GoogleError(
            'Google 授权失效，请重新登录', 401, 'google_auth_expired'
        )
        with self.assertRaises(GoogleError):
            self.pool.generate(MODEL, body())
        self.upstream.generate.assert_called_once()

    def test_concurrent_selection_advances_shared_cursor_exclusively(self):
        ids = self.sorted_ids(self.ready_many(3))
        started = threading.Barrier(3)
        release = threading.Event()
        seen = []

        def generate(account, *args, **kwargs):
            seen.append(account['id'])
            started.wait(5)
            release.wait(5)
            return document()

        self.upstream.generate.side_effect = generate
        results = []

        def worker():
            results.append(self.pool.generate(MODEL, body()))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        started.wait(5)
        with self.pool.lock:
            leased = set(seen)
            self.assertEqual(leased, {ids[0], ids[1]})
            self.assertEqual(len(self.pool.inflight), 2)
            self.assertIn(self.pool._rr_after_id, leased)
        release.set()
        for thread in threads:
            thread.join(5)
        used = {item['google_pool']['account_id'] for item in results}
        self.assertEqual(used, {ids[0], ids[1]})
        self.upstream.generate.side_effect = lambda *args, **kwargs: document()
        third = self.pool.generate(MODEL, body())
        self.assertEqual(third['google_pool']['account_id'], ids[2])


class UpstreamHttpRejectionTests(Fixture):
    def _upstream(self, response):
        session = mock_session(response)
        upstream = GoogleUpstream(self.settings, lambda: session)
        return upstream, session

    def test_http_429_before_stream_is_complete_status_rejection(self):
        payload = {'error': {'status': 'RESOURCE_EXHAUSTED', 'message': 'ya29.secret'}}
        upstream, session = self._upstream(HttpResponse(payload, 429))
        with self.assertRaises(GoogleError) as caught:
            upstream.generate(
                {'access_token': 'fixture-at', 'project_id': 'fixture-project', 'id': 'abc123'},
                MODEL,
                prepare_request(body()),
            )
        session.post.assert_called_once()
        error = caught.exception
        self.assertTrue(error.http_status_rejection)
        self.assertEqual(error.status, 429)
        self.assertEqual(error.code, 'google_quota_exhausted')
        self.assertIn('HTTP 429', str(error))
        self.assertNotIn('ya29.secret', str(error))
        self.assertTrue(google_pool.can_retry_other_account(error, submitted=True))
        url = session.post.call_args[0][0]
        self.assertIn(':streamGenerateContent', url)

    def test_http_401_before_stream_is_complete_status_rejection(self):
        payload = {'error': {'status': 'UNAUTHENTICATED', 'message': 'ya29.secret'}}
        upstream, session = self._upstream(HttpResponse(payload, 401))
        with self.assertRaises(GoogleError) as caught:
            upstream.generate(
                {'access_token': 'fixture-at', 'project_id': 'fixture-project', 'id': 'abc123'},
                MODEL,
                prepare_request(body()),
            )
        session.post.assert_called_once()
        error = caught.exception
        self.assertTrue(error.http_status_rejection)
        self.assertEqual(error.status, 401)
        self.assertEqual(error.code, 'google_auth_expired')
        self.assertTrue(google_pool.can_retry_other_account(error, submitted=True))

    def test_sse_started_429_body_is_not_http_status_rejection(self):
        payload = {
            'error': {
                'code': 429,
                'status': 'RESOURCE_EXHAUSTED',
                'message': 'quota',
                'details': [{'reason': 'RATE_LIMIT'}],
            }
        }
        upstream, session = self._upstream(HttpResponse(status=200, chunks=[sse_event(payload)]))
        with self.assertRaises(GoogleError) as caught:
            upstream.generate(
                {'access_token': 'fixture-at', 'project_id': 'fixture-project', 'id': 'abc123'},
                MODEL,
                prepare_request(body()),
            )
        session.post.assert_called_once()
        error = caught.exception
        self.assertFalse(bool(getattr(error, 'http_status_rejection', False)))
        self.assertNotEqual((error.status, error.code), (429, 'google_quota_exhausted'))
        self.assertFalse(google_pool.can_retry_other_account(error, submitted=True))

    def test_pool_does_not_resubmit_after_sse_started_429(self):
        ids = self.sorted_ids(self.ready_many(2))
        payload = {
            'error': {
                'code': 429,
                'status': 'RESOURCE_EXHAUSTED',
                'message': 'quota',
            }
        }
        session = mock_session(HttpResponse(status=200, chunks=[sse_event(payload)]))
        self.pool.upstream = GoogleUpstream(self.settings, lambda: session)
        # Bypass token/metadata by keeping ready() catalog; generate uses self.pool.upstream.
        with self.assertRaises(GoogleError) as caught:
            self.pool.generate(MODEL, body())
        session.post.assert_called_once()
        self.assertFalse(google_pool.can_retry_other_account(caught.exception, submitted=True))
        self.assertEqual(caught.exception.account_id, ids[0])


class ProviderSsePublicChainTests(unittest.TestCase):
    def test_provider_reads_error_public_from_sse_and_keeps_anonymous_ids(self):
        error = http_reject(
            'Google 图像生成失败（HTTP 429）',
            429,
            'google_quota_exhausted',
        )
        error.account_id = '0898e9f10cfb47c4'
        error.attempt = 1
        public = error.public()
        self.assertEqual(public['error_code'], 'google_quota_exhausted')
        self.assertEqual(public['google_pool'], {'account_id': '0898e9f10cfb47c4', 'attempt': 1})
        session = mock_session(HttpResponse(status=200, chunks=[sse_event(public)]))

        class Client:
            def connection(self):
                return 'http://127.0.0.1:18080', {'Authorization': 'Bearer fixture-local-key'}

            def session_factory(self):
                return session

        with self.assertRaises(ValueError) as caught:
            GooglePoolProvider(Client()).generate('fixture', model=MODEL)
        text = str(caught.exception)
        self.assertIn('Google 图像生成失败（HTTP 429）', text)
        self.assertIn('account_id=0898e9f10cfb47c4', text)
        self.assertIn('attempt=1', text)
        self.assertNotIn('fixture-local-key', text)
        session.post.assert_called_once()


if __name__ == '__main__':
    unittest.main()
