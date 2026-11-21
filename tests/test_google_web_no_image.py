"""Offline Gemini Web no-image regressions. Synthetic frames only; no network."""
from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
import unittest

HAS_WEB = all(importlib.util.find_spec(name) for name in ('curl_cffi', 'orjson', 'pydantic'))


def _candidate(*, text, images=False, edit=False, rcid='rc_synthetic'):
    entry = [[None, None, None, [None, None, 'synthetic image',
        'https://lh3.googleusercontent.com/gg/preview=s1024-rj', None, '$synthetic-token']],
        ['http://googleusercontent.com/image_generation_content/0', 0], None,
        [23, 'synthetic description']]
    candidate = [None] * 38
    candidate[0], candidate[1], candidate[8] = rcid, [text], [2]
    if not images:
        candidate[12] = [None] * 8
        return candidate
    candidate[12] = [{'8': [[entry]]}] if edit else [None] * 8
    if not edit:
        candidate[12][7] = [[entry]]
    return candidate


def _stream_bytes(candidates):
    chunks = []
    for index, candidate in enumerate(candidates):
        body = [None, ['c_synthetic', 'r_synthetic'], None, None, [candidate]]
        frame = json.dumps([['wrb.fr', None, json.dumps(body)]])
        prefix = ")]}'\n" if index == 0 else ''
        chunks.append(prefix + str(len(frame) + 2) + '\n' + frame + '\n')
    return ''.join(chunks).encode()


@unittest.skipUnless(HAS_WEB, 'Requires Web runtime dependencies')
class LastFrameOmitsGeneratedImageTest(unittest.IsolatedAsyncioTestCase):
    async def _client(self, candidates):
        from curl_cffi.requests import AsyncSession
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient

        client = GeminiClient(secure_1psid='synthetic-cookie', authuser=2)
        client._running = True
        client.access_token = 'synthetic-access-token'
        raw = _stream_bytes(candidates)

        class Response:
            status_code = 200

            async def aiter_content(self):
                yield raw

        class Stream:
            async def __aenter__(self):
                return Response()

            async def __aexit__(self, *_):
                pass

        async def post(url, **kwargs):
            return SimpleNamespace(status_code=200, text='[]')

        http = AsyncSession()
        self.addAsyncCleanup(http.close)
        http.post, http.stream = post, (lambda *args, **kwargs: Stream())
        client.client = http
        return client

    async def test_generate_content_keeps_images_when_final_frame_omits_them(self):
        from sidecars.google_web.vendor.gemini_webapi.types import GeneratedImage

        client = await self._client([
            _candidate(text='mid-stream image', images=True, edit=True),
            _candidate(text='final text only', images=False, edit=True),
        ])
        output = await client.generate_content('synthetic edit', temporary=True, pro_image=True)
        images = [image for image in output.images if isinstance(image, GeneratedImage)]
        self.assertEqual(len(images), 1)
        self.assertEqual(output.text, 'final text only')

    async def test_text_only_stream_still_has_no_generated_image(self):
        from sidecars.google_web.vendor.gemini_webapi.types import GeneratedImage

        client = await self._client([_candidate(text='text only', images=False)])
        output = await client.generate_content('synthetic', temporary=True, pro_image=True)
        images = [image for image in output.images if isinstance(image, GeneratedImage)]
        self.assertEqual(images, [])
        self.assertEqual(output.text, 'text only')


@unittest.skipUnless(HAS_WEB, 'Requires Web runtime dependencies')
class NoImageDiagnosticTest(unittest.IsolatedAsyncioTestCase):
    async def test_upstream_no_image_reports_structure_counts_without_text(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.upstream import GeminiWebUpstream
        from sidecars.google_web.vendor.gemini_webapi.types import Candidate, ModelOutput

        class DummyUpstream(GeminiWebUpstream):
            def __init__(self):
                self.sessions = {'acct': {'client': self}}
                self.settings = SimpleNamespace(timeout=5, proxy_url='')
                self.download_diagnostics = SimpleNamespace()

            def flush(self, account_id, client):
                return None

        output = ModelOutput(
            metadata=['c', 'r'],
            candidates=[Candidate(rcid='rc1', text='synthetic refusal text', thoughts='thinking notes',
                                  web_images=[], generated_images=[], generated_videos=[], generated_media=[])],
        )

        class FakeClient:
            async def generate_content(self, *args, **kwargs):
                return output

        upstream = DummyUpstream()
        upstream.sessions['acct']['client'] = FakeClient()
        request = {
            'contents': [{'parts': [{'text': 'synthetic prompt'}]}],
            'generationConfig': {'imageConfig': {'aspectRatio': '16:9', 'imageSize': '2K'}},
        }
        with self.assertRaises(WebError) as caught:
            await upstream.generate('acct', request)
        error = caught.exception
        self.assertEqual(error.code, 'web_no_image')
        details = error.details
        self.assertIsInstance(details, dict)
        self.assertEqual(details.get('candidate_count'), 1)
        self.assertEqual(details.get('generated_image_count'), 0)
        self.assertEqual(details.get('web_image_count'), 0)
        self.assertEqual(details.get('text_len'), len('synthetic refusal text'))
        self.assertEqual(details.get('thoughts_len'), len('thinking notes'))
        blob = json.dumps(details, ensure_ascii=False)
        self.assertNotIn('synthetic refusal text', blob)
        self.assertNotIn('thinking notes', blob)
        self.assertNotIn('synthetic prompt', blob)
