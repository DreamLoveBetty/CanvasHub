#!/usr/bin/env python3
"""Local Codex request endpoint: config, settings patch, runtime routing, provider payload."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import provider_gpt_codex
from backend.app_config import DEFAULT_GPT_REQUEST_ENDPOINT, get_gpt_provider_config
from backend.server import _collect_gpt_runtime_config, _sanitize_gpt_provider_patch

# provider_gpt_codex puts the runtime scripts directory on sys.path.
import edit_image  # noqa: E402
import generate_image  # noqa: E402

FAKE_B64 = "ZmFrZS1pbWFnZQ=="


def fake_images_response(count: int = 1) -> dict:
    return {"created": 1, "data": [{"b64_json": FAKE_B64} for _ in range(count)], "output_format": "png"}


def fake_responses_event() -> dict:
    return {
        "type": "response.completed",
        "response": {
            "created_at": 1,
            "output": [{"type": "image_generation_call", "result": FAKE_B64, "output_format": "png"}],
        },
    }


GENERATE_ARGS = dict(
    size="1k",
    ratio="1:1",
    quality="auto",
    background="auto",
    moderation="auto",
    output_format="png",
    output_compression=100,
    n=1,
)


class RequestEndpointConfigTest(unittest.TestCase):
    def load_config(self, settings: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(json.dumps(settings), encoding="utf-8")
            env = {"APP_SETTINGS_PATH": str(settings_path), "GPT_PROVIDER_REQUEST_ENDPOINT": ""}
            with patch.dict(os.environ, env, clear=False):
                return get_gpt_provider_config()

    def test_default_endpoint_is_images(self) -> None:
        cfg = self.load_config({})

        self.assertEqual(DEFAULT_GPT_REQUEST_ENDPOINT, "images")
        self.assertEqual(cfg["request_endpoint"], "images")
        self.assertEqual(cfg["allowed_request_endpoints"], ["images", "responses"])

    def test_endpoint_can_be_loaded_from_settings(self) -> None:
        cfg = self.load_config({"gpt_provider": {"request_endpoint": "responses"}})

        self.assertEqual(cfg["request_endpoint"], "responses")

    def test_invalid_endpoint_falls_back_to_default(self) -> None:
        cfg = self.load_config({"gpt_provider": {"request_endpoint": "chat"}})

        self.assertEqual(cfg["request_endpoint"], DEFAULT_GPT_REQUEST_ENDPOINT)

    def test_sanitize_patch_accepts_only_known_endpoints(self) -> None:
        self.assertEqual(_sanitize_gpt_provider_patch({"request_endpoint": "Responses"})["request_endpoint"], "responses")
        self.assertNotIn("request_endpoint", _sanitize_gpt_provider_patch({"request_endpoint": "chat"}))

    def test_runtime_config_exposes_endpoint(self) -> None:
        with patch("backend.server.get_gpt_provider_config", return_value={"request_endpoint": "responses"}):
            payload = _collect_gpt_runtime_config()["gpt_provider"]

        self.assertEqual(payload["request_endpoint"], "responses")
        self.assertEqual(payload["allowed_request_endpoints"], ["images", "responses"])


class CatalogEndpointTest(unittest.TestCase):
    def test_codex_route_reports_live_endpoint_without_touching_cache(self) -> None:
        from backend import gpt_model_catalog

        cached_codex = {"available": True, "models": []}
        with patch.object(gpt_model_catalog, "discover_codex_route", return_value=cached_codex), patch.object(
            gpt_model_catalog, "discover_pool_route", return_value={"models": []}
        ), patch.object(gpt_model_catalog, "get_gpt_provider_config", side_effect=[{"request_endpoint": "images"}, {"request_endpoint": "responses"}]):
            first = gpt_model_catalog.get_gpt_model_catalog()
            second = gpt_model_catalog.get_gpt_model_catalog()

        self.assertEqual(first["routes"]["codex"]["request_endpoint"], "images")
        self.assertEqual(second["routes"]["codex"]["request_endpoint"], "responses")
        self.assertNotIn("request_endpoint", cached_codex)
        self.assertNotIn("request_endpoint", second["routes"]["chatgpt_pool"])


class RuntimeEndpointRoutingTest(unittest.TestCase):
    def test_generate_images_endpoint_never_calls_responses(self) -> None:
        with patch.object(generate_image, "post_codex_images", side_effect=RuntimeError("HTTP 400")) as post_images, patch.object(
            generate_image, "post_responses"
        ) as post_responses:
            with self.assertRaises(RuntimeError):
                generate_image.generate_with_metadata("p", **GENERATE_ARGS, request_endpoint="images", timeout=123)

        self.assertEqual(post_images.call_args.kwargs["timeout"], 123)
        post_responses.assert_not_called()

    def test_generate_responses_endpoint_never_calls_images(self) -> None:
        with patch.object(generate_image, "post_codex_images") as post_images, patch.object(
            generate_image, "post_responses", return_value=fake_responses_event()
        ) as post_responses:
            images = generate_image.generate_with_metadata(
                "p", **GENERATE_ARGS, request_endpoint="responses", transport_mode="nonstream", timeout=321
            )

        self.assertEqual(len(images), 1)
        post_images.assert_not_called()
        self.assertEqual(post_responses.call_args.kwargs["timeout"], 321)
        self.assertEqual(post_responses.call_args.kwargs["transport_mode"], "nonstream")

    def test_edit_follows_selected_endpoint_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"\x89PNG\r\n\x1a\nfake")
            edit_args = dict(
                image_paths=[str(source)],
                mask_path=None,
                size="1k",
                ratio="1:1",
                quality="auto",
                background="auto",
                moderation="auto",
                output_format="png",
                output_compression=100,
            )
            with patch.object(edit_image, "post_codex_images", side_effect=RuntimeError("HTTP 400")), patch.object(
                edit_image, "post_responses"
            ) as post_responses:
                with self.assertRaises(RuntimeError):
                    edit_image.edit_image_with_metadata("p", **edit_args, request_endpoint="images")
            post_responses.assert_not_called()

            with patch.object(edit_image, "post_codex_images") as post_images, patch.object(
                edit_image, "post_responses", return_value=fake_responses_event()
            ):
                images = edit_image.edit_image_with_metadata("p", **edit_args, request_endpoint="responses", timeout=200)
            post_images.assert_not_called()
            self.assertEqual(len(images), 1)


class ProviderEndpointPayloadTest(unittest.TestCase):
    def run_generate(self, endpoint: str, runner) -> dict:
        with patch.object(provider_gpt_codex, "_run_provider_with_total_timeout", side_effect=runner), patch.object(
            provider_gpt_codex, "_new_gpt_output_batch", return_value={"output_paths": []}
        ):
            return provider_gpt_codex.generate_image_gpt_codex(
                "prompt",
                main_model="gpt-5.5",
                request_endpoint=endpoint,
                total_timeout_seconds=300,
            )

    def test_payload_carries_endpoint_and_unified_timeout(self) -> None:
        calls = []

        def runner(label, mode, payload, timeout_seconds, **kwargs):
            calls.append((payload, timeout_seconds))
            return []

        self.run_generate("responses", runner)

        payload, timeout_seconds = calls[0]
        self.assertEqual(payload["request_endpoint"], "responses")
        self.assertEqual(payload["timeout"], 300)
        self.assertEqual(timeout_seconds, 300)

    def test_images_endpoint_skips_main_model_compatibility_fallback(self) -> None:
        calls = []

        def runner(label, mode, payload, timeout_seconds, **kwargs):
            calls.append(payload["main_model"])
            raise RuntimeError("The 'gpt-5.5' model is not supported when using Codex with a ChatGPT account.")

        result = self.run_generate("images", runner)

        self.assertEqual(calls, ["gpt-5.5"])
        self.assertIn("not supported", result["error"])


if __name__ == "__main__":
    unittest.main()
