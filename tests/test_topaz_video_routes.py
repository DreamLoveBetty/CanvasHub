"""Portable transport tests for the independent Topaz Video HTTP adapter."""

import io
import json
import unittest

from backend.routes.topaz_video_routes import create_router


class FakeService:
    def __init__(self):
        self.uploaded = None
        self.submitted = None

    def status(self):
        return {'engine': 'topaz_video', 'ready': False, 'models': []}

    def upload(self, data, name):
        self.uploaded = (data, name)
        return {'asset_id': 'a' * 32}

    def submit(self, body):
        self.submitted = body
        return {'id': 'b' * 32, 'status': 'queued'}

    def job(self, ident):
        return {'id': ident, 'status': 'succeeded'}

    def cancel(self, ident):
        return {'id': ident, 'status': 'cancelled'}


class Handler:
    def __init__(self, path, payload=b'', *, authenticated=True):
        self.path = path
        self.headers = {'Content-Length': str(len(payload))}
        self.rfile = io.BytesIO(payload)
        self.authenticated = authenticated
        self.responses = []

    def require_auth(self):
        return self.authenticated

    def send_json(self, payload, status=200):
        self.responses.append((status, payload))


class TopazVideoRouteTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.router = create_router(self.service)

    def test_protected_and_exact_match(self):
        denied = Handler('/api/topaz_video/status', authenticated=False)
        self.assertTrue(self.router.dispatch(denied, 'GET', '/api/topaz_video/status'))
        self.assertEqual(denied.responses, [])
        self.assertFalse(self.router.dispatch(denied, 'GET', '/api/topaz_video/unknown'))
        self.assertFalse(self.router.dispatch(denied, 'POST', '/api/topaz_video/status'))

    def test_upload_and_submit_transport(self):
        uploaded = Handler('/api/topaz_video/upload?name=clip.mp4', b'video')
        self.assertTrue(self.router.dispatch(uploaded, 'POST', '/api/topaz_video/upload'))
        self.assertEqual(self.service.uploaded, (b'video', 'clip.mp4'))
        self.assertEqual(uploaded.responses[0][0], 200)

        body = {'asset_id': 'a' * 32, 'model': 'prob-4'}
        submitted = Handler('/api/topaz_video/submit', json.dumps(body).encode())
        self.assertTrue(self.router.dispatch(submitted, 'POST', '/api/topaz_video/submit'))
        self.assertEqual(self.service.submitted, body)
        self.assertEqual(submitted.responses[0][0], 202)

        queried = Handler('/api/topaz_video/job?id=' + 'b' * 32)
        self.assertTrue(self.router.dispatch(queried, 'GET', '/api/topaz_video/job'))
        self.assertEqual(queried.responses[0][1]['id'], 'b' * 32)

        cancelled = Handler('/api/topaz_video/cancel', json.dumps({'id': 'b' * 32}).encode())
        self.assertTrue(self.router.dispatch(cancelled, 'POST', '/api/topaz_video/cancel'))
        self.assertEqual(cancelled.responses[0][1]['status'], 'cancelled')

    def test_rejects_bad_or_oversized_json_before_service(self):
        for payload in (b'[]', b'{bad', b'', b'{}' + b'x' * 20000):
            with self.subTest(payload=payload[:8]):
                handler = Handler('/api/topaz_video/submit', payload)
                self.router.dispatch(handler, 'POST', '/api/topaz_video/submit')
                self.assertEqual(handler.responses[0][0], 400)
                self.assertIsNone(self.service.submitted)


if __name__ == '__main__':
    unittest.main()
