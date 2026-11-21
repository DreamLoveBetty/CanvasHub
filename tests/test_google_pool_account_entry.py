"""Add-account vs quota refresh: import/OAuth stay local; catalog+summary need refresh().

Synthetic accounts and mocked upstream only. No live Google calls or tokens.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlencode, urlsplit

from sidecars.google_pool.config import GoogleSettings
from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.oauth import GoogleOAuth
from sidecars.google_pool.pool import GooglePool
from sidecars.google_pool.store import GoogleStore


CATALOG = {
    'gemini-3.1-flash-image': {
        'quotaInfo': {'remainingFraction': 0.7, 'resetTime': '2026-09-15T00:00:00Z'}
    }
}
GROUPS = {
    'groups': [
        {
            'displayName': 'Claude and GPT models',
            'buckets': [
                {
                    'bucketId': '3p-weekly',
                    'window': 'weekly',
                    'remainingFraction': 1.0,
                    'resetTime': '2026-11-27T13:59:32Z',
                    'displayName': 'Weekly Limit Remaining',
                }
            ],
        }
    ]
}


def settings(root: Path) -> GoogleSettings:
    return GoogleSettings(
        root / 'accounts.db', 'id', 'secret', 'http://localhost:18080/oauth-callback'
    )


class AccountEntryQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = settings(Path(self.temp.name))
        self.store = GoogleStore(self.settings.db_path)
        self.upstream = Mock()
        self.upstream.token.return_value = {
            'access_token': 'access-new',
            'refresh_token': 'refresh-new',
            'expires_in': 3600,
        }
        self.upstream.profile.return_value = {'email': 'fixture@example.test'}
        self.upstream.metadata.side_effect = (
            lambda token, method, payload, **kwargs: {'models': CATALOG}
            if method == 'fetchAvailableModels'
            else {'cloudaicompanionProject': {'id': 'fixture-project'}}
        )
        self.upstream.quota_summary.return_value = GROUPS
        self.pool = GooglePool(self.store, self.upstream)
        self.store.set_enabled(True)

    def test_json_import_does_not_fetch_catalog_or_quota(self):
        item = self.store.import_account(
            {'refresh_token': 'token-import', 'access_token': 'access-a', 'expires_in': 3600}
        )
        self.assertEqual(item['quota_groups_status'], 'missing')
        self.assertEqual(item.get('quota_groups') or [], [])
        self.assertFalse(item.get('models'))
        self.upstream.metadata.assert_not_called()
        self.upstream.quota_summary.assert_not_called()
        self.upstream.token.assert_not_called()

    def test_oauth_finish_saves_account_but_does_not_fetch_catalog_or_quota(self):
        oauth = GoogleOAuth(self.settings, self.store, self.upstream)
        started = oauth.start()
        query = parse_qs(urlsplit(started['authorize_url']).query)
        callback = self.settings.redirect_uri + '?' + urlencode(
            {'state': query['state'][0], 'code': 'fixture-code'}
        )
        result = oauth.finish(callback, started['session_id'])
        self.assertTrue(result['ok'])
        self.assertTrue(result['item']['refreshable'])
        self.assertEqual(result['item']['quota_groups_status'], 'missing')
        self.assertFalse(result['item'].get('models'))
        self.upstream.token.assert_called_once()
        self.upstream.metadata.assert_not_called()
        self.upstream.quota_summary.assert_not_called()

    def test_public_status_read_does_not_refresh_quota(self):
        self.store.import_account(
            {'refresh_token': 'token-status', 'access_token': 'access-a', 'expires_in': 3600}
        )
        self.upstream.reset_mock()
        public = self.store.list_public()
        self.assertEqual(public[0]['quota_groups_status'], 'missing')
        self.upstream.metadata.assert_not_called()
        self.upstream.quota_summary.assert_not_called()
        self.upstream.token.assert_not_called()

    def test_periodic_credentials_refresh_does_not_update_quota(self):
        item = self.store.import_account(
            {
                'refresh_token': 'token-watch',
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'project-a',
            }
        )
        self.pool.credentials(item['id'])
        stored = self.store.get(item['id'])
        self.assertEqual(stored.get('quota_groups_status') or 'missing', 'missing')
        self.assertFalse(stored.get('models'))
        self.upstream.quota_summary.assert_not_called()
        methods = [call.args[1] for call in self.upstream.metadata.call_args_list]
        self.assertNotIn('fetchAvailableModels', methods)

    def test_refresh_after_import_fills_catalog_and_quota_without_loadcodeassist(self):
        item = self.store.import_account(
            {
                'refresh_token': 'token-refresh',
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'aicode-consumers',
            }
        )
        self.upstream.reset_mock()
        public = self.pool.refresh(item['id'])
        self.assertEqual(public['quota_groups_status'], 'ok')
        self.assertEqual(public['quota_groups'][0]['buckets'][0]['bucket_id'], '3p-weekly')
        self.assertEqual({m['name'] for m in public['models']}, {'gemini-3.1-flash-image'})
        methods = [call.args[1] for call in self.upstream.metadata.call_args_list]
        self.assertEqual(methods, ['fetchAvailableModels'])
        self.assertEqual(self.upstream.metadata.call_args.args[2], {})
        self.upstream.quota_summary.assert_called_once()
        args, kwargs = self.upstream.quota_summary.call_args
        project = args[1] if len(args) > 1 else kwargs.get('project')
        self.assertFalse(project)

    def test_refresh_failure_after_import_keeps_the_account(self):
        item = self.store.import_account(
            {'refresh_token': 'token-fail', 'access_token': 'access-a', 'expires_in': 3600}
        )
        self.upstream.metadata.side_effect = GoogleError(
            '目录失败', 502, 'google_upstream_error'
        )
        with self.assertRaises(GoogleError):
            self.pool.refresh(item['id'])
        stored = self.store.get(item['id'])
        self.assertTrue(stored.get('refresh_token'))
        self.assertEqual(stored.get('quota_groups_status') or 'missing', 'missing')


@unittest.skipUnless(importlib.util.find_spec('fastapi') is not None, 'requires FastAPI')
class RuntimeActionEntryTests(unittest.TestCase):
    def setUp(self):
        from sidecars.google_pool.api import GoogleRuntime

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.settings = settings(Path(self.temp.name))
        self.store = GoogleStore(self.settings.db_path)
        self.upstream = Mock()
        self.upstream.token.return_value = {
            'access_token': 'access-new',
            'refresh_token': 'refresh-new',
            'expires_in': 3600,
        }
        self.upstream.metadata.side_effect = (
            lambda token, method, payload, **kwargs: {'models': CATALOG}
            if method == 'fetchAvailableModels'
            else {'cloudaicompanionProject': {'id': 'fixture-project'}}
        )
        self.upstream.quota_summary.return_value = GROUPS
        self.runtime = GoogleRuntime(self.settings, self.store, self.upstream)
        self.store.set_enabled(True)

    def test_accounts_import_action_does_not_call_upstream(self):
        result = self.runtime.action(
            'accounts-import',
            {'accounts': [{'refresh_token': 'token-import', 'access_token': 'access-a', 'expires_in': 3600}]},
        )
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['items'][0]['quota_groups_status'], 'missing')
        self.upstream.metadata.assert_not_called()
        self.upstream.quota_summary.assert_not_called()

    def test_account_refresh_action_uses_pool_refresh(self):
        imported = self.runtime.action(
            'accounts-import',
            {
                'accounts': [
                    {
                        'refresh_token': 'token-refresh',
                        'access_token': 'access-a',
                        'expires_in': 3600,
                        'project_id': 'aicode-consumers',
                    }
                ]
            },
        )
        account_id = imported['items'][0]['id']
        self.upstream.reset_mock()
        status = self.runtime.action('account-refresh', {'account_id': account_id})
        item = next(row for row in status['items'] if row['id'] == account_id)
        self.assertEqual(item['quota_groups_status'], 'ok')
        methods = [call.args[1] for call in self.upstream.metadata.call_args_list]
        self.assertEqual(methods, ['fetchAvailableModels'])
        self.upstream.quota_summary.assert_called_once()

    def test_models_refresh_skips_disabled_accounts(self):
        item = self.store.import_account(
            {'refresh_token': 'token-disabled', 'access_token': 'access-a', 'expires_in': 3600}
        )
        self.runtime.action('account-update', {'account_id': item['id'], 'enabled': False})
        self.upstream.reset_mock()
        result = self.runtime.action('models-refresh', {})
        self.assertEqual(result['refreshed'], 0)
        self.upstream.metadata.assert_not_called()
        self.upstream.quota_summary.assert_not_called()


if __name__ == '__main__':
    unittest.main()
