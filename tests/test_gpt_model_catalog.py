from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from backend import gpt_model_catalog


class GptModelCatalogTest(unittest.TestCase):
    def test_codex_reasoning_is_limited_to_selected_model(self):
        route = {
            "available": True,
            "models": [
                {
                    "id": "gpt-5.6-luna",
                    "reasoning_efforts": ["low", "medium", "high", "xhigh", "max"],
                    "default_reasoning_effort": "medium",
                }
            ],
            "default_model": "gpt-5.6-luna",
            "model_role": "responses_main_model",
            "image_engine": {"id": "gpt-image-2", "label": "GPT Image 2"},
            "source": "test",
        }
        with patch.object(gpt_model_catalog, "discover_codex_route", return_value=route):
            resolved = gpt_model_catalog.resolve_route_model(
                "codex",
                "gpt-5.6-luna",
                reasoning_effort="ultra",
            )

        self.assertEqual(resolved["model"], "gpt-5.6-luna")
        self.assertEqual(resolved["reasoning_effort"], "medium")
        self.assertTrue(resolved["reasoning_adapted"])

    def test_codex_unavailable_route_has_no_compatibility_fallbacks(self):
        route = {
            "available": False,
            "models": [{"id": "gpt-5.5", "image_generation": False}],
            "default_model": "gpt-5.5",
        }
        with patch.object(gpt_model_catalog, "discover_codex_route", return_value=route):
            self.assertEqual(gpt_model_catalog.codex_fallback_models("gpt-5.6-sol"), [])

    def test_pool_adapts_codex_model_to_discovered_web_model(self):
        route = {
            "available": True,
            "models": [{"id": "gpt-5-5", "reasoning_efforts": []}],
            "default_model": "gpt-5-5",
            "model_role": "web_main_model",
            "image_engine": {"id": "chatgpt-image", "label": "ChatGPT Image"},
            "source": "test",
        }
        with patch.object(gpt_model_catalog, "discover_pool_route", return_value=route):
            resolved = gpt_model_catalog.resolve_route_model(
                "chatgpt_pool",
                "gpt-5.6-sol",
                reasoning_effort="high",
            )

        self.assertEqual(resolved["model"], "gpt-5-5")
        self.assertEqual(resolved["reasoning_effort"], "none")
        self.assertEqual(resolved["image_engine"]["label"], "ChatGPT Image")
        self.assertTrue(resolved["adapted"])

    def test_unavailable_codex_route_skips_provider_and_uses_pool_model(self):
        from backend import server

        def resolve(route, requested_model, **_kwargs):
            if route == "codex":
                return {
                    "route": "codex",
                    "model": requested_model,
                    "available": False,
                    "warning": "Codex image generation unavailable",
                    "reasoning_effort": "medium",
                    "model_role": "responses_main_model",
                    "image_engine": {"id": "gpt-image-2", "label": "GPT Image 2"},
                    "source": "test",
                }
            return {
                "route": "chatgpt_pool",
                "model": "gpt-5-5",
                "available": True,
                "adapted": True,
                "reasoning_effort": "none",
                "model_role": "web_main_model",
                "image_engine": {"id": "chatgpt-image", "label": "ChatGPT Image"},
                "source": "test",
            }

        codex = Mock()
        with patch.object(server, "resolve_route_model", side_effect=resolve), patch.object(
            server, "generate_image_gpt_codex", codex
        ), patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "_append_task_route_trace"
        ), patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ):
            result, source, primary_error = server._generate_gpt_with_pool_fallback(
                "task",
                "prompt",
                "1:1",
                "1k",
                "auto",
                prompt_mode="faithful",
                main_model="gpt-5.6-sol",
                reasoning_effort="ultra",
                gpt_provider_route="codex",
            )

        codex.assert_not_called()
        self.assertEqual(source, "chatgpt_pool")
        self.assertIn("unavailable", primary_error)
        self.assertEqual(result["main_model"], "gpt-5-5")
        self.assertEqual(result["requested_main_model"], "gpt-5.6-sol")
        self.assertEqual(result["requested_gpt_provider_route"], "codex")
        self.assertEqual(result["gpt_provider_route"], "chatgpt_pool")
        self.assertEqual(result["reasoning_effort"], "none")
        self.assertEqual(result["image_engine_label"], "ChatGPT Image")


if __name__ == "__main__":
    unittest.main()
