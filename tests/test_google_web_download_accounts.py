"""Synthetic per-account CDN routing; no credentials or live Google services."""
import io
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

from PIL import Image


def image_bytes(color='blue'):
    stream = io.BytesIO()
    Image.new('RGB', (1536, 2752), color).save(stream, 'PNG')
    return stream.getvalue()


class DownloadAccountTest(unittest.IsolatedAsyncioTestCase):
    def image(self, slot, *, original=True):
        client = SimpleNamespace(authuser=slot,
            _get_full_size_image=AsyncMock(return_value=(
                'https://lh3.googleusercontent.com/gg/original?sig=a%2fb+%2B&part=1&part=2'
                if original else None)))
        return SimpleNamespace(client_ref=client, temporary=True, cid='synthetic-c',
            rid='synthetic-r', rcid='synthetic-rc', image_id='synthetic-image',
            url='https://lh3.googleusercontent.com/gg/preview=s1024-rj?sig=other%2bvalue')

    def session(self, owner, raw, *, forbidden=False):
        calls = []

        async def get(url, **kwargs):
            calls.append((url, kwargs))
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            # Google defaults to account 0, not the Gemini RPC's selected slot.
            selected = int(query.get('authuser', ['0'])[0])
            if parsed.path.startswith('/gg/'):
                if 'original' in parsed.path:
                    next_url = 'https://lh3.google.com/rd-gg/asset?alr=yes'
                    if 'authuser' in query:
                        next_url += '&authuser=' + str(selected)
                    return reply(next_url.encode())
            elif parsed.hostname == 'lh3.google.com':
                next_url = 'https://lh3.googleusercontent.com/rd-gg/asset?alr=yes'
                if 'authuser' in query:
                    next_url += '&authuser=' + str(selected)
                return reply(next_url.encode())
            if selected != owner or forbidden:
                return reply(b'<html>Forbidden</html>', status=403)
            return reply(raw)

        return SimpleNamespace(get=get, calls=calls)

    async def test_shared_session_slots_0_to_3_download_their_own_original(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        for slot, color in enumerate(('red', 'blue', 'green', 'yellow')):
            with self.subTest(slot=slot):
                expected = image_bytes(color)
                image = self.image(slot)
                session = self.session(slot, expected)
                try:
                    raw, mime, meta = await download_generated_image(image, session)
                except WebError:
                    self.fail('A non-default account must not download as account 0')
                self.assertEqual(raw, expected)
                self.assertEqual(mime, 'image/png')
                self.assertEqual(meta, {'web_image_source': 'original_rpc', 'web_original_verified': True})
                self.assertEqual(len(session.calls), 3)
                self.assertEqual(image.client_ref._get_full_size_image.await_count, 1)
                for url, kwargs in session.calls:
                    self.assertEqual(int(parse_qs(urlsplit(url).query).get('authuser', ['0'])[0]), slot)
                    self.assertIs(kwargs['allow_redirects'], False)
                    self.assertNotIn('Cookie', kwargs['headers'])
                    self.assertNotIn('Authorization', kwargs['headers'])

    async def test_unavailable_original_keeps_selected_account_in_preview_fallback(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        for slot in (1, 3):
            with self.subTest(slot=slot):
                expected = image_bytes()
                session = self.session(slot, expected)
                try:
                    raw, _, meta = await download_generated_image(self.image(slot, original=False), session)
                except WebError:
                    self.fail('Fallback must use the same account, not silently default to account 0')
                self.assertEqual(raw, expected)
                self.assertEqual(meta, {'web_image_source': 'preview_fallback',
                    'web_original_verified': False, 'web_original_error': 'rpc_unavailable'})
                self.assertEqual(len(session.calls), 1)

    async def test_forbidden_download_never_switches_account_or_replays_rpc(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        image = self.image(2)
        session = self.session(2, image_bytes(), forbidden=True)
        with self.assertRaises(WebError) as raised:
            await download_generated_image(image, session)
        self.assertEqual(raised.exception.code, 'web_image_download_failed')
        self.assertEqual(image.client_ref._get_full_size_image.await_count, 1)
        self.assertEqual(len(session.calls), 4)  # Three original hops, then the preview.
        self.assertEqual([int(parse_qs(urlsplit(url).query).get('authuser', ['0'])[0])
            for url, _ in session.calls], [2, 2, 2, 2])

    async def test_account_selection_preserves_raw_signed_query_and_pointer_urls(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        image = self.image(2)
        # Repeated parameters and signature escaping must remain byte-for-byte intact.
        image.client_ref._get_full_size_image.return_value += '&authuser=0&alr=no'
        session = self.session(2, image_bytes())
        try:
            await download_generated_image(image, session)
        except WebError:
            self.fail('The original request must select account 2, retaining its signed URL encoding')
        self.assertEqual(session.calls[0][0],
            'https://lh3.googleusercontent.com/gg/original=d-I?sig=a%2fb+%2B&part=1&part=2&authuser=2&alr=yes')
        self.assertEqual(session.calls[1][0], 'https://lh3.google.com/rd-gg/asset?alr=yes&authuser=2')
        self.assertEqual(session.calls[2][0], 'https://lh3.googleusercontent.com/rd-gg/asset?alr=yes&authuser=2')

    async def test_invalid_account_selector_is_rejected_before_download(self):
        from sidecars.google_web.errors import WebError
        from sidecars.google_web.images import download_generated_image
        for slot in (-1, 20, True, 1.5, '1'):
            with self.subTest(slot=slot):
                session = self.session(0, image_bytes())
                with self.assertRaises(WebError):
                    await download_generated_image(self.image(slot), session)
                self.assertEqual(session.calls, [])


def reply(raw, status=200):
    def raise_for_status():
        if status != 200:
            raise RuntimeError('Synthetic HTTP failure')
    return SimpleNamespace(status_code=status, content=raw, headers={}, raise_for_status=raise_for_status)


if __name__ == '__main__':
    unittest.main()
