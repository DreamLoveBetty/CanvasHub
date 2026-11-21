"""Grouped quota summary: allowlisted persist, public pass-through, best-effort refresh.

Synthetic accounts and mocked upstream only. No live Google calls or tokens.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

from sidecars.google_pool.config import GoogleSettings
from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.pool import GooglePool
from sidecars.google_pool.quota_groups import normalize_quota_summary
from sidecars.google_pool.store import GoogleStore
from sidecars.google_pool.upstream import GoogleUpstream


CATALOG = {
    'gemini-3.1-flash-image': {'quotaInfo': {'remainingFraction': 0.7, 'resetTime': '2026-09-15T00:00:00Z'}},
    'claude-sonnet-4-6': {'quotaInfo': {'remainingFraction': 1}},
}

CLAUDE_GROUPS = {
    'description': 'Quota remaining',
    'groups': [
        {
            'displayName': 'Claude and GPT models',
            'description': 'Models within this group: Claude Sonnet 4.6, GPT-OSS 120B',
            'buckets': [
                {
                    'bucketId': '3p-weekly',
                    'window': 'weekly',
                    'remainingFraction': 1.0,
                    'resetTime': '2026-11-27T13:59:32Z',
                    'displayName': 'Weekly Limit Remaining',
                },
                {
                    'bucketId': '3p-5h',
                    'window': '5h',
                    'remainingFraction': 1.0,
                    'resetTime': '2026-11-20T18:59:32Z',
                    'displayName': 'Five Hour Limit Remaining',
                },
            ],
        }
    ],
}


def settings(root: Path) -> GoogleSettings:
    return GoogleSettings(root / 'accounts.db', 'id', 'secret', 'http://localhost/cb')


class NormalizeQuotaSummaryTests(unittest.TestCase):
    def test_keeps_allowlisted_fields_and_unknown_windows(self):
        value = normalize_quota_summary(
            {
                'groups': [
                    {
                        'displayName': 'Custom Family',
                        'description': 'shown',
                        'buckets': [
                            {
                                'bucketId': 'family-daily',
                                'window': 'daily',
                                'remainingFraction': 0.4,
                                'resetTime': '2026-11-21T00:00:00Z',
                                'displayName': 'Daily',
                                'description': 'honest unknown window',
                            }
                        ],
                    }
                ],
                'access_token': 'should-not-leak',
                'project_id': 'proj-secret',
                'email': 'user@example.test',
            }
        )
        self.assertEqual(value['groups'][0]['display_name'], 'Custom Family')
        self.assertEqual(value['groups'][0]['buckets'][0]['window'], 'daily')
        self.assertEqual(value['groups'][0]['buckets'][0]['remaining_fraction'], 0.4)
        self.assertEqual(value['groups'][0]['buckets'][0]['percentage'], 40)
        self.assertNotIn('access_token', value)
        self.assertNotIn('project_id', value)
        self.assertNotIn('email', value)
        blob = str(value)
        self.assertNotIn('should-not-leak', blob)
        self.assertNotIn('proj-secret', blob)
        self.assertNotIn('user@example.test', blob)

    def test_rejects_url_and_secret_pollution_and_caps_lists(self):
        groups = [
            {
                'displayName': 'https://evil.example/steal',
                'description': 'Bearer aaa.bbb',
                'buckets': [
                    {
                        'bucketId': 'ok-id',
                        'window': '5h',
                        'remainingFraction': 0.2,
                        'resetTime': 'https://evil.example/reset',
                        'displayName': 'token-eyJhbGciOi.aaa.bbb',
                    }
                ],
            }
        ] + [
            {
                'displayName': f'Group {i}',
                'buckets': [{'bucketId': f'b{j}', 'window': '5h', 'remainingFraction': 0.1} for j in range(20)],
            }
            for i in range(20)
        ]
        value = normalize_quota_summary({'groups': groups})
        self.assertLessEqual(len(value['groups']), 16)
        first = value['groups'][0]
        self.assertFalse(first.get('display_name'))
        self.assertFalse(first.get('description'))
        bucket = first['buckets'][0]
        self.assertEqual(bucket['bucket_id'], 'ok-id')
        self.assertIsNone(bucket.get('reset_time') or None)
        self.assertFalse(bucket.get('display_name'))
        self.assertLessEqual(len(value['groups'][1]['buckets']), 16)
        self.assertNotIn('https://', str(value))
        self.assertNotIn('Bearer', str(value))

    def test_invalid_percentages_are_not_coerced_to_a_full_bar(self):
        value = normalize_quota_summary(
            {
                'groups': [
                    {
                        'displayName': 'X',
                        'buckets': [
                            {'bucketId': 'a', 'window': '5h', 'remainingFraction': 0},
                            {'bucketId': 'b', 'window': '5h', 'remainingFraction': None},
                            {'bucketId': 'c', 'window': '5h', 'remainingFraction': 1.5},
                            {'bucketId': 'd', 'window': '5h', 'remainingFraction': -0.2},
                            {'bucketId': 'e', 'window': '5h'},
                        ],
                    }
                ]
            }
        )
        buckets = value['groups'][0]['buckets']
        self.assertEqual(buckets[0]['remaining_fraction'], 0.0)
        self.assertEqual(buckets[0]['percentage'], 0)
        for index in (1, 2, 3, 4):
            self.assertIsNone(buckets[index]['remaining_fraction'])
            self.assertIsNone(buckets[index]['percentage'])

    def test_rejects_non_objects_and_does_not_treat_missing_groups_as_zero(self):
        self.assertIsNone(normalize_quota_summary(None))
        self.assertIsNone(normalize_quota_summary('groups'))
        self.assertIsNone(normalize_quota_summary({'groups': 'nope'}))
        empty = normalize_quota_summary({'groups': []})
        self.assertEqual(empty['groups'], [])


class QuotaSummaryRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GoogleStore(settings(Path(self.temp.name)).db_path)
        self.upstream = Mock()
        self.upstream.metadata.return_value = {'models': CATALOG}
        self.upstream.quota_summary.return_value = CLAUDE_GROUPS
        self.pool = GooglePool(self.store, self.upstream)
        self.store.set_enabled(True)

    def account(self, key='token-a'):
        return self.store.import_account(
            {
                'refresh_token': key,
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'project-a',
            }
        )['id']

    def test_refresh_stores_normalized_groups_and_public_omits_secrets(self):
        account_id = self.account()
        public = self.pool.refresh(account_id)
        self.upstream.quota_summary.assert_called_once()
        args, kwargs = self.upstream.quota_summary.call_args
        self.assertEqual(args[0], 'access-a')
        # project is passed for the body, but must not appear in public output
        self.assertIn('project-a', args + tuple(kwargs.values()))
        self.assertEqual(public['quota_groups_status'], 'ok')
        self.assertIsInstance(public['quota_groups_updated_at'], int)
        self.assertGreater(public['quota_groups_updated_at'], 0)
        groups = public['quota_groups']
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['display_name'], 'Claude and GPT models')
        self.assertEqual([b['window'] for b in groups[0]['buckets']], ['weekly', '5h'])
        self.assertEqual([b['bucket_id'] for b in groups[0]['buckets']], ['3p-weekly', '3p-5h'])
        self.assertNotIn('project_id', public)
        self.assertNotIn('access_token', public)
        self.assertNotIn('refresh_token', public)
        stored = self.store.get(account_id)
        self.assertNotIn('https://', str(stored.get('quota_groups')))
        # catalog still refreshed
        self.assertEqual({m['name'] for m in public['models']}, {'gemini-3.1-flash-image', 'claude-sonnet-4-6'})

    def test_summary_failure_keeps_old_cache_and_does_not_fail_catalog(self):
        account_id = self.account()
        first = self.pool.refresh(account_id)
        updated = first['quota_groups_updated_at']
        self.upstream.metadata.return_value = {
            'models': {
                'gemini-3.1-flash-image': {'quotaInfo': {'remainingFraction': 0.2}},
            }
        }
        self.upstream.quota_summary.side_effect = GoogleError('分组额度失败', 502, 'google_upstream_error')
        time.sleep(1)
        second = self.pool.refresh(account_id)
        self.assertEqual(second['models'][0]['percentage'], 20)
        self.assertEqual(second['quota_groups'], first['quota_groups'])
        self.assertEqual(second['quota_groups_updated_at'], updated)
        self.assertEqual(second['quota_groups_status'], 'stale')
        self.assertGreater(second['quota_groups_last_attempt_at'], updated)
        # last_error stays clear after a successful catalog refresh
        self.assertFalse(second.get('last_error'))

    def test_first_summary_failure_is_missing_not_a_zero_bar(self):
        self.upstream.quota_summary.side_effect = GoogleError('fail', 503, 'google_upstream_error')
        public = self.pool.refresh(self.account())
        self.assertEqual(public['quota_groups_status'], 'error')
        self.assertEqual(public.get('quota_groups') or [], [])
        self.assertFalse(public.get('quota_groups_updated_at'))
        self.assertTrue(public['models'])

    def test_summary_is_not_used_when_catalog_fails_and_does_not_call_generate(self):
        account_id = self.account()
        self.upstream.metadata.side_effect = GoogleError('目录失败', 502, 'google_upstream_error')
        with self.assertRaises(GoogleError):
            self.pool.refresh(account_id)
        self.upstream.quota_summary.assert_not_called()
        self.upstream.generate.assert_not_called()

    def test_import_preserves_cached_groups(self):
        account_id = self.account()
        self.pool.refresh(account_id)
        cached = self.store.get(account_id)['quota_groups']
        # Re-import same refresh token (stable identity)
        self.store.import_account(
            {
                'refresh_token': 'token-a',
                'access_token': 'access-b',
                'expires_in': 3600,
                'project_id': 'project-a',
            }
        )
        again = self.store.get(account_id)
        self.assertEqual(again['quota_groups'], cached)
        self.assertEqual(again['quota_groups_status'], 'ok')


    def test_empty_summary_after_cache_keeps_old_groups_and_marks_stale_empty(self):
        account_id = self.account()
        first = self.pool.refresh(account_id)
        updated = first['quota_groups_updated_at']
        self.upstream.quota_summary.return_value = {'groups': []}
        time.sleep(1)
        second = self.pool.refresh(account_id)
        self.assertEqual(second['quota_groups'], first['quota_groups'])
        self.assertEqual(second['quota_groups_updated_at'], updated)
        self.assertEqual(second['quota_groups_status'], 'stale_empty')
        self.assertGreater(second['quota_groups_last_attempt_at'], updated)
        self.assertTrue(second['models'])

    def test_empty_buckets_after_cache_keeps_old_groups(self):
        account_id = self.account()
        first = self.pool.refresh(account_id)
        updated = first['quota_groups_updated_at']
        self.upstream.quota_summary.return_value = {
            'groups': [{'displayName': 'Empty', 'buckets': []}]
        }
        time.sleep(1)
        second = self.pool.refresh(account_id)
        self.assertEqual(second['quota_groups'], first['quota_groups'])
        self.assertEqual(second['quota_groups_updated_at'], updated)
        self.assertEqual(second['quota_groups_status'], 'stale_empty')

    def test_first_empty_summary_is_empty_not_a_zero_bar(self):
        self.upstream.quota_summary.return_value = {'groups': []}
        public = self.pool.refresh(self.account())
        self.assertEqual(public['quota_groups_status'], 'empty')
        self.assertEqual(public.get('quota_groups') or [], [])
        self.assertTrue(public.get('quota_groups_updated_at'))
        self.assertTrue(public['models'])

    def test_status_reads_cached_groups_without_calling_upstream(self):
        account_id = self.account()
        self.pool.refresh(account_id)
        self.upstream.quota_summary.reset_mock()
        self.upstream.metadata.reset_mock()
        public = self.store.list_public()
        self.upstream.quota_summary.assert_not_called()
        self.upstream.metadata.assert_not_called()
        self.assertTrue(public[0]['quota_groups'])
        self.assertEqual(public[0]['quota_groups_status'], 'ok')




OFFICIAL_DAILY = 'https://daily-cloudcode-pa.googleapis.com/v1internal'
OFFICIAL_PROD = 'https://cloudcode-pa.googleapis.com/v1internal'
CONFIGURED_UPSTREAM = 'https://configured.example/v1internal'


def recording_session(calls, payload=CLAUDE_GROUPS):
    class RecordingSession:
        def __init__(self):
            self.proxies = {}
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None, timeout=None, allow_redirects=None, stream=None):
            safe_headers = {}
            for key, value in (headers or {}).items():
                name = str(key)
                if name.lower() == 'authorization':
                    safe_headers[name] = 'present' if value else 'missing'
                else:
                    safe_headers[name] = value
            calls.append({'url': url, 'json': json, 'headers': safe_headers})

            class Response:
                status_code = 200

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def json(self):
                    return payload

                def iter_content(self, chunk_size=None):
                    return iter(())

            return Response()

    return RecordingSession


class QuotaQueryHostAndProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.settings = GoogleSettings(
            Path(self.temp.name) / 'direct.db',
            'id',
            'secret',
            'http://localhost/cb',
            upstream=CONFIGURED_UPSTREAM,
        )
        self.upstream = GoogleUpstream(
            self.settings, session_factory=recording_session(self.calls)
        )

    def test_placeholder_and_blank_projects_are_omitted_from_quota_payload(self):
        from sidecars.google_pool.upstream import quota_request_payload

        self.assertEqual(quota_request_payload('project-a'), {'project': 'project-a'})
        self.assertEqual(quota_request_payload('  real-project  '), {'project': 'real-project'})
        self.assertEqual(quota_request_payload('aicode-consumers'), {})
        self.assertEqual(quota_request_payload('  aicode-consumers  '), {})
        self.assertEqual(quota_request_payload(''), {})
        self.assertEqual(quota_request_payload('   '), {})
        self.assertEqual(quota_request_payload(None), {})
        self.assertEqual(quota_request_payload({'id': 'project-a'}), {})

    def test_quota_summary_uses_official_daily_not_generation_host(self):
        result = self.upstream.quota_summary('access-a', 'project-a')
        self.assertEqual(result['groups'][0]['displayName'], 'Claude and GPT models')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.calls[0]['url'],
            OFFICIAL_DAILY + ':retrieveUserQuotaSummary',
        )
        self.assertEqual(self.calls[0]['json'], {'project': 'project-a'})
        self.assertNotIn('configured.example', self.calls[0]['url'])

    def test_quota_summary_and_catalog_share_quota_host_and_omit_placeholder(self):
        self.upstream.quota_summary('access-a', 'aicode-consumers')
        self.upstream.metadata('access-a', 'fetchAvailableModels', {'project': 'aicode-consumers'})
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]['url'], OFFICIAL_DAILY + ':retrieveUserQuotaSummary')
        self.assertEqual(self.calls[1]['url'], OFFICIAL_DAILY + ':fetchAvailableModels')
        self.assertEqual(self.calls[0]['json'], {})
        self.assertEqual(self.calls[1]['json'], {})

    def test_missing_project_still_posts_empty_body_on_official_daily(self):
        self.upstream.quota_summary('access-a', None)
        self.upstream.metadata('access-a', 'fetchAvailableModels', {})
        self.assertEqual(self.calls[0]['json'], {})
        self.assertEqual(self.calls[1]['json'], {})
        self.assertTrue(all(c['url'].startswith(OFFICIAL_DAILY + ':') for c in self.calls))

    def test_loadcodeassist_and_generate_stay_on_configured_generation_host(self):
        self.upstream.metadata('access-a', 'loadCodeAssist', {'metadata': {'ideType': 'ANTIGRAVITY'}})
        with self.assertRaises(GoogleError):
            self.upstream.generate(
                {'access_token': 'access-a', 'project_id': 'project-a'},
                'gemini-3.1-flash-image',
                {},
            )
        urls = [c['url'] for c in self.calls]
        self.assertEqual(urls[0], CONFIGURED_UPSTREAM + ':loadCodeAssist')
        self.assertTrue(urls[1].startswith(CONFIGURED_UPSTREAM + ':streamGenerateContent'))
        self.assertFalse(any('daily-cloudcode-pa.googleapis.com' in url and 'streamGenerateContent' in url for url in urls))
        self.assertFalse(any('cloudcode-pa.googleapis.com' in url and 'loadCodeAssist' in url for url in urls))


    def test_quota_client_headers_follow_cockpit_catalog_formula_and_leave_generation_unchanged(self):
        from sidecars.google_pool.upstream import build_cloud_code_user_agent

        expected = build_cloud_code_user_agent(
            ide_version='2.33.0', os_name='darwin', arch='arm64'
        )
        self.assertEqual(
            expected,
            'antigravity/2.33.0 (aidev_client; os_type=darwin; arch=arm64; cl=1003475615)',
        )
        self.assertEqual(
            build_cloud_code_user_agent(
                ide_version='2.17.0', os_name='darwin', arch='arm64'
            ),
            'antigravity/2.25.0 (aidev_client; os_type=darwin; arch=arm64; cl=1003475615)',
        )

        self.upstream.quota_summary('access-a', None)
        self.upstream.metadata('access-a', 'fetchAvailableModels', {})
        quota_ua = build_cloud_code_user_agent()
        for call in self.calls:
            headers = call['headers']
            self.assertEqual(headers.get('User-Agent'), quota_ua)
            self.assertEqual(headers.get('Accept-Encoding'), 'gzip')
            self.assertEqual(headers.get('Content-Type'), 'application/json')
            self.assertEqual(headers.get('Authorization'), 'present')
            self.assertNotIn('x-client-name', {k.lower() for k in headers})
            self.assertNotIn('x-goog-api-client', {k.lower() for k in headers})
            self.assertTrue(call['url'].startswith(OFFICIAL_DAILY + ':'))
            self.assertEqual(call['json'], {})

        self.calls.clear()
        self.upstream.metadata('access-a', 'loadCodeAssist', {'metadata': {'ideType': 'ANTIGRAVITY'}})
        with self.assertRaises(GoogleError):
            self.upstream.generate(
                {'access_token': 'access-a', 'project_id': 'project-a'},
                'gemini-3.1-flash-image',
                {},
            )
        for call in self.calls:
            headers = call['headers']
            self.assertEqual(headers.get('User-Agent'), 'antigravity')
            self.assertEqual(headers.get('x-client-name'), 'antigravity')
            self.assertNotEqual(headers.get('User-Agent'), quota_ua)
            self.assertNotIn('aidev_client', str(headers.get('User-Agent') or ''))
            self.assertEqual(headers.get('Authorization'), 'present')
            self.assertTrue(call['url'].startswith(CONFIGURED_UPSTREAM + ':'))

    def test_prod_host_only_when_gcp_tos_is_reliably_true_and_project_is_valid(self):
        self.upstream.quota_summary('access-a', 'project-a', is_gcp_tos=True)
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_PROD + ':retrieveUserQuotaSummary')
        self.assertEqual(self.calls[-1]['json'], {'project': 'project-a'})
        self.upstream.metadata(
            'access-a',
            'fetchAvailableModels',
            {'project': 'project-a'},
            is_gcp_tos=True,
        )
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_PROD + ':fetchAvailableModels')
        self.upstream.quota_summary('access-a', 'aicode-consumers', is_gcp_tos=True)
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_DAILY + ':retrieveUserQuotaSummary')
        self.upstream.quota_summary('access-a', 'project-a', is_gcp_tos=None)
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_DAILY + ':retrieveUserQuotaSummary')
        self.upstream.quota_summary('access-a', 'project-a', is_gcp_tos=False)
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_DAILY + ':retrieveUserQuotaSummary')
        self.upstream.quota_summary('access-a', 'project-a', is_gcp_tos='true')
        self.assertEqual(self.calls[-1]['url'], OFFICIAL_DAILY + ':retrieveUserQuotaSummary')


class QuotaRefreshWithoutValidProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = GoogleStore(settings(Path(self.temp.name)).db_path)
        self.upstream = Mock()
        self.upstream.metadata.return_value = {'models': CATALOG}
        self.upstream.quota_summary.return_value = CLAUDE_GROUPS
        self.pool = GooglePool(self.store, self.upstream)
        self.store.set_enabled(True)

    def test_refresh_without_project_continues_and_does_not_discover_project(self):
        account_id = self.store.import_account(
            {
                'refresh_token': 'token-noproj',
                'access_token': 'access-a',
                'expires_in': 3600,
            }
        )['id']
        public = self.pool.refresh(account_id)
        self.assertTrue(public['models'])
        self.assertEqual(public['quota_groups_status'], 'ok')
        self.assertFalse(public['project_configured'])
        methods = [call.args[1] for call in self.upstream.metadata.call_args_list]
        self.assertNotIn('loadCodeAssist', methods)
        self.assertEqual(methods, ['fetchAvailableModels'])
        self.assertEqual(self.upstream.metadata.call_args.args[2], {})
        self.upstream.quota_summary.assert_called_once()
        args, kwargs = self.upstream.quota_summary.call_args
        project = args[1] if len(args) > 1 else kwargs.get('project')
        self.assertFalse(project)

    def test_refresh_does_not_send_placeholder_project(self):
        account_id = self.store.import_account(
            {
                'refresh_token': 'token-placeholder',
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'aicode-consumers',
            }
        )['id']
        public = self.pool.refresh(account_id)
        self.assertTrue(public['models'])
        self.assertEqual(public['quota_groups_status'], 'ok')
        self.assertFalse(public['project_configured'])
        methods = [call.args[1] for call in self.upstream.metadata.call_args_list]
        self.assertNotIn('loadCodeAssist', methods)
        self.assertEqual(self.upstream.metadata.call_args.args[2], {})
        args, kwargs = self.upstream.quota_summary.call_args
        project = args[1] if len(args) > 1 else kwargs.get('project')
        self.assertFalse(project)

    def test_credentials_still_discovers_project_for_generation(self):
        account_id = self.store.import_account(
            {
                'refresh_token': 'token-creds',
                'access_token': 'access-a',
                'expires_in': 3600,
            }
        )['id']
        with self.assertRaises(GoogleError) as ctx:
            self.pool.credentials(account_id)
        self.assertEqual(ctx.exception.code, 'google_project_unavailable')
        self.assertEqual(self.upstream.metadata.call_args.args[1], 'loadCodeAssist')
        self.upstream.quota_summary.assert_not_called()

    def test_placeholder_is_not_a_configured_project_in_public_account(self):
        placeholder = self.store.import_account(
            {
                'refresh_token': 'token-public-placeholder',
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'aicode-consumers',
            }
        )
        valid = self.store.import_account(
            {
                'refresh_token': 'token-public-valid',
                'access_token': 'access-a',
                'expires_in': 3600,
                'project_id': 'project-a',
            }
        )
        self.assertFalse(placeholder['project_configured'])
        self.assertTrue(valid['project_configured'])



class SummaryBucketFamilyMappingTests(unittest.TestCase):
    """Exact Cockpit v1.4.2 summary_bucket_family rules on official bucketId only."""

    def test_3p_and_claude_aliases_map_to_claude_windows(self):
        from sidecars.google_pool.quota_groups import official_bucket_family, official_bucket_window
        for bucket_id, window in (
            ('3p-5h', '5h'),
            ('claude:5h', '5h'),
            ('3p-weekly', 'weekly'),
            ('claude:weekly', 'weekly'),
        ):
            self.assertEqual(official_bucket_family(bucket_id), 'claude', bucket_id)
            self.assertEqual(
                official_bucket_window({'bucket_id': bucket_id, 'window': window}),
                window,
                bucket_id,
            )

    def test_gemini_aliases_map_to_gemini_only(self):
        from sidecars.google_pool.quota_groups import official_bucket_family
        for bucket_id in ('gemini-5h', 'gemini:5h', 'gemini-weekly', 'gemini:weekly'):
            self.assertEqual(official_bucket_family(bucket_id), 'gemini', bucket_id)
        self.assertNotEqual(official_bucket_family('3p-weekly'), 'gemini')
        self.assertIsNone(official_bucket_family('gemini-flash'))

    def test_argon_official_ids_and_gemini_argon_suffix_aliases(self):
        from sidecars.google_pool.quota_groups import official_bucket_family, official_bucket_window
        for bucket_id, window in (
            ('argon:weekly', 'weekly'),
            ('argon:5h', '5h'),
            ('gemini-argon-wtu-weekly', 'weekly'),
            ('gemini-argon-foo-5h', '5h'),
        ):
            self.assertEqual(official_bucket_family(bucket_id), 'argon', bucket_id)
            self.assertEqual(
                official_bucket_window({'bucket_id': bucket_id, 'window': window}),
                window,
                bucket_id,
            )

    def test_carbon_official_ids_map_to_carbon_weekly_only(self):
        from sidecars.google_pool.quota_groups import official_bucket_family
        self.assertEqual(official_bucket_family('carbon:weekly'), 'carbon')
        self.assertEqual(official_bucket_family('gemini-carbon-wtu-weekly'), 'carbon')
        self.assertIsNone(official_bucket_family('carbon:5h'))
        self.assertIsNone(official_bucket_family('gemini-carbon-wtu-5h'))

    def test_families_do_not_cross_and_unofficial_or_description_text_is_ignored(self):
        from sidecars.google_pool.quota_groups import official_bucket_family
        self.assertEqual(official_bucket_family('3p-5h'), 'claude')
        self.assertNotEqual(official_bucket_family('3p-5h'), 'argon')
        self.assertNotEqual(official_bucket_family('3p-weekly'), 'gemini')
        for bucket_id in (
            'argon-weekly',
            'argon_5h',
            'gemini-4-argon',
            'gemini-argon-wtu',
            'gemini-argon-wtu-daily',
            'family-daily',
            'Claude and GPT models',
            'These are not Gemini models; Claude only',
        ):
            self.assertIsNone(official_bucket_family(bucket_id), bucket_id)

    def test_official_window_field_wins_and_missing_window_can_use_official_id_suffix_only(self):
        from sidecars.google_pool.quota_groups import official_bucket_window
        self.assertEqual(
            official_bucket_window({'bucket_id': '3p-5h', 'window': '5h'}),
            '5h',
        )
        self.assertEqual(
            official_bucket_window({'bucket_id': 'argon:weekly', 'window': ''}),
            'weekly',
        )
        self.assertEqual(
            official_bucket_window({'bucket_id': 'family-daily', 'window': 'daily'}),
            'daily',
        )
        self.assertEqual(
            official_bucket_window({'bucket_id': 'family-odd', 'window': ''}),
            '',
        )




if __name__ == '__main__':
    unittest.main()
