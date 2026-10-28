"""Same-Profile Google accounts; synthetic sessions only, no network or credentials."""
import asyncio
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import AsyncMock, patch

COOKIES = {'__Secure-1PSID': 'fixture-shared-session', '__Secure-1PSIDTS': 'fixture-old-ts'}
HAS_WEB = all(importlib.util.find_spec(n) for n in ('curl_cffi', 'orjson', 'pydantic'))


def accounts(order=('a', 'b', 'c', 'd')):
    return [{'cookies': COOKIES, 'authuser': i, 'email': name+'@example.test',
             'display_name': 'Synthetic '+name, 'label': 'Chrome · Default', 'source_profile': 'Default'}
            for i, name in enumerate(order)]


class MultiAccountStoreTest(unittest.TestCase):
    def setUp(self):
        from sidecars.google_web.store import WebStore
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'web.db'
        self.store = WebStore(self.path)

    def test_same_cookie_session_contains_four_distinct_idempotent_accounts(self):
        self.store.import_accounts(accounts())
        first = self.store.list_public()
        self.assertEqual(len(first), 4)
        self.assertEqual(len(set(a['id'] for a in first)), 4)
        self.store.import_accounts(accounts())
        self.assertEqual([a['id'] for a in self.store.list_public()], [a['id'] for a in first])
        self.assertNotIn('fixture-shared-session', json.dumps(first))
        self.assertEqual([a.get('authuser') for a in first], [0, 1, 2, 3])

    def test_reordering_google_slots_preserves_email_identity_and_counters(self):
        first = self.store.import_accounts(accounts())
        self.store.patch(first[0]['id'], {'success_count': 7})
        self.store.import_accounts(accounts(('d', 'c', 'b', 'a')))
        public = self.store.list_public()
        self.assertEqual(len(public), 4)
        by_email = {a.get('email'): a for a in public}
        self.assertEqual(by_email['a@example.test']['id'], first[0]['id'])
        self.assertEqual(by_email['a@example.test']['success_count'], 7)
        self.assertEqual(by_email['a@example.test']['authuser'], 3)

    def test_shared_cookie_rotation_and_account_deletion_have_one_storage_owner(self):
        imported = self.store.import_accounts(accounts())
        self.assertEqual(len(self.store.list_public()), 4)
        self.store.persist_cookies(imported[0]['id'], {'__Secure-1PSIDTS': 'fixture-rotated'})
        for account in imported:
            self.assertEqual(self.store.get(account['id'])['cookies']['__Secure-1PSIDTS'], 'fixture-rotated')
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM web_credentials').fetchone()[0], 1)
            self.assertTrue(all('cookies' not in json.loads(r[0]) for r in db.execute('SELECT data FROM web_accounts')))
        self.store.delete(imported[0]['id'])
        self.store.persist_cookies(imported[0]['id'], COOKIES)
        self.assertEqual(len(self.store.list_public()), 3)
        self.assertEqual(self.store.get(imported[1]['id'])['cookies']['__Secure-1PSIDTS'], 'fixture-rotated')
        for account in imported[1:]: self.store.delete(account['id'])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM web_credentials').fetchone()[0], 0)

    def test_legacy_database_migrates_without_replacing_task_account_id(self):
        legacy = dict(id='legacy-id', label='Chrome · Default', cookies=COOKIES, revision=3,
                      enabled=False, checked_at=123, success_count=9, email='a@example.test')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO web_accounts VALUES (?,?,?)', ('legacy-id', hashlib.sha256(COOKIES['__Secure-1PSID'].encode()).hexdigest(), json.dumps(legacy)))
        from sidecars.google_web.store import WebStore
        migrated = WebStore(self.path)
        self.assertEqual(migrated.get('legacy-id')['cookies'], COOKIES)
        migrated.import_accounts(accounts())
        by_email = {a.get('email'):a for a in migrated.list_public()}
        self.assertIn('a@example.test', by_email)
        a = by_email['a@example.test']
        self.assertEqual(a['id'], 'legacy-id')
        self.assertEqual(a['success_count'], 9)
        self.assertFalse(a['enabled'])

    def test_invalid_selector_does_not_partially_import_accounts(self):
        from sidecars.google_web.errors import WebError
        for value in (True, -1, 1.2, 'other@example.test', 100):
            with self.subTest(value=value):
                with self.assertRaises(WebError): self.store.import_accounts([accounts()[0], dict(accounts()[1], authuser=value)])
                self.assertEqual(self.store.list_public(), [])

    def test_account_status_patch_cannot_create_a_second_cookie_owner(self):
        from sidecars.google_web.errors import WebError
        account=self.store.import_accounts([accounts()[0]])[0]
        with self.assertRaises(WebError):self.store.patch(account['id'],{'cookies':COOKIES})

    def test_late_refresh_cannot_overwrite_a_reimported_shared_session(self):
        account=self.store.import_accounts([accounts()[0]])[0]
        revision=self.store.get(account['id'])['revision']
        fresh=dict(accounts()[0],cookies=dict(COOKIES,**{'__Secure-1PSIDTS':'fixture-fresh-import'}))
        self.store.import_accounts([fresh])
        try:
            self.store.persist_cookies(account['id'],{'__Secure-1PSIDTS':'fixture-old-refresh'},revision)
        except TypeError:self.fail('Refresh must include the session revision')
        self.assertEqual(self.store.get(account['id'])['cookies']['__Secure-1PSIDTS'],'fixture-fresh-import')

    def test_expansion_keeps_account_ids_when_google_rotates_the_session_cookie(self):
        first=self.store.import_accounts(accounts())
        group=self.store.get(first[0]['id'])['credential_id']
        rotated=[dict(a,cookies=dict(COOKIES,**{'__Secure-1PSID':'fixture-new-session-cookie'})) for a in accounts()]
        try:self.store.import_accounts(rotated,source_credential_id=group)
        except TypeError:self.fail('Explicit stored-session expansion must preserve its credential owner')
        self.assertEqual([a['id'] for a in self.store.list_public()],[a['id'] for a in first])
        self.assertEqual(self.store.get(first[0]['id'])['cookies']['__Secure-1PSID'],'fixture-new-session-cookie')


class MultiAccountRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_expansion_uses_saved_session_not_browser_and_preserves_existing_account(self):
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        from tests.test_google_web import FakeUpstream
        upstream = FakeUpstream()
        async def discover(item):
            self.assertEqual(item['cookies'], COOKIES)
            return accounts()
        upstream.discover_accounts = discover
        with tempfile.TemporaryDirectory() as temp:
            runtime = WebRuntime(WebSettings(Path(temp)/'web.db'), upstream=upstream)
            self.addAsyncCleanup(runtime.close)
            original = runtime.store.import_accounts([accounts()[0]])[0]
            runtime.store.patch(original['id'], {'success_count': 4})
            try:
                with patch('sidecars.google_web.browser.import_profile', side_effect=AssertionError('Browser must not be read')):
                    result = await runtime.action('account-expand', {'account_id': original['id']})
            except Exception as error:
                self.fail('Stored-session expansion failed: '+type(error).__name__)
            self.assertEqual(result['imported'], 4)
            self.assertEqual(len(result['items']), 4)
            self.assertEqual(next(a for a in result['items'] if a['id']==original['id'])['success_count'], 4)

    async def test_first_successful_login_pins_a_legacy_unlabelled_identity(self):
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        from tests.test_google_web import FakeUpstream
        upstream=FakeUpstream()
        async def prepare(_):return {'email':'a@example.test','display_name':'Synthetic A'}
        upstream.prepare=prepare
        with tempfile.TemporaryDirectory() as temp:
            runtime=WebRuntime(WebSettings(Path(temp)/'web.db'),upstream=upstream)
            self.addAsyncCleanup(runtime.close)
            item=runtime.store.import_accounts([{'cookies':COOKIES}])[0]
            await runtime.pool.check(item['id'])
            self.assertEqual(runtime.store.get(item['id']).get('expected_email'),'a@example.test')

    async def test_four_accounts_in_one_session_rotate_without_post_submission_failover(self):
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from tests.test_google_web import FakeUpstream, BODY
        upstream=FakeUpstream(); selected=[]
        async def prepare(account):
            selected.append(account['authuser'])
            return {'email':account['expected_email'],'display_name':'Synthetic'}
        upstream.prepare=prepare
        with tempfile.TemporaryDirectory() as temp:
            runtime=WebRuntime(WebSettings(Path(temp)/'web.db'),upstream=upstream)
            self.addAsyncCleanup(runtime.close)
            runtime.store.import_accounts(accounts());runtime.store.set_enabled(True)
            for _ in range(5):await runtime.pool.generate('gemini-3-pro-image',BODY)
            self.assertEqual(selected,[0,1,2,3,0])
            upstream.fail_generate=True
            with self.assertRaises(WebError):await runtime.pool.generate('gemini-3-pro-image',BODY)
            self.assertEqual(selected,[0,1,2,3,0,1])
            self.assertEqual(len(upstream.submitted),6)
            self.assertEqual(runtime.pool.inflight,set())

    async def test_discovery_maintenance_prevents_generation_and_delete_until_finished(self):
        from sidecars.google_web.runtime import WebRuntime
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from tests.test_google_web import FakeUpstream,BODY
        started,finish=asyncio.Event(),asyncio.Event();upstream=FakeUpstream()
        async def discover(_):started.set();await finish.wait();return accounts()
        upstream.discover_accounts=discover
        with tempfile.TemporaryDirectory() as temp:
            runtime=WebRuntime(WebSettings(Path(temp)/'web.db'),upstream=upstream)
            self.addAsyncCleanup(runtime.close)
            original=runtime.store.import_accounts([accounts()[0]])[0];runtime.store.set_enabled(True)
            task=asyncio.create_task(runtime.action('account-expand',{'account_id':original['id']}))
            await started.wait()
            try:
                with self.assertRaises(WebError):await runtime.pool.generate('gemini-3-pro-image',BODY)
                with self.assertRaises(WebError):await runtime.action('account-delete',{'account_id':original['id']})
            finally:
                finish.set();await task
            self.assertFalse(runtime.pool.maintenance)
            self.assertEqual(upstream.submitted,[])


@unittest.skipUnless(HAS_WEB, 'Requires Web dependencies')
class MultiAccountVendorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from curl_cffi.requests import AsyncSession
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        self.http = AsyncSession(); self.addAsyncCleanup(self.close_http)
        self.client = GeminiClient(secure_1psid='fixture-shared-session', authuser=2)
        self.client.client = self.http; self.client._running=True
        self.client.push_id = 'fixture-push'
        self.calls = []

    async def close_http(self):
        if self.client.client and self.client.client._closed: self.client.client=None
        await self.client.close()
        if not self.http._closed: await self.http.close()

    async def test_generation_and_original_rpc_select_the_same_account(self):
        from sidecars.google_web.vendor.gemini_webapi.constants import Model
        from sidecars.google_web.vendor.gemini_webapi.exceptions import APIError
        class Response:
            status_code=500
        class Stream:
            async def __aenter__(self):return Response()
            async def __aexit__(self,*_):pass
        def stream(method,url,**kwargs):
            self.calls.append((str(url),kwargs));return Stream()
        self.http.stream=stream
        with self.assertRaises(APIError):
            async for _ in self.client._generate('synthetic', model=Model.UNSPECIFIED, pro_image=True):pass
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0][1].get('params',{}).get('authuser'),2)
        # _generate closed the session after HTTP 500; restore without reinitializing.
        from curl_cffi.requests import AsyncSession
        self.http=AsyncSession(); self.client.client=self.http; self.client._running=True
        class RPCResponse:
            status_code=200; text=')]}\'\n[["wrb.fr","c8o8Fe","[\\"https://lh3.googleusercontent.com/original\\"]"]]'
        async def post(url,**kwargs):self.calls.append((str(url),kwargs));return RPCResponse()
        self.http.post=post
        await self.client._get_full_size_image('c','r','rc','image')
        self.assertEqual(self.calls[-1][1].get('params',{}).get('authuser'),2)

    async def test_reference_upload_selects_the_account_not_the_default(self):
        from sidecars.google_web.vendor.gemini_webapi.exceptions import APIError
        class Reply:
            status_code=200; text='synthetic-upload-id'
            def raise_for_status(self):pass
        async def post(url,**kwargs):self.calls.append((str(url),kwargs));return Reply()
        self.http.post=post
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        with patch.object(GeminiClient,'_send_bard_activity',new=AsyncMock()), \
                patch.object(GeminiClient,'_generate',side_effect=APIError('fixture stop after upload')):
            with self.assertRaises(APIError):
                await self.client.generate_content('synthetic',files=[io.BytesIO(b'fixture')])
        self.assertEqual(self.calls[0][1].get('params',{}).get('authuser'),2)

    async def test_login_bootstrap_selects_the_requested_account(self):
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        class Reply:
            text='{"SNlM0e":"fixture-token"}';status_code=200
            def raise_for_status(self):pass
        async def get(url,**kwargs):self.calls.append((str(url),kwargs));return Reply()
        self.http.get=get;self.client._running=False
        with patch('sidecars.google_web.vendor.gemini_webapi.utils.get_access_token.AsyncSession',return_value=self.http), \
                patch.object(GeminiClient,'_init_rpc',new=AsyncMock()):
            await self.client.init(auto_refresh=False)
        self.assertEqual(self.calls[0][1].get('params',{}).get('authuser'),2)

    async def test_readonly_discovery_returns_four_identities_not_duplicate_default(self):
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.config import WebSettings
        upstream=GeminiWebUpstream(WebSettings(Path('unused-fixture.db')),lambda *_:None)
        discover=getattr(upstream,'discover_accounts',None)
        self.assertTrue(callable(discover),'Web account discovery is missing')
        class Reply:
            status_code=200
            def __init__(self,slot):
                selected=slot if slot<4 else 0
                self.text=json.dumps({'SNlM0e':'fixture-token','QrtxK':str(selected),'oPEP7c':chr(97+selected)+'@example.test'})
            def raise_for_status(self):pass
        async def get(url,**kwargs):
            self.calls.append((str(url),kwargs));return Reply(int(kwargs['params']['authuser']))
        self.http.get=get
        with patch('curl_cffi.requests.AsyncSession',return_value=self.http):
            found=await discover({'label':'Chrome · Default','cookies':COOKIES,'source_profile':'Default'})
        self.assertEqual([(a['authuser'],a['email']) for a in found],[(0,'a@example.test'),(1,'b@example.test'),(2,'c@example.test'),(3,'d@example.test')])
        self.assertTrue(all(url=='https://gemini.google.com/app' for url,_ in self.calls))
        self.assertLessEqual(len(self.calls),20)

    async def test_reordered_slot_is_rejected_before_initialization_rpc_or_generation(self):
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        upstream=GeminiWebUpstream(WebSettings(Path('unused-fixture.db')),lambda *_:None)
        self.addAsyncCleanup(upstream.close)
        class Reply:
            text='{"SNlM0e":"fixture-token","QrtxK":"2","oPEP7c":"wrong@example.test"}';status_code=200
            def raise_for_status(self):pass
        self.http.get=AsyncMock(return_value=Reply())
        with patch('sidecars.google_web.vendor.gemini_webapi.utils.get_access_token.AsyncSession',return_value=self.http), \
                patch.object(GeminiClient,'_init_rpc',new=AsyncMock()) as rpc:
            with self.assertRaises(WebError) as caught:
                await upstream.prepare({'id':'synthetic','revision':1,'cookies':COOKIES,'authuser':2,'expected_email':'right@example.test'})
        self.assertEqual(caught.exception.code,'web_account_changed')
        self.assertEqual(rpc.await_count,0)

    async def test_cookie_refresh_has_one_owner_and_propagates_to_other_account_clients(self):
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.config import WebSettings
        from sidecars.google_web.store import WebStore
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from curl_cffi.requests import AsyncSession
        with tempfile.TemporaryDirectory() as temp:
            store=WebStore(Path(temp)/'web.db');rows=store.import_accounts(accounts()[:2])
            upstream=GeminiWebUpstream(WebSettings(Path(temp)/'web.db'),store.persist_cookies)
            self.addAsyncCleanup(upstream.close)
            for row in rows:
                private=store.get(row['id']);client=GeminiClient(secure_1psid=COOKIES['__Secure-1PSID'])
                client.client=AsyncSession();client.cookies=COOKIES;client._running=True
                upstream.sessions[row['id']]={'client':client,'credential_id':private['credential_id'],
                    'cookie_snapshot':dict(COOKIES),'revision':1}
            async def rotate(http,*_):
                http.cookies.set('__Secure-1PSIDTS','fixture-rotated',domain='.google.com')
                return 'fixture-rotated'
            with patch('sidecars.google_web.vendor.gemini_webapi.utils.rotate_1psidts.rotate_1psidts',new=AsyncMock(side_effect=rotate)) as refresh, \
                    patch('sidecars.google_web.upstream.asyncio.sleep',new=AsyncMock(side_effect=[None,asyncio.CancelledError()])):
                with self.assertRaises(asyncio.CancelledError):await upstream._persist_refreshed()
            self.assertEqual(refresh.await_count,1)
            other=upstream.sessions[rows[1]['id']]['client']
            self.assertEqual(other.cookies.get('__Secure-1PSIDTS'),'fixture-rotated')
            upstream.flush(rows[1]['id'],other)
            self.assertEqual(store.get(rows[0]['id'])['cookies']['__Secure-1PSIDTS'],'fixture-rotated')


if __name__=='__main__': unittest.main()
