"""Google pool LLM path: catalog filtering, thought stripping, account rotation, prompt dispatch.

All accounts, upstream calls and sidecar responses are synthetic.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sidecars.google_pool.config import GoogleSettings
from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.pool import GooglePool
from sidecars.google_pool.store import GoogleStore
from sidecars.google_pool.wire import (
    TextResponse,
    is_image_model,
    is_text_model,
    normalize_model,
    prepare_text_request,
)
from backend import prompt_skill_client as client
from backend.provider_google_pool_llm import GooglePoolLLM, model_label

CATALOG = {
    'gemini-3.1-flash-image': {'quotaInfo': {'remainingFraction': 0.5}},
    'gemini-3-flash': {'quotaInfo': {'remainingFraction': 1}},
    'claude-sonnet-4-6': {'quotaInfo': {'remainingFraction': 1}},
    'chat_20706': {},
    'tab_flash_lite_preview': {},
}


def sse(value):
    return b'data: ' + json.dumps(value).encode() + b'\r\n\r\n'


class WireTextTests(unittest.TestCase):
    def test_model_classification(self):
        self.assertTrue(is_text_model('gemini-3-flash'))
        self.assertTrue(is_text_model('claude-opus-5-5-high'))
        self.assertTrue(is_text_model('gpt-oss-120b-medium'))
        for name in ('gemini-3.1-flash-image', 'chat_20706', 'tab_flash_lite_preview', 'gpt', ''):
            self.assertFalse(is_text_model(name), name)
        self.assertTrue(is_image_model('gemini-3-pro-image-preview'))
        with self.assertRaises(GoogleError):
            normalize_model('gemini-3-flash')  # image path stays image-only

    def test_text_request_keeps_system_and_config(self):
        request = prepare_text_request({
            'systemInstruction': {'parts': [{'text': 'sys'}]},
            'contents': [{'role': 'user', 'parts': [{'text': 'hi'}]}],
            'generationConfig': {'temperature': 0.2, 'unknown': 1},
        })
        self.assertEqual(request['systemInstruction'], {'parts': [{'text': 'sys'}]})
        self.assertEqual(request['generationConfig'], {'temperature': 0.2})

    def test_thought_parts_are_dropped_across_chunk_boundaries(self):
        raw = (
            b': heartbeat\n\n'
            + sse({'response': {'candidates': [{'content': {'parts': [{'thought': True, 'text': 'thinking'}]}}]}})
            + sse({'response': {'candidates': [{'content': {'parts': [{'text': 'Hel'}]}}]}})
            + sse({'response': {'candidates': [{'content': {'parts': [{'text': 'lo'}]}, 'finishReason': 'STOP'}]}})
        )
        for size in (1, 7, 64, 4096):
            decoder = TextResponse()
            deltas = []
            for i in range(0, len(raw), size):
                deltas.extend(decoder.feed(raw[i:i + size]))
            result = decoder.finish()
            self.assertEqual(''.join(deltas), 'Hello')
            self.assertEqual(result['candidates'][0]['content']['parts'][0]['text'], 'Hello')


class PoolTextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = GoogleSettings(Path(self.temp.name) / 'g/accounts.db', 'id', 'secret', 'http://localhost/cb')
        self.store = GoogleStore(settings.db_path)
        self.upstream = Mock()
        self.upstream.metadata.return_value = {'models': CATALOG}
        self.pool = GooglePool(self.store, self.upstream)
        self.store.set_enabled(True)

    def account(self, key):
        account_id = self.store.import_account({
            'refresh_token': key, 'access_token': 'at', 'expires_in': 3600, 'project_id': 'p'
        })['id']
        self.pool.refresh(account_id)
        return account_id

    def test_refresh_keeps_image_and_text_models_only(self):
        account_id = self.account('a')
        names = {m['name'] for m in self.store.get(account_id)['models']}
        self.assertEqual(names, {'gemini-3.1-flash-image', 'gemini-3-flash', 'claude-sonnet-4-6'})

    def test_rotates_to_next_account_on_preflight_capacity_error(self):
        self.account('a')
        self.account('b')
        calls = []

        def stream_text(account, model, request, cancelled=None):
            calls.append(account['id'])
            if len(calls) == 1:
                raise GoogleError('busy', 503, 'google_upstream_error')
            yield ('delta', 'ok')
            yield ('done', {'candidates': [{'content': {'parts': [{'text': 'ok'}]}}]})

        self.upstream.stream_text.side_effect = stream_text
        result = self.pool.generate('gemini-3-flash', {'contents': [{'parts': [{'text': 'x'}]}]})
        self.assertEqual(len(set(calls)), 2)
        self.assertEqual(result['google_pool']['resolved_model'], 'gemini-3-flash')
        self.assertEqual(self.pool.stats()['inflight'], 0)

    def test_no_retry_after_tokens_were_streamed(self):
        self.account('a')
        self.account('b')

        def stream_text(account, model, request, cancelled=None):
            yield ('delta', 'partial')
            raise GoogleError('cut', 502, 'google_execution_unknown')

        self.upstream.stream_text.side_effect = stream_text
        with self.assertRaises(GoogleError):
            list(self.pool.stream_text('gemini-3-flash', {'contents': [{'parts': [{'text': 'x'}]}]}))
        self.assertEqual(self.upstream.stream_text.call_count, 1)


class FakeResponse:
    def __init__(self, status=200, data=None, lines=None):
        self.status_code = status
        self.data = data
        self.lines = lines or []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def json(self):
        return self.data

    def iter_lines(self, decode_unicode=False):
        yield from self.lines


class FakeSession:
    def __init__(self, get=None, post=None):
        self._get, self._post = get, post
        self.trust_env = True
        self.posts = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, *args, **kwargs):
        return self._get

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return self._post


class BackendGooglePoolLLMTests(unittest.TestCase):
    transport = staticmethod(lambda: {'base_url': 'http://fixture', 'auth_key': 'k'})

    def test_list_models_filters_and_labels(self):
        data = {'models': [{'name': 'models/gemini-3-flash'}, {'name': 'models/gemini-3.1-flash-image'},
                           {'name': 'models/claude-opus-5-5-high'}]}
        llm = GooglePoolLLM(self.transport, lambda: FakeSession(get=FakeResponse(data=data)))
        models, warning = llm.list_models()
        self.assertEqual([m['id'] for m in models], ['gemini-3-flash', 'claude-opus-5-5-high'])
        self.assertEqual(warning, '')
        self.assertEqual(GooglePoolLLM.default_model(models), 'gemini-3-flash')
        self.assertEqual(model_label('claude-opus-5-5-high'), 'Claude Opus 5.5 High')

    def test_stream_uses_deltas_and_ignores_final_duplicate(self):
        delta = lambda t: b'data: ' + json.dumps({'candidates': [{'content': {'parts': [{'text': t}]}}],
                                                   'google_pool_delta': True}).encode()
        final = b'data: ' + json.dumps({'candidates': [{'content': {'parts': [{'text': 'AB'}]}}]}).encode()
        session = FakeSession(post=FakeResponse(lines=[b': hb', delta('A'), delta('B'), final]))
        llm = GooglePoolLLM(self.transport, lambda: session)
        self.assertEqual(llm.call('p', 's', 'gemini-3-flash'), 'AB')
        url, kwargs = session.posts[0]
        self.assertTrue(url.endswith('/v1beta/models/gemini-3-flash:streamGenerateContent?alt=sse'))
        self.assertEqual(kwargs['json']['systemInstruction'], {'parts': [{'text': 's'}]})

    def test_prompt_provider_registry_and_dispatch(self):
        ids = [p['id'] for p in client.list_prompt_providers()]
        self.assertIn('google_pool', ids)
        fake = Mock()
        fake.call.return_value = 'reply'
        with patch.object(client, '_google_pool_llm', return_value=fake):
            self.assertEqual(client._call_prompt_provider('google_pool', 'p', 's', 'gemini-3-flash', 'high'), 'reply')
            client._call_prompt_provider('google_pool', 'p', 's', 'gemini-3-flash', 'high', images=['data:image/png;base64,AA=='])
        self.assertEqual(fake.call.call_args_list[1].args[3], ['data:image/png;base64,AA=='])


if __name__ == '__main__':
    unittest.main()
