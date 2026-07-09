import json
import unittest
from unittest.mock import patch

from backend import provider_third_party_image as provider


class ThirdPartyImageProviderTest(unittest.TestCase):
    def test_download_url_retries_chunked_disconnect_and_reports_progress(self):
        body = b"image-bytes-that-arrive-on-retry"
        events = []

        class FakeDownloadResponse:
            status_code = 200
            text = ""

            def __init__(self, should_fail):
                self.should_fail = should_fail
                self.headers = {"Content-Length": str(len(body))}

            def close(self):
                pass

            def iter_content(self, chunk_size=1):
                midpoint = len(body) // 2
                yield body[:midpoint]
                if self.should_fail:
                    raise provider.requests.exceptions.ChunkedEncodingError("connection broken")
                yield body[midpoint:]

        class FakeSession:
            def __init__(self):
                self.calls = 0

            def get(self, url, timeout=None, stream=False):
                self.calls += 1
                return FakeDownloadResponse(should_fail=self.calls == 1)

        fake_session = FakeSession()

        with patch.object(provider.time, "sleep") as sleep:
            result = provider._download_url(
                fake_session,
                "https://cdn.example.test/image.png",
                timeout=30,
                progress_callback=events.append,
                max_retries=2,
                item_index=1,
                item_count=1,
            )

        self.assertEqual(result, body)
        self.assertEqual(fake_session.calls, 2)
        sleep.assert_called_once_with(1)
        event_names = [event.get("event") for event in events]
        self.assertIn("download_retry", event_names)
        self.assertIn("download_complete", event_names)
        self.assertTrue(any(event.get("bytes_received", 0) > 0 for event in events))

    def test_generate_image_reports_malformed_json_with_response_preview(self):
        class FakeResponse:
            status_code = 200
            text = '{"data": [DONE]}'
            headers = {"Content-Type": "text/plain; charset=utf-8"}

            def json(self):
                raise json.JSONDecodeError("Expecting value", self.text, 10)

        class FakeSession:
            trust_env = False

            def __init__(self):
                self.headers = {}
                self.calls = []

            def post(self, url, headers=None, json=None, timeout=None):
                self.calls.append(
                    {
                        "url": url,
                        "headers": headers or {},
                        "json": json or {},
                        "timeout": timeout,
                    }
                )
                return FakeResponse()

        fake_session = FakeSession()
        with patch.object(
            provider,
            "get_third_party_image_config",
            return_value={
                "api_key": "sk-test",
                "api_key_configured": True,
                "base_url": "https://api.change2pro.com",
                "model": "gpt-image-2",
                "generate_path": "/v1/images/generations",
                "edit_path": "/v1/images/edits",
                "format": "png",
                "timeout_seconds": 900,
            },
        ), patch.object(provider.requests, "Session", return_value=fake_session):
            with self.assertRaises(RuntimeError) as ctx:
                provider.generate_image_third_party("draw a test image")

        message = str(ctx.exception)
        self.assertIn("无法解析的响应", message)
        self.assertIn("HTTP 200", message)
        self.assertIn("text/plain; charset=utf-8", message)
        self.assertIn('{"data": [DONE]}', message)
        self.assertNotIn("Expecting value: line 1 column 11", message)

    def test_generate_image_uses_neutral_file_prefix(self):
        class FakeResponse:
            status_code = 200
            text = '{"data": [{"url": "https://cdn.example.test/image.png"}]}'
            headers = {"Content-Type": "application/json"}

            def json(self):
                return {"data": [{"url": "https://cdn.example.test/image.png"}]}

        class FakeSession:
            trust_env = False

            def __init__(self):
                self.headers = {}

            def post(self, url, headers=None, json=None, timeout=None):
                return FakeResponse()

        fake_session = FakeSession()
        with patch.object(
            provider,
            "get_third_party_image_config",
            return_value={
                "api_key": "sk-test",
                "api_key_configured": True,
                "base_url": "https://api.example.com",
                "model": "gpt-image-2",
                "generate_path": "/v1/images/generations",
                "edit_path": "/v1/images/edits",
                "format": "png",
                "timeout_seconds": 900,
            },
        ), patch.object(provider.requests, "Session", return_value=fake_session), patch.object(
            provider,
            "_save_outputs",
            return_value={"success": True},
        ) as save_outputs:
            provider.generate_image_third_party("draw a test image")

        self.assertEqual(save_outputs.call_args.kwargs["file_prefix"], "gpt_third_party")

    def test_edit_image_uses_neutral_file_prefix(self):
        class FakeResponse:
            status_code = 200
            text = '{"data": [{"url": "https://cdn.example.test/image.png"}]}'
            headers = {"Content-Type": "application/json"}

            def json(self):
                return {"data": [{"url": "https://cdn.example.test/image.png"}]}

        class FakeSession:
            trust_env = False

            def __init__(self):
                self.headers = {}

            def post(self, url, data=None, files=None, timeout=None):
                return FakeResponse()

        fake_session = FakeSession()
        with patch.object(
            provider,
            "get_third_party_image_config",
            return_value={
                "api_key": "sk-test",
                "api_key_configured": True,
                "base_url": "https://api.example.com",
                "model": "gpt-image-2",
                "generate_path": "/v1/images/generations",
                "edit_path": "/v1/images/edits",
                "format": "png",
                "timeout_seconds": 900,
            },
        ), patch.object(provider.requests, "Session", return_value=fake_session), patch.object(
            provider,
            "_save_outputs",
            return_value={"success": True},
        ) as save_outputs:
            provider.edit_image_third_party("edit image", ["aW1hZ2U="])

        self.assertEqual(save_outputs.call_args.kwargs["file_prefix"], "gpt_third_party_edit")


if __name__ == "__main__":
    unittest.main()
