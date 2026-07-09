#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import generate_image


class GenerateImageTest(unittest.TestCase):
    def _fake_images_response(self, data: str = "ZmFrZS1pbWFnZQ==", count: int = 1) -> dict:
        return {
            "created": 123,
            "data": [
                {
                    "b64_json": data,
                }
                for _ in range(count)
            ],
            "output_format": "png",
            "size": "2048x1152",
        }

    def _fake_image_event(self, data: str = "ZmFrZS1pbWFnZQ==") -> dict:
        return {
            "type": "response.completed",
            "response": {
                "created_at": 123,
                "output": [
                    {
                        "type": "image_generation_call",
                        "result": data,
                        "output_format": "png",
                        "size": "2048x1152",
                    }
                ],
            },
        }

    def test_multi_image_count_uses_external_single_image_calls(self) -> None:
        captured_payloads = []

        def fake_post(endpoint, payload, **kwargs):
            self.assertEqual(endpoint, "generations")
            captured_payloads.append(payload)
            return self._fake_images_response(count=payload.get("n") or 1)

        with patch.object(generate_image, "post_codex_images", side_effect=fake_post):
            images = generate_image.generate(
                "test prompt",
                size="2k",
                ratio="16:9",
                quality="auto",
                background="auto",
                moderation="low",
                output_format="png",
                output_compression=100,
                n=8,
            )

        self.assertEqual(images, [b"fake-image"] * 8)
        self.assertEqual(len(captured_payloads), 1)
        payload = captured_payloads[0]
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertEqual(payload["size"], "2048x1152")
        self.assertEqual(payload["prompt"], "test prompt")
        self.assertEqual(payload["n"], 8)

    def test_images_api_failure_falls_back_to_responses_loop(self) -> None:
        captured_responses_payloads = []

        def fake_response_post(payload, **kwargs):
            captured_responses_payloads.append(payload)
            if len(captured_responses_payloads) == 4:
                raise RuntimeError("temporary provider failure")
            return self._fake_image_event()

        with patch.object(generate_image, "post_codex_images", side_effect=RuntimeError("images api failed")), patch.object(
            generate_image, "post_responses", side_effect=fake_response_post
        ):
            images = generate_image.generate(
                "test prompt",
                size="2k",
                ratio="16:9",
                quality="auto",
                background="auto",
                moderation="low",
                output_format="png",
                output_compression=100,
                n=8,
            )

        self.assertEqual(images, [b"fake-image"] * 3)
        self.assertEqual(len(captured_responses_payloads), 4)

    def test_multi_image_first_failure_still_raises(self) -> None:
        with patch.object(generate_image, "post_codex_images", side_effect=RuntimeError("images api failed")), patch.object(
            generate_image, "post_responses", side_effect=RuntimeError("provider failed")
        ):
            with self.assertRaises(RuntimeError):
                generate_image.generate(
                    "test prompt",
                    size="2k",
                    ratio="16:9",
                    quality="auto",
                    background="auto",
                    moderation="low",
                    output_format="png",
                    output_compression=100,
                    n=8,
                )


if __name__ == "__main__":
    unittest.main()
