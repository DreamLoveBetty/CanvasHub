"""Synthetic stream-to-original regressions; no real accounts or network."""
import copy
import importlib.util
import io
import json
from types import SimpleNamespace
import unittest

from PIL import Image

HAS_WEB = all(importlib.util.find_spec(name) for name in ('curl_cffi', 'orjson', 'pydantic'))


def png_bytes(size):
    out = io.BytesIO()
    Image.new('RGB', size, 'blue').save(out, 'PNG')
    return out.getvalue()


def media_candidate(*, edit=False):
    # Both StreamGenerate media shapes; values are synthetic, not saved HAR data.
    entry = [[None, None, None, [None, None, 'synthetic image',
        'https://lh3.googleusercontent.com/gg/preview=s1024-rj', None, '$synthetic-token']],
        ['http://googleusercontent.com/image_generation_content/0', 0], None,
        [23, 'synthetic description']]
    candidate = [None] * 38
    candidate[0], candidate[1], candidate[8] = 'rc_synthetic', ['synthetic response'], [2]
    candidate[12] = [{'8': [[entry]]}] if edit else [None] * 8
    if not edit:
        candidate[12][7] = [[entry]]
    return candidate


@unittest.skipUnless(HAS_WEB, 'Requires Web runtime dependencies')
class OriginalImageContextTest(unittest.IsolatedAsyncioTestCase):
    def client(self, *, modes=(True,), edit=False, reject=False):
        from curl_cffi.requests import AsyncSession
        from sidecars.google_web.vendor.gemini_webapi import GeminiClient
        from sidecars.google_web.vendor.gemini_webapi.constants import GRPC
        client = GeminiClient(secure_1psid='synthetic-cookie', authuser=2)
        client._running = True
        client.access_token = 'synthetic-access-token'
        self.calls, self.downloads, self.submissions = [], [], []
        self.original, self.preview = png_bytes((1536, 2752)), png_bytes((768, 1376))
        self.expected_modes = list(modes)
        candidate = media_candidate(edit=edit)
        self.candidate, self.candidate_before = candidate, copy.deepcopy(candidate)

        async def post(url, **kwargs):
            self.assertTrue(str(url).endswith('/batchexecute'))
            if kwargs['params']['rpcids'] == GRPC.BARD_SETTINGS:
                return SimpleNamespace(status_code=200, text='[]')
            self.assertEqual(kwargs['params']['rpcids'], 'c8o8Fe', 'No history or other RPC is needed')
            payload = json.loads(json.loads(kwargs['data']['f.req'])[0][0][1])
            self.calls.append((kwargs['params'], payload))
            # The same temporary image yields 1003 with 0 and the original with 1.
            expected_flag = {'c_synthetic_temp': 1, 'c_synthetic_saved': 0}[payload[1][2]]
            if reject or payload[3] != expected_flag:
                frames = [['wrb.fr', 'c8o8Fe', None, None, None,
                    [3, None, [['synthetic.BardErrorInfo', [1003]]]], 'generic']]
            else:
                # A telemetry record must not hide the actual RPC result.
                frames = [['di', 1], ['wrb.fr', 'c8o8Fe', json.dumps([
                    'https://lh3.googleusercontent.com/gg/original']), None, None, None, 'generic']]
            return SimpleNamespace(status_code=200, text=json.dumps(frames))

        async def get(url, **kwargs):
            self.downloads.append(url)
            raw = self.original if url == 'https://lh3.googleusercontent.com/gg/original=d-I?alr=yes&authuser=2' else self.preview
            return SimpleNamespace(status_code=200, content=raw, headers={}, raise_for_status=lambda: None)

        def stream(method, url, **kwargs):
            self.assertEqual(method, 'POST')
            self.assertTrue(str(url).endswith('/StreamGenerate'))
            self.assertLess(len(self.submissions), len(self.expected_modes), 'Generation must never replay')
            temporary = self.expected_modes[len(self.submissions)]
            inner = json.loads(json.loads(kwargs['data']['f.req'])[1])
            self.assertEqual(inner[45], 1 if temporary else None)
            self.assertEqual(kwargs['params']['authuser'], 2)
            self.submissions.append(temporary)
            cid = 'c_synthetic_temp' if temporary else 'c_synthetic_saved'
            body = [None, [cid, 'r_synthetic'], None, None, [candidate]]
            frame = json.dumps([['wrb.fr', None, json.dumps(body)]])
            raw = (")]}'\n" + str(len(frame) + 2) + '\n' + frame + '\n').encode()

            class Response:
                status_code = 200

                async def aiter_content(self):
                    yield raw[:27]
                    yield raw[27:]

            class Stream:
                async def __aenter__(self):
                    return Response()

                async def __aexit__(self, *_):
                    pass

            return Stream()

        http = AsyncSession()
        self.addAsyncCleanup(http.close)
        http.post, http.get, http.stream = post, get, stream
        client.client = http
        return client

    async def test_temporary_generation_and_edit_return_2k_original_not_1003_preview(self):
        from sidecars.google_web.images import download_generated_image
        for edit in (False, True):
            with self.subTest(edit=edit):
                client = self.client(edit=edit)
                output = await client.generate_content('synthetic 2K', temporary=True, pro_image=True)
                raw, mime, provenance = await download_generated_image(output.images[0], client.client)
                self.assertEqual(raw, self.original, 'Temporary download must not silently degrade to the 1K preview')
                self.assertEqual(mime, 'image/png')
                self.assertEqual(provenance, {'web_image_source': 'original_rpc', 'web_original_verified': True})
                self.assertEqual(self.submissions, [True])
                self.assertEqual(len(self.calls), 1)
                params, payload = self.calls[0]
                self.assertEqual(params['authuser'], 2)
                self.assertEqual(params['source-path'], '/app')
                self.assertEqual(payload[2:], [1, 1, 1])
                self.assertEqual(payload[1], ['r_synthetic', 'rc_synthetic', 'c_synthetic_temp', None, ''])
                self.assertEqual(payload[0][1], ['http://googleusercontent.com/image_generation_content/0', 0])
                self.assertEqual(self.candidate, self.candidate_before)
                self.assertEqual(self.downloads, ['https://lh3.googleusercontent.com/gg/original=d-I?alr=yes&authuser=2'])

    async def test_saved_generation_and_edit_keep_regular_original_contract(self):
        from sidecars.google_web.images import download_generated_image
        for edit in (False, True):
            with self.subTest(edit=edit):
                client = self.client(modes=(False,), edit=edit)
                output = await client.generate_content('synthetic', temporary=False, pro_image=True)
                raw, _, provenance = await download_generated_image(output.images[0], client.client)
                self.assertEqual(raw, self.original)
                self.assertTrue(provenance['web_original_verified'])
                self.assertEqual(self.submissions, [False])
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(self.calls[0][1][2:], [1, 0, 1])

    async def test_download_mode_belongs_to_the_image_not_last_client_request(self):
        from sidecars.google_web.images import download_generated_image
        client = self.client(modes=(True, False))
        temporary = (await client.generate_content('temporary', temporary=True)).images[0]
        saved = (await client.generate_content('saved', temporary=False)).images[0]
        for image in (temporary, saved):
            raw, _, provenance = await download_generated_image(image, client.client)
            self.assertEqual(raw, self.original)
            self.assertTrue(provenance['web_original_verified'])
            public = image.model_dump(exclude={'client', 'client_ref'})
            self.assertNotIn('temporary', public, 'Transport context must not change serialized image contracts')
            self.assertNotIn('$synthetic-token', json.dumps(public))
        self.assertEqual([payload[3] for _, payload in self.calls], [1, 0])
        self.assertEqual(self.submissions, [True, False])

    async def test_legacy_lookup_defaults_to_regular_mode_and_matches_rpc_frame(self):
        client = self.client(modes=())
        url = await client._get_full_size_image('c_synthetic_saved', 'r_synthetic', 'rc_synthetic', 'synthetic-image')
        self.assertEqual(url, 'https://lh3.googleusercontent.com/gg/original')
        self.assertEqual(self.submissions, [])
        self.assertEqual(len(self.calls), 1)
        params, payload = self.calls[0]
        self.assertEqual(params['authuser'], 2)
        self.assertEqual(params['source-path'], '/app')
        self.assertEqual(payload[2:], [1, 0, 1])
        self.assertEqual(payload[0][3], [19, ''])
        self.assertEqual(payload[0][0][3], [None, None, None, None, None, ''])

    async def test_upstream_rejection_stays_unverified_without_generation_replay(self):
        from sidecars.google_web.images import download_generated_image
        client = self.client(reject=True)
        output = await client.generate_content('synthetic', temporary=True)
        raw, _, provenance = await download_generated_image(output.images[0], client.client)
        self.assertEqual(raw, self.preview)
        self.assertEqual(provenance, {'web_image_source': 'preview_fallback',
            'web_original_verified': False, 'web_original_error': 'rpc_unavailable'})
        self.assertEqual(self.submissions, [True])
        self.assertEqual(len(self.calls), 1, 'An HTTP-200 rejection must not loop or resubmit generation')
        self.assertNotIn('$synthetic', json.dumps(provenance))


if __name__ == '__main__':
    unittest.main()
