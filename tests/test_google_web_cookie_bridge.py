"""Synthetic cookie domain/path/duplicate-name contracts. No live credentials."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HAS_WEB = importlib.util.find_spec('curl_cffi') is not None


class CookieBridgeTest(unittest.TestCase):
    def test_duplicate_name_on_other_host_does_not_replace_google_apex_session_cookie(self):
        from sidecars.google_web.store import normalize_cookies
        cookies = normalize_cookies([
            {'name': '__Secure-1PSID', 'value': 'apex-session', 'domain': '.google.com'},
            {'name': '__Secure-1PSID', 'value': 'other-host-session', 'domain': 'gemini.google.com'},
        ])
        self.assertEqual(cookies['__Secure-1PSID'], 'apex-session')

    def test_compass_prefers_gemini_host_when_names_collide(self):
        from sidecars.google_web.store import normalize_cookies
        cookies = normalize_cookies([
            {'name': '__Secure-1PSID', 'value': 'apex-session', 'domain': '.google.com'},
            {'name': 'COMPASS', 'value': 'gemini-compass', 'domain': 'gemini.google.com'},
            {'name': 'COMPASS', 'value': 'apex-compass', 'domain': '.google.com'},
        ])
        self.assertEqual(cookies['COMPASS'], 'gemini-compass')
        self.assertEqual(cookies['__Secure-1PSID'], 'apex-session')

    def test_cookie_source_stats_count_duplicate_names_by_domain_kind_without_values(self):
        from sidecars.google_web.store import cookie_source_stats
        stats = cookie_source_stats([
            {'name': '__Secure-1PSID', 'value': 'secret-a', 'domain': '.google.com'},
            {'name': '__Secure-1PSID', 'value': 'secret-b', 'domain': 'gemini.google.com'},
            {'name': 'COMPASS', 'value': 'secret-c', 'domain': 'gemini.google.com'},
        ])
        text = json.dumps(stats)
        self.assertNotIn('secret-a', text)
        self.assertNotIn('secret-b', text)
        self.assertNotIn('secret-c', text)
        self.assertEqual(stats['duplicate_names']['__Secure-1PSID']['google_apex'], 1)
        self.assertEqual(stats['duplicate_names']['__Secure-1PSID']['gemini_host'], 1)
        self.assertEqual(stats['kept_names'], 2)
        self.assertEqual(stats['input_rows'], 3)

    @unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
    def test_discovery_session_keeps_original_domains_on_the_cookie_jar(self):
        from curl_cffi.requests import Session
        from sidecars.google_web.accounts import apply_cookie_records
        session = Session()
        apply_cookie_records(session, [
            {'name': '__Secure-1PSID', 'value': 'apex-session', 'domain': '.google.com', 'path': '/'},
            {'name': 'COMPASS', 'value': 'gemini-compass', 'domain': 'gemini.google.com', 'path': '/'},
        ])
        by_name = {}
        for cookie in session.cookies.jar:
            by_name[cookie.name] = (str(cookie.domain), cookie.path or '/')
        self.assertEqual(by_name['__Secure-1PSID'][0].lstrip('.'), 'google.com')
        self.assertEqual(by_name['COMPASS'][0], 'gemini.google.com')


EXTRA_SESSION_RECORDS = [
    {'name': '__Secure-1PSID', 'value': 'apex-session', 'domain': '.google.com', 'path': '/'},
    {'name': 'COMPASS', 'value': 'gemini-compass', 'domain': 'gemini.google.com', 'path': '/'},
    {'name': '__Secure-1PAPISID', 'value': 'apex-papisid', 'domain': '.google.com', 'path': '/'},
    {'name': 'SIDCC', 'value': 'apex-sidcc', 'domain': '.google.com', 'path': '/'},
]

RECORDS = [
    {'name': '__Secure-1PSID', 'value': 'apex-session', 'domain': '.google.com', 'path': '/'},
    {'name': 'COMPASS', 'value': 'gemini-compass', 'domain': 'gemini.google.com', 'path': '/'},
]


class CookiePersistTest(unittest.TestCase):
    def setUp(self):
        from sidecars.google_web.store import WebStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WebStore(Path(self.temp.name) / 'web.db')

    def test_import_accounts_persists_cookie_records_and_public_list_redacts_them(self):
        imported = self.store.import_accounts([{
            'label': 'Chrome · Default',
            'email': 'a@example.test',
            'authuser': 2,
            'source_profile': 'Default',
            'cookies': {'__Secure-1PSID': 'apex-session', 'COMPASS': 'gemini-compass'},
            'cookie_records': RECORDS,
        }])
        private = self.store.get(imported[0]['id'])
        records = private.get('cookie_records') or []
        by_name = {item['name']: item for item in records}
        self.assertEqual(by_name['__Secure-1PSID']['domain'].lstrip('.'), 'google.com')
        self.assertEqual(by_name['COMPASS']['domain'], 'gemini.google.com')
        public = json.dumps(self.store.list_public())
        self.assertNotIn('apex-session', public)
        self.assertNotIn('gemini-compass', public)
        self.assertNotIn('cookie_records', public)

    def test_legacy_accounts_without_cookie_records_still_hydrate(self):
        imported = self.store.import_accounts([{'cookies': {'__Secure-1PSID': 'fixture-legacy'}}])
        private = self.store.get(imported[0]['id'])
        self.assertEqual(private['cookies']['__Secure-1PSID'], 'fixture-legacy')
        self.assertFalse(private.get('cookie_records'))


@unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
class DiscoverRecordReturnTest(unittest.IsolatedAsyncioTestCase):
    async def test_discover_returns_cookie_records_for_import(self):
        from types import SimpleNamespace
        from sidecars.google_web.accounts import discover_accounts
        from unittest.mock import patch
        class Reply:
            status_code = 200
            text = '{"SNlM0e":"fixture-token","QrtxK":"0","oPEP7c":"slot0@example.test"}'
            def raise_for_status(self):
                pass
        class Session:
            def __init__(self, *args, **kwargs):
                self.cookies = type('C', (), {})()
                self.cookies.jar = []
                def set(name, value, domain=None, path='/', **_):
                    self.cookies.jar.append(SimpleNamespace(
                        name=name, value=value, domain=domain, path=path or '/', is_expired=lambda: False))
                self.cookies.set = set
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, url, **kwargs):
                return Reply()
        settings = SimpleNamespace(proxy_url=None, timeout=20)
        with patch('curl_cffi.requests.AsyncSession', Session):
            found = await discover_accounts({
                'label': 'Chrome · Default',
                'source_profile': 'Default',
                'cookies': {'__Secure-1PSID': 'apex-session'},
                'cookie_records': RECORDS,
            }, settings)
        self.assertEqual(len(found), 1)
        by_name = {item['name']: item for item in found[0]['cookie_records']}
        self.assertEqual(by_name['COMPASS']['domain'], 'gemini.google.com')
        self.assertEqual(by_name['__Secure-1PSID']['domain'].lstrip('.'), 'google.com')


@unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
class PrepareCookieBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_bootstrap_applies_persisted_cookie_domains(self):
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.store import WebStore
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from curl_cffi.requests import AsyncSession

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = WebStore(Path(temp.name) / 'web.db')
        imported = store.import_accounts([{
            'label': 'Chrome · Default',
            'email': 'slot2@example.test',
            'authuser': 2,
            'source_profile': 'Default',
            'cookies': {'__Secure-1PSID': 'apex-session', 'COMPASS': 'gemini-compass'},
            'cookie_records': RECORDS,
        }])
        account = store.get(imported[0]['id'])
        upstream = GeminiWebUpstream(WebSettings(Path(temp.name) / 'unused.db'), store.persist_cookies)
        self.addAsyncCleanup(upstream.close)
        session = AsyncSession()
        seen = {}

        class Reply:
            text = '{"SNlM0e":"fixture-token","QrtxK":"2","oPEP7c":"slot2@example.test"}'
            status_code = 200
            url = 'https://gemini.google.com/app'

            def raise_for_status(self):
                pass

        async def get(url, **kwargs):
            for cookie in session.cookies.jar:
                seen[cookie.name] = str(cookie.domain)
            return Reply()

        session.get = get
        with patch('sidecars.google_web.vendor.gemini_webapi.utils.get_access_token.AsyncSession', return_value=session),                 patch.object(GeminiClient, '_init_rpc', new=AsyncMock()):
            identity = await upstream.prepare(account)
        self.assertEqual(identity.get('email'), 'slot2@example.test')
        self.assertEqual(seen.get('COMPASS'), 'gemini.google.com')
        self.assertEqual(seen.get('__Secure-1PSID', '').lstrip('.'), 'google.com')


@unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
class PrepareLoginWallClassificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_login_wall_is_auth_expired_not_account_changed(self):
        from types import SimpleNamespace
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient

        class Reply:
            text = '<!DOCTYPE html><html><body>{"SNlM0e":"fixture-token","QrtxK":"ignored"}</body></html>'
            status_code = 200
            url = 'https://accounts.google.com/v3/signin/identifier?continue=https://gemini.google.com/app'
            def raise_for_status(self):
                pass

        class Session:
            def __init__(self, *args, **kwargs):
                self.cookies = SimpleNamespace(jar=[], set=lambda *a, **k: None, update=lambda *a, **k: None)
            async def get(self, url, **kwargs):
                return Reply()
            async def close(self):
                return None

        upstream = GeminiWebUpstream(WebSettings(Path('unused-fixture.db')), lambda *_: None)
        self.addAsyncCleanup(upstream.close)
        with patch('sidecars.google_web.vendor.gemini_webapi.utils.get_access_token.AsyncSession', return_value=Session()), \
                patch.object(GeminiClient, '_init_rpc', new=AsyncMock()) as rpc:
            with self.assertRaises(WebError) as caught:
                await upstream.prepare({
                    'id': 'synthetic',
                    'revision': 1,
                    'cookies': {'__Secure-1PSID': 'apex-session'},
                    'authuser': 0,
                    'expected_email': 'slot0@example.test',
                })
        self.assertEqual(caught.exception.code, 'web_auth_expired')
        self.assertEqual(rpc.await_count, 0)


@unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
class DiscoverDoesNotPersistLoginWallCookiesTest(unittest.IsolatedAsyncioTestCase):
    async def test_discover_keeps_successful_session_cookies_if_later_slots_hit_a_login_wall(self):
        from types import SimpleNamespace
        from sidecars.google_web.accounts import discover_accounts

        class Reply:
            def __init__(self, slot):
                self.status_code = 200
                if slot < 2:
                    self.url = 'https://gemini.google.com/app'
                    self.text = '{"SNlM0e":"fixture-token","QrtxK":"%s","oPEP7c":"slot%s@example.test"}' % (slot, slot)
                else:
                    self.url = 'https://accounts.google.com/v3/signin/identifier'
                    self.text = '<!DOCTYPE html>{"SNlM0e":"login-page-token"}'
            def raise_for_status(self):
                pass

        class Session:
            def __init__(self, *args, **kwargs):
                self.cookies = type('C', (), {})()
                self.cookies.jar = []
                def set(name, value, domain=None, path='/', **_):
                    self.cookies.jar = [item for item in self.cookies.jar if not (item.name == name and item.domain == domain)]
                    self.cookies.jar.append(SimpleNamespace(
                        name=name, value=value, domain=domain, path=path or '/', is_expired=lambda: False))
                self.cookies.set = set
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, url, **kwargs):
                slot = int(kwargs['params']['authuser'])
                if slot >= 2:
                    self.cookies.set('__Secure-1PSID', 'login-wall-session', domain='.google.com', path='/')
                return Reply(slot)

        settings = SimpleNamespace(proxy_url=None, timeout=20)
        with patch('curl_cffi.requests.AsyncSession', Session):
            found = await discover_accounts({
                'label': 'Chrome · Default',
                'source_profile': 'Default',
                'cookies': {'__Secure-1PSID': 'apex-session'},
                'cookie_records': RECORDS,
            }, settings)
        self.assertEqual([item['authuser'] for item in found], [0, 1])
        by_name = {item['name']: item for item in found[0]['cookie_records'] if item['name'] == '__Secure-1PSID'}
        self.assertEqual(by_name['__Secure-1PSID']['value'], 'apex-session')


class SessionCookieAllowlistTest(unittest.TestCase):
    def test_import_accounts_persists_session_cookies_outside_the_legacy_name_allowlist(self):
        from sidecars.google_web.store import WebStore
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = WebStore(Path(temp.name) / 'web.db')
        imported = store.import_accounts([{
            'label': 'Chrome · Default',
            'email': 'a@example.test',
            'authuser': 0,
            'source_profile': 'Default',
            'cookies': {'__Secure-1PSID': 'apex-session', 'COMPASS': 'gemini-compass'},
            'cookie_records': EXTRA_SESSION_RECORDS,
        }])
        private = store.get(imported[0]['id'])
        names = {item['name'] for item in private.get('cookie_records') or []}
        self.assertIn('__Secure-1PAPISID', names)
        self.assertIn('SIDCC', names)
        public = json.dumps(store.list_public())
        self.assertNotIn('apex-papisid', public)
        self.assertNotIn('apex-sidcc', public)


@unittest.skipUnless(HAS_WEB, "Requires Web dependencies")
class DiscoverKeepsExtraSessionCookiesTest(unittest.IsolatedAsyncioTestCase):
    async def test_discover_snapshot_keeps_session_cookies_outside_the_legacy_name_allowlist(self):
        from types import SimpleNamespace
        from sidecars.google_web.accounts import discover_accounts

        class Reply:
            status_code = 200
            url = 'https://gemini.google.com/app'
            text = '{"SNlM0e":"fixture-token","QrtxK":"0","oPEP7c":"slot0@example.test"}'
            def raise_for_status(self):
                pass

        class Session:
            def __init__(self, *args, **kwargs):
                self.cookies = type('C', (), {})()
                self.cookies.jar = []
                def set(name, value, domain=None, path='/', **_):
                    self.cookies.jar.append(SimpleNamespace(
                        name=name, value=value, domain=domain, path=path or '/', is_expired=lambda: False))
                self.cookies.set = set
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def get(self, url, **kwargs):
                return Reply()

        settings = SimpleNamespace(proxy_url=None, timeout=20)
        with patch('curl_cffi.requests.AsyncSession', Session):
            found = await discover_accounts({
                'label': 'Chrome · Default',
                'source_profile': 'Default',
                'cookies': {'__Secure-1PSID': 'apex-session'},
                'cookie_records': EXTRA_SESSION_RECORDS,
            }, settings)
        self.assertEqual(len(found), 1)
        names = {item['name'] for item in found[0]['cookie_records']}
        self.assertIn('__Secure-1PAPISID', names)
        self.assertIn('SIDCC', names)
        self.assertEqual(
            {item['value'] for item in found[0]['cookie_records'] if item['name'] == '__Secure-1PAPISID'},
            {'apex-papisid'},
        )


class ImportPreviewTest(unittest.TestCase):
    def setUp(self):
        from sidecars.google_web.store import WebStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = WebStore(Path(self.temp.name) / 'web.db')

    def test_preview_import_reports_existing_session_without_writing(self):
        first = self.store.import_accounts([{
            'label': 'Chrome · Default',
            'email': 'a@example.test',
            'authuser': 0,
            'source_profile': 'Default',
            'cookies': {'__Secure-1PSID': 'apex-session'},
            'cookie_records': EXTRA_SESSION_RECORDS,
        }])
        before = {'accounts': len(self.store.list_public()),
                  'sessions': self._session_count()}
        preview = self.store.preview_import([{
            'email': 'a@example.test',
            'authuser': 0,
            'cookies': {'__Secure-1PSID': 'apex-session'},
            'cookie_records': EXTRA_SESSION_RECORDS,
        }])
        private = self.store.get(first[0]['id'])
        self.assertTrue(preview['fingerprint_matches_existing'])
        self.assertFalse(preview['would_create_new_session'])
        self.assertEqual(preview['matched_credential'], private['credential_id'][:8] + '…')
        self.assertEqual(self._session_count(), before['sessions'])
        self.assertEqual(len(self.store.list_public()), before['accounts'])
        self.assertIn('__Secure-1PAPISID', preview['snapshot_names'])
        self.assertNotIn('apex-session', json.dumps(preview))
        self.assertNotIn('apex-papisid', json.dumps(preview))

    def test_preview_import_flags_a_new_session_without_writing(self):
        self.store.import_accounts([{
            'cookies': {'__Secure-1PSID': 'apex-session'},
            'email': 'a@example.test',
            'authuser': 0,
        }])
        preview = self.store.preview_import([{
            'cookies': {'__Secure-1PSID': 'other-session'},
            'email': 'a@example.test',
            'authuser': 0,
        }])
        self.assertFalse(preview['fingerprint_matches_existing'])
        self.assertTrue(preview['would_create_new_session'])
        self.assertIsNone(preview['matched_credential'])
        self.assertEqual(self._session_count(), 1)
        self.assertEqual(len(self.store.list_public()), 1)
        self.assertNotIn('other-session', json.dumps(preview))

    def _session_count(self):
        with self.store.db() as db:
            return db.execute('SELECT COUNT(*) FROM web_credentials').fetchone()[0]
