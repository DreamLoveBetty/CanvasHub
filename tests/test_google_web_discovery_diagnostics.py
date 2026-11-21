"""Desensitized Gemini Web discovery diagnostics. Synthetic HTML only; no live network."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

HAS_WEB = all(importlib.util.find_spec(n) for n in ('curl_cffi', 'orjson', 'pydantic'))
COOKIES = {'__Secure-1PSID': 'fixture-shared-session', '__Secure-1PSIDTS': 'fixture-old-ts'}
ITEM = {'label': 'Chrome · Default', 'cookies': COOKIES, 'source_profile': 'Default'}
SECRET_MARKERS = (
    'fixture-shared-session',
    'fixture-old-ts',
    'secret-login-token',
    '@example.test',
    '@gmail.',
    'alice@',
    '<html',
)


def _public_text(exc):
    return json.dumps(exc.public(), ensure_ascii=False, sort_keys=True)


class FakeReply:
    def __init__(self, text, url='https://gemini.google.com/app', status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self):
        pass


class FakeCookie:
    def __init__(self, name, value, domain='.google.com'):
        self.name = name
        self.value = value
        self.domain = domain

    def is_expired(self):
        return False


class FakeCookieJar:
    def __init__(self):
        self.jar = []

    def set(self, name, value, domain='.google.com', path='/', **kwargs):
        self.jar.append(FakeCookie(name, value, domain))


class FakeSession:
    def __init__(self, handler, *args, **kwargs):
        self.handler = handler
        self.cookies = FakeCookieJar()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        return await self.handler(url, **kwargs)


def gemini_page(slot, email='user@example.test', token='secret-login-token', qrtxk=None):
    return json.dumps({
        'SNlM0e': token,
        'QrtxK': str(slot if qrtxk is None else qrtxk),
        'oPEP7c': email,
    })


@unittest.skipUnless(HAS_WEB, 'Requires Web dependencies')
class DiscoveryDiagnosticsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.accounts import discover_accounts
        self.settings = WebSettings(Path('unused-fixture.db'))
        self.discover = discover_accounts
        self.WebError = WebError
        self.calls = []

    def _patch_http(self, handler):
        return patch('curl_cffi.requests.AsyncSession', return_value=FakeSession(handler))

    async def _discover(self, handler):
        with self._patch_http(handler):
            return await self.discover(ITEM, self.settings)

    def _assert_clean(self, payload):
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        for marker in SECRET_MARKERS:
            self.assertNotIn(marker, text)

    async def test_web_error_public_keeps_credential_free_details(self):
        err = self.WebError(
            '所选会话未找到已登录的 Gemini 账号',
            401,
            'web_auth_expired',
            details={'discovery': {'primary_reason': 'login_wall', 'valid_count': 0}},
        )
        payload = err.public()
        self.assertEqual(payload['error_code'], 'web_auth_expired')
        self.assertEqual(payload['details']['discovery']['primary_reason'], 'login_wall')
        self._assert_clean(payload)
        bare = self.WebError('登录已失效', 401, 'web_auth_expired')
        self.assertEqual(set(bare.public()), {'error', 'error_code'})

    async def test_login_wall_is_classified_without_leaking_page_content(self):
        async def handler(url, **kwargs):
            self.calls.append(int(kwargs['params']['authuser']))
            return FakeReply(
                '<html>Sign in to continue to Gemini</html>',
                url='https://accounts.google.com/ServiceLogin',
            )

        with self.assertRaises(self.WebError) as raised:
            await self._discover(handler)
        err = raised.exception
        self.assertEqual(err.code, 'web_auth_expired')
        discovery = err.public()['details']['discovery']
        self.assertEqual(discovery['primary_reason'], 'login_wall')
        self.assertEqual(discovery['reason_counts'].get('login_wall'), 2)
        self.assertTrue(discovery['stopped_early'])
        self.assertEqual(discovery['slots_tried'], 2)
        self.assertEqual(discovery['valid_count'], 0)
        self.assertEqual(discovery['host_kind_counts'], {'accounts': 2})
        self.assertTrue(discovery['cookie_presence']['__Secure-1PSID'])
        self.assertTrue(discovery['cookie_presence']['__Secure-1PSIDTS'])
        self._assert_clean(err.public())
        self.assertEqual(self.calls, [0, 1])

    async def test_missing_bootstrap_fields_on_gemini_host_are_classified(self):
        async def handler(url, **kwargs):
            self.calls.append(int(kwargs['params']['authuser']))
            return FakeReply(json.dumps({'QrtxK': '0'}), url='https://gemini.google.com/app')

        with self.assertRaises(self.WebError) as raised:
            await self._discover(handler)
        discovery = raised.exception.public()['details']['discovery']
        self.assertEqual(discovery['primary_reason'], 'missing_fields')
        self.assertGreaterEqual(discovery['reason_counts'].get('missing_fields', 0), 1)
        self.assertEqual(discovery['host_kind_counts'], {'gemini': 2})
        self._assert_clean(raised.exception.public())

    async def test_slot_mismatch_is_classified_when_page_slot_differs(self):
        async def handler(url, **kwargs):
            slot = int(kwargs['params']['authuser'])
            self.calls.append(slot)
            return FakeReply(gemini_page(slot, email='alice@example.test', qrtxk=3))

        with self.assertRaises(self.WebError) as raised:
            await self._discover(handler)
        discovery = raised.exception.public()['details']['discovery']
        self.assertEqual(discovery['primary_reason'], 'slot_mismatch')
        self.assertGreaterEqual(discovery['reason_counts'].get('slot_mismatch', 0), 1)
        self.assertNotIn('observed_slot', json.dumps(discovery))
        self._assert_clean(raised.exception.public())

    async def test_early_stop_is_reported_when_a_later_valid_slot_is_not_tried(self):
        async def handler(url, **kwargs):
            slot = int(kwargs['params']['authuser'])
            self.calls.append(slot)
            if slot >= 2:
                return FakeReply(gemini_page(slot, email=f'{slot}@example.test'))
            return FakeReply(json.dumps({}), url='https://gemini.google.com/app')

        with self.assertRaises(self.WebError) as raised:
            await self._discover(handler)
        discovery = raised.exception.public()['details']['discovery']
        self.assertTrue(discovery['stopped_early'])
        self.assertEqual(discovery['slots_tried'], 2)
        self.assertEqual(discovery['valid_count'], 0)
        self.assertEqual(self.calls, [0, 1])
        self.assertIn(discovery['primary_reason'], ('missing_fields', 'early_stop'))
        self._assert_clean(raised.exception.public())

    async def test_successful_discovery_still_returns_accounts_and_no_error_details_leak(self):
        async def handler(url, **kwargs):
            slot = int(kwargs['params']['authuser'])
            self.calls.append(slot)
            if slot < 2:
                return FakeReply(gemini_page(slot, email=f'{chr(97 + slot)}@example.test'))
            return FakeReply(json.dumps({}), url='https://gemini.google.com/app')

        found = await self._discover(handler)
        self.assertEqual([item['authuser'] for item in found], [0, 1])
        self.assertGreaterEqual(len(self.calls), 2)
        self._assert_clean(_public_text(self.WebError('ok', 200, 'ok')))
