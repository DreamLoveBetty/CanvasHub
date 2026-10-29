"""A broken Google image stream keeps its cause, and large uploads get time to finish."""

import unittest
from types import SimpleNamespace

import requests

from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.upstream import CONNECT_TIMEOUT, MAX_UPLOAD_TIMEOUT, GoogleUpstream, upload_timeout

SETTINGS = SimpleNamespace(upstream="https://upstream.invalid/v1internal", timeout=900, proxy_url="")
ACCOUNT = {"id": "fixture-account", "project_id": "fixture-project", "access_token": "fixture-secret-token"}


class FakeResponse:
    status_code = 200

    def __init__(self, chunks, error):
        self.chunks = chunks
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size=None):
        yield from self.chunks
        raise self.error


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.trust_env = True
        self.proxies = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


class GoogleUpstreamDiagnosticsTest(unittest.TestCase):
    def generate(self, session):
        upstream = GoogleUpstream(SETTINGS, session_factory=lambda: session)
        with self.assertLogs("sidecars.google_pool.upstream", level="WARNING") as logs, \
                self.assertRaises(GoogleError) as caught:
            upstream.generate(ACCOUNT, "gemini-3.1-flash-image", {"contents": []})
        return caught.exception, "\n".join(logs.output)

    def test_mid_stream_disconnect_reports_type_phase_and_bytes(self):
        response = FakeResponse([b": heartbeat\n\n"], requests.exceptions.ChunkedEncodingError("reset"))
        error, log = self.generate(FakeSession(response=response))
        self.assertEqual(error.code, "google_execution_unknown")
        self.assertIn("ChunkedEncodingError", str(error))
        self.assertIn("stream", str(error))
        self.assertIn("已收 13 字节", str(error))
        self.assertIn("未重新提交", str(error))
        self.assertIn("phase=stream", log)
        self.assertIn("bytes=13", log)
        self.assertIn("account=fixture-account", log)
        self.assertNotIn("fixture-secret-token", log + str(error))

    def test_connect_failure_reports_connect_phase(self):
        error, log = self.generate(FakeSession(error=requests.exceptions.ConnectTimeout("slow")))
        self.assertIn("ConnectTimeout", str(error))
        self.assertIn("connect", str(error))
        self.assertIn("phase=connect", log)
        self.assertIn("bytes=0", log)
        self.assertIn("MB", str(error))

    def test_upload_timeout_grows_with_request_size(self):
        self.assertEqual(upload_timeout(0), CONNECT_TIMEOUT)
        self.assertGreaterEqual(upload_timeout(10 * 1024 * 1024), 150)
        self.assertEqual(upload_timeout(10 ** 10), MAX_UPLOAD_TIMEOUT)

    def test_large_reference_images_extend_the_upload_timeout(self):
        session = FakeSession(error=requests.exceptions.ConnectionError("aborted"))
        image = {"inlineData": {"mimeType": "image/png", "data": "A" * (8 * 1024 * 1024)}}
        upstream = GoogleUpstream(SETTINGS, session_factory=lambda: session)
        with self.assertLogs("sidecars.google_pool.upstream", level="WARNING"), self.assertRaises(GoogleError):
            upstream.generate(ACCOUNT, "gemini-3.1-flash-image", {"contents": [{"parts": [image]}]})
        connect, read = session.kwargs["timeout"]
        self.assertGreater(connect, 100)
        self.assertEqual(read, SETTINGS.timeout)
        self.assertEqual(session.kwargs["json"]["request"]["contents"][0]["parts"][0], image)


if __name__ == "__main__":
    unittest.main()
