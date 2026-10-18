from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend import gpt_model_catalog
from tests.temp_task_db import use_temp_task_db


def fake_jwt(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{raw}.sig"


class GptModelCatalogTest(unittest.TestCase):
    def setUp(self):
        use_temp_task_db(self)

    def test_codex_client_version_reports_newest_known_version(self):
        def resolve(local: str, published: str) -> str:
            gpt_model_catalog._CLIENT_VERSION_CACHE = (0.0, "")
            with patch.object(gpt_model_catalog, "_local_codex_version", return_value=local), \
                 patch.object(gpt_model_catalog, "_published_codex_version", return_value=published):
                return gpt_model_catalog._codex_client_version()

        self.addCleanup(setattr, gpt_model_catalog, "_CLIENT_VERSION_CACHE", (0.0, ""))
        self.assertEqual(resolve("0.118.0", "999.1.0"), "999.1.0")
        # An old local CLI must not hide models that need a newer client.
        self.assertEqual(resolve("0.118.0", ""), gpt_model_catalog.DEFAULT_CODEX_CLIENT_VERSION)
        self.assertEqual(resolve("998.0.0-alpha.1", ""), "998.0.0")

    def test_codex_auth_plan_type_follows_access_token_claims(self):
        auth = {"https://api.openai.com/auth": {"chatgpt_plan_type": "free", "chatgpt_account_id": "acct"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"tokens": {"access_token": fake_jwt(auth), "id_token": ""}}), encoding="utf-8")
            context = gpt_model_catalog._read_auth_context(path, "https://example.test", "managed_codex_oauth", "prolite")

        self.assertEqual(context["plan_type"], "free")

    def test_pool_route_labels_show_supporting_account_count(self):
        response = Mock(status_code=200, text="{}")
        response.json.return_value = {
            "models": [
                {"id": "gpt-6", "label": "GPT-6 Auto", "available_accounts": 2, "account_count": 2},
                {"id": "gpt-6-thinking", "label": "GPT-6 Thinking", "available_accounts": 1, "account_count": 2},
            ],
            "default_model": "gpt-6",
        }
        session = Mock()
        session.get.return_value = response
        cfg = {"enabled": True, "base_url": "http://pool.test", "auth_key": "k"}
        with patch.object(gpt_model_catalog, "get_chatgpt_pool_config", return_value=cfg), \
             patch.object(gpt_model_catalog.requests, "Session", return_value=session):
            _, route = gpt_model_catalog._discover_pool_route(force=True)

        self.assertEqual(
            [(item["id"], item["label"]) for item in route["models"]],
            [("gpt-6", "GPT-6 Auto · 2/2 账号"), ("gpt-6-thinking", "GPT-6 Thinking · 1/2 账号")],
        )
        self.assertEqual(route["default_model"], "gpt-6")

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
