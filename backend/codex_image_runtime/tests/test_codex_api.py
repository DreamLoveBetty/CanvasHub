#!/usr/bin/env python3

from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import requests
from codex_api import CodexAPIError, decode_image_items, extract_images, post_responses, post_responses_stream, resolve_size


class FakeStreamResponse:
    status_code = 200
    text = ""

    def iter_lines(self, chunk_size=1, decode_unicode=False):
        yield b'data: {"type":"response.created","response":{"id":"resp_test","status":"in_progress"}}'
        yield b'data: {"type":"response.image_generation_call.generating","output_index":0,"item_id":"ig_test"}'
        raise requests.exceptions.ChunkedEncodingError("Response ended prematurely")


class FakeJsonResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: dict):
        self.payload = payload

    def json(self):
        return self.payload


class CodexAPITest(unittest.TestCase):
    def test_4k_16_9_maps_to_supported_size(self) -> None:
        self.assertEqual(resolve_size("4k", "16:9"), "3840x2160")

    def test_1k_portrait_stays_above_minimum_pixel_budget(self) -> None:
        self.assertEqual(resolve_size("1k", "9:16"), "608x1088")
        self.assertEqual(resolve_size("1k", "9:21"), "528x1248")

    def test_named_sizes_are_valid_pixel_sizes(self) -> None:
        for size in ("1k", "2k", "4k"):
            for ratio in ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "9:21", "21:9"):
                with self.subTest(size=size, ratio=ratio):
                    resolved = resolve_size(size, ratio)
                    width, height = (int(part) for part in resolved.split("x"))
                    self.assertEqual(width % 16, 0)
                    self.assertEqual(height % 16, 0)
                    self.assertGreaterEqual(width * height, 655_360)
                    self.assertLessEqual(width * height, 8_294_400)
                    self.assertLessEqual(max(width, height), 3840)

    def test_rejects_4096_edge(self) -> None:
        with self.assertRaisesRegex(ValueError, "Maximum edge length"):
            resolve_size("4096x2304", None)

    def test_extracts_images_from_completed_sse_payload(self) -> None:
        raw = base64.b64encode(b"fake-image").decode("ascii")
        event = {
            "type": "response.completed",
            "response": {
                "created_at": 123,
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": raw,
                        "output_format": "png",
                        "size": "1024x1024",
                    }
                ],
            },
        }
        out = extract_images(event)
        self.assertEqual(out["created"], 123)
        self.assertEqual(out["size"], "1024x1024")
        self.assertEqual(decode_image_items(out), [b"fake-image"])

    def test_missing_image_output_is_error(self) -> None:
        with self.assertRaises(CodexAPIError):
            extract_images({"type": "response.completed", "response": {"output": []}})

    def test_missing_image_output_includes_text_output_preview(self) -> None:
        event = {
            "type": "response.completed",
            "response": {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "I cannot generate this image because it may violate safety policy.",
                            }
                        ],
                    }
                ],
            },
        }

        with self.assertRaisesRegex(CodexAPIError, "output_text=I cannot generate"):
            extract_images(event)

    def test_chunked_disconnect_includes_last_sse_event(self) -> None:
        with patch("codex_api.get_auth"), patch("codex_api.requests.post", return_value=FakeStreamResponse()):
            with self.assertRaisesRegex(
                CodexAPIError,
                "last_event=response.image_generation_call.generating.*transport_error=ChunkedEncodingError",
            ):
                post_responses_stream({"tools": [{"type": "image_generation"}]})

    def test_nonstream_response_wraps_response_json_as_completed_event(self) -> None:
        raw = base64.b64encode(b"fake-image").decode("ascii")
        response = FakeJsonResponse(
            {
                "id": "resp_json",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": raw,
                        "output_format": "png",
                        "size": "1024x1024",
                    }
                ],
            }
        )
        captured = {}

        def fake_post(url, headers, json, stream, timeout):
            captured["headers"] = headers
            captured["json"] = json
            captured["stream"] = stream
            return response

        with patch("codex_api.get_auth"), patch("codex_api.requests.post", side_effect=fake_post):
            event = post_responses({"stream": True, "tools": [{"type": "image_generation"}]}, transport_mode="nonstream")

        self.assertEqual(event["type"], "response.completed")
        self.assertFalse(captured["json"]["stream"])
        self.assertFalse(captured["stream"])
        self.assertEqual(captured["headers"]["Accept"], "application/json")
        self.assertEqual(captured["headers"]["OpenAI-Beta"], "responses=experimental")

    def test_stream_then_nonstream_falls_back_only_for_transport_disconnect(self) -> None:
        raw = base64.b64encode(b"fake-image").decode("ascii")
        calls = []

        def fake_post(url, headers, json, stream, timeout):
            calls.append(stream)
            if stream:
                return FakeStreamResponse()
            return FakeJsonResponse(
                {
                    "id": "resp_json",
                    "object": "response",
                    "status": "completed",
                    "output": [
                        {
                            "type": "image_generation_call",
                            "result": raw,
                            "output_format": "png",
                            "size": "1024x1024",
                        }
                    ],
                }
            )

        with patch("codex_api.get_auth"), patch("codex_api.requests.post", side_effect=fake_post):
            event = post_responses({"stream": True, "tools": [{"type": "image_generation"}]}, transport_mode="stream_then_nonstream")

        self.assertEqual(event["type"], "response.completed")
        self.assertEqual(calls, [True, False])


if __name__ == "__main__":
    unittest.main()
