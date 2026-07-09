#!/usr/bin/env python3

from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class ChatgptPoolIntegrationTest(unittest.TestCase):
    def test_config_generates_secret_and_public_config_hides_it(self):
        from backend.app_config import get_chatgpt_pool_config, get_chatgpt_pool_public_config

        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                cfg = get_chatgpt_pool_config(ensure_auth_key=True)
                public = get_chatgpt_pool_public_config()
                saved = json.loads(settings_path.read_text(encoding="utf-8"))

        self.assertTrue(cfg["auth_key"].startswith("sk-local-"))
        self.assertEqual(saved["chatgpt_pool"]["auth_key"], cfg["auth_key"])
        self.assertTrue(public["auth_key_configured"])
        self.assertNotIn("auth_key", public)

    def test_provider_saves_b64_images_to_archive_and_preview(self):
        from backend import provider_chatgpt_pool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            previews = root / "gpt_outputs"
            payload = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")
            with patch.object(provider_chatgpt_pool, "daily_output_dir", return_value=archive), patch.object(
                provider_chatgpt_pool, "GPT_OUTPUT_DIR", previews
            ):
                result = provider_chatgpt_pool.save_chatgpt_pool_outputs(
                    [{"b64_json": payload, "revised_prompt": "revised"}],
                    prompt="original prompt",
                    ratio="1:1",
                    resolution="1k",
                    quality="auto",
                    file_prefix="pool_test",
                )
                image_path = Path(result["image_path"])
                prompt_path = Path(result["prompt_file"])
                self.assertTrue(image_path.exists())
                self.assertTrue(prompt_path.exists())
                self.assertTrue((previews / image_path.name).exists())
                self.assertIn("provider: chatgpt-pool-sidecar", prompt_path.read_text(encoding="utf-8"))
                self.assertEqual(result["provider"], "chatgpt-pool-sidecar")

    def test_provider_records_actual_resolution_when_pool_returns_lower_size(self):
        from backend import provider_chatgpt_pool

        image_bytes = io.BytesIO()
        Image.new("RGB", (941, 1672), "white").save(image_bytes, "PNG")
        payload = base64.b64encode(image_bytes.getvalue()).decode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            previews = root / "gpt_outputs"
            with patch.object(provider_chatgpt_pool, "daily_output_dir", return_value=archive), patch.object(
                provider_chatgpt_pool, "GPT_OUTPUT_DIR", previews
            ):
                result = provider_chatgpt_pool.save_chatgpt_pool_outputs(
                    [{"b64_json": payload}],
                    prompt="prompt",
                    ratio="9:16",
                    resolution="4k",
                    quality="auto",
                    file_prefix="pool_actual_size",
                )

        self.assertEqual(result["requested_resolution"], "4k")
        self.assertEqual(result["actual_resolution"], "1k")
        self.assertEqual(result["effective_resolution"], "1k")
        self.assertTrue(result["resolution_mismatch"])
        self.assertEqual(result["actual_sizes"], [{"width": 941, "height": 1672}])

    def test_system_diagnostics_exposes_pool_status_without_auth_key(self):
        from backend import server

        with patch.object(
            server,
            "_collect_chatgpt_pool_status",
            return_value={"enabled": True, "online": True, "auth_key_configured": True, "stats": {"active": 1}},
        ):
            diagnostics = server._collect_system_diagnostics()

        self.assertIn("chatgpt_pool", diagnostics)
        self.assertTrue(diagnostics["chatgpt_pool"]["auth_key_configured"])
        self.assertNotIn("sk-local-", json.dumps(diagnostics, ensure_ascii=False))

    def test_local_codex_auth_import_normalizes_nested_tokens(self):
        from backend import server

        with tempfile.TemporaryDirectory() as tmp:
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "tokens": {
                            "access_token": "access-token",
                            "refresh_token": "refresh-token",
                            "id_token": "id-token",
                            "account_id": "acct_123",
                        }
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(server, "_chatgpt_pool_safe_auth_candidates", return_value=[auth_path.resolve()]):
                account, source_path = server._chatgpt_pool_build_local_auth_account()

        self.assertEqual(source_path, str(auth_path.resolve()))
        self.assertEqual(account["access_token"], "access-token")
        self.assertEqual(account["refresh_token"], "refresh-token")
        self.assertEqual(account["id_token"], "id-token")
        self.assertEqual(account["account_id"], "acct_123")
        self.assertEqual(account["source_type"], "local_codex_auth")

    def test_clean_oauth_browser_opener_restricts_authorize_url(self):
        from backend import server

        good_url = (
            "https://auth.openai.com/api/accounts/authorize?"
            "client_id=app_2SKx67EdpoN0G6j64rFvigXD&"
            "redirect_uri=https%3A%2F%2Fplatform.openai.com%2Fauth%2Fcallback"
        )
        with patch.object(server.subprocess, "Popen") as popen:
            result = server._chatgpt_pool_open_authorize_url_clean(good_url)

        self.assertTrue(result["ok"])
        self.assertTrue(popen.called)
        with self.assertRaises(RuntimeError):
            server._chatgpt_pool_open_authorize_url_clean("https://example.com/")

    def test_gpt_provider_route_can_start_with_account_pool(self):
        from backend import server

        with patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "generate_image_gpt_codex"
        ) as codex, patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ) as pool:
            result, source, primary_error = server._generate_gpt_with_pool_fallback(
                "task",
                "prompt",
                "1:1",
                "1k",
                "auto",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertEqual(result["gpt_provider_route"], "chatgpt_pool")
        self.assertFalse(codex.called)
        self.assertTrue(pool.called)
        self.assertIn("跳过本地 Codex", primary_error)

    def test_account_pool_smart_route_polishes_prompt_before_generation(self):
        from backend import server

        with patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "get_prompt_skill_config", return_value={"default_output": "full_prompt"}
        ), patch.object(
            server,
            "polish_prompt",
            return_value={
                "full_prompt": "optimized full prompt",
                "compact_prompt": "optimized compact",
                "provider": "gpt_oauth",
                "model": "gpt-5.5",
                "skill": "image_prompt_v7",
                "latency_seconds": 1.25,
            },
        ) as polish, patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ) as pool:
            result, source, _ = server._generate_gpt_with_pool_fallback(
                "task",
                "raw prompt",
                "1:1",
                "1k",
                "auto",
                prompt_mode="smart",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertTrue(polish.called)
        self.assertEqual(pool.call_args.args[0], "optimized full prompt")
        self.assertTrue(result["prompt_optimized"])
        self.assertEqual(result["optimized_prompt"], "optimized full prompt")
        self.assertEqual(result["original_prompt"], "raw prompt")

    def test_account_pool_smart_route_uses_pool_chat_when_local_polish_fails(self):
        from backend import server

        chat_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "full_prompt": "pool chat full prompt",
                                "compact_prompt": "pool chat compact",
                                "warnings": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "model": "auto",
        }
        with patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "get_prompt_skill_config", return_value={"default_output": "full_prompt"}
        ), patch.object(
            server,
            "polish_prompt",
            side_effect=RuntimeError("local codex failed"),
        ), patch.object(
            server,
            "chat_chatgpt_pool",
            return_value={"ok": True, "result": chat_payload},
        ) as chat, patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ) as pool:
            result, source, _ = server._generate_gpt_with_pool_fallback(
                "task",
                "raw prompt",
                "1:1",
                "1k",
                "auto",
                prompt_mode="smart",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertTrue(chat.called)
        self.assertEqual(pool.call_args.args[0], "pool chat full prompt")
        self.assertTrue(result["prompt_optimized"])
        self.assertEqual(result["prompt_optimized_by"], "chatgpt_pool_chat")
        self.assertEqual(result["prompt_polish_fallback"], "chatgpt_pool_chat")
        self.assertIn("local codex failed", result["prompt_polish_error"])

    def test_account_pool_updates_status_after_chat_polish_before_image_generation(self):
        from backend import server

        chat_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "full_prompt": "pool chat full prompt",
                                "compact_prompt": "pool chat compact",
                                "warnings": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "model": "auto",
        }
        statuses = []
        with patch.object(server, "update_task_status", side_effect=lambda *args, **kwargs: statuses.append((args, kwargs))), patch.object(
            server, "send_status_notification"
        ), patch.object(server, "_is_task_canceled", return_value=False), patch.object(
            server, "get_chatgpt_pool_config", return_value={"enabled": True}
        ), patch.object(
            server, "get_prompt_skill_config", return_value={"default_output": "full_prompt"}
        ), patch.object(
            server,
            "polish_prompt",
            side_effect=RuntimeError("local codex failed"),
        ), patch.object(
            server,
            "chat_chatgpt_pool",
            return_value={"ok": True, "result": chat_payload},
        ), patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ):
            result, source, _ = server._generate_gpt_with_pool_fallback(
                "task",
                "raw prompt",
                "1:1",
                "1k",
                "auto",
                prompt_mode="smart",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertTrue(result["prompt_optimized"])
        status_texts = [call[0][2] for call in statuses if len(call[0]) >= 3]
        self.assertIn("本地润色失败，正在用账号池 chat 兜底润色...", status_texts)
        self.assertIn("正在调用 ChatGPT 账号池生成图片...", status_texts)

    def test_account_pool_faithful_route_skips_prompt_polish(self):
        from backend import server

        with patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "polish_prompt"
        ) as polish, patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ) as pool:
            result, source, _ = server._generate_gpt_with_pool_fallback(
                "task",
                "raw prompt",
                "1:1",
                "1k",
                "auto",
                prompt_mode="faithful",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertFalse(polish.called)
        self.assertEqual(pool.call_args.args[0], "raw prompt")
        self.assertNotIn("prompt_optimized", result)

    def test_web_search_prompt_mode_enriches_before_image_generation(self):
        from backend import server

        chat_payload = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "full_prompt": "search enriched image prompt",
                                "compact_prompt": "search compact",
                                "warnings": [],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "model": "auto",
        }
        search_payload = {
            "conversation_id": "conv-search",
            "answer": "检索结论：青行灯常见视觉元素包括灯、青蓝色调和怪谈氛围。",
            "sources": [{"title": "source", "url": "https://example.com", "snippet": "visual reference"}],
        }
        with patch.object(server, "update_task_status"), patch.object(server, "send_status_notification"), patch.object(
            server, "_is_task_canceled", return_value=False
        ), patch.object(server, "get_chatgpt_pool_config", return_value={"enabled": True}), patch.object(
            server, "get_prompt_skill_config", return_value={"default_output": "full_prompt"}
        ), patch.object(
            server,
            "search_chatgpt_pool",
            return_value={"ok": True, "model": "gpt-5-5", "result": search_payload},
        ) as search, patch.object(
            server,
            "chat_chatgpt_pool",
            return_value={"ok": True, "result": chat_payload},
        ) as chat, patch.object(
            server,
            "generate_image_gpt_pool",
            return_value={"success": True, "image_path": "/tmp/out.png", "image_paths": ["/tmp/out.png"]},
        ) as pool, patch.object(
            server,
            "generate_image_gpt_codex",
            return_value={"success": False, "error": "codex down"},
        ):
            result, source, _ = server._generate_gpt_with_pool_fallback(
                "task",
                "青行灯海报",
                "1:1",
                "1k",
                "auto",
                prompt_mode="web_search",
                gpt_provider_route="chatgpt_pool",
            )

        self.assertEqual(source, "chatgpt_pool")
        self.assertTrue(search.called)
        self.assertTrue(chat.called)
        self.assertEqual(pool.call_args.args[0], "search enriched image prompt")
        self.assertEqual(result["prompt_mode"], "web_search")
        self.assertEqual(result["prompt_optimized_by"], "chatgpt_pool_search")
        self.assertEqual(result["web_search_conversation_id"], "conv-search")
        self.assertEqual(result["web_search_sources"][0]["url"], "https://example.com")

    def test_pool_provider_wraps_faithful_prompt_before_sidecar_call(self):
        from backend import provider_chatgpt_pool

        class FakeResponse:
            status_code = 200
            text = '{"data":[]}'

            def json(self):
                return {"data": []}

        captured = {}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None):
                captured["payload"] = json or {}
                return FakeResponse()

        with patch.object(
            provider_chatgpt_pool,
            "get_chatgpt_pool_config",
            return_value={
                "enabled": True,
                "auth_key": "sk-local-test",
                "base_url": "http://127.0.0.1:18080",
                "generation_model": "gpt-image-2",
                "timeout_seconds": 10,
            },
        ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()):
            provider_chatgpt_pool.generate_image_gpt_pool(
                "keep exact subject",
                prompt_mode="faithful",
            )

        prompt = captured["payload"]["prompt"]
        self.assertEqual(prompt, "keep exact subject")
        self.assertNotIn("literal source brief", prompt)
        self.assertEqual(captured["payload"]["model"], "gpt-image-2")

    def test_pool_provider_sends_sidecar_timeout_with_http_buffer(self):
        from backend import provider_chatgpt_pool

        class FakeResponse:
            status_code = 200
            text = '{"data":[]}'

            def json(self):
                return {"data": []}

        captured = {}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None):
                captured["payload"] = json or {}
                captured["timeout"] = timeout
                return FakeResponse()

        with patch.object(
            provider_chatgpt_pool,
            "get_chatgpt_pool_config",
            return_value={
                "enabled": True,
                "auth_key": "sk-local-test",
                "base_url": "http://127.0.0.1:18080",
                "generation_model": "gpt-image-2",
                "timeout_seconds": 420,
            },
        ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()):
            provider_chatgpt_pool.generate_image_gpt_pool("draw something")

        self.assertEqual(captured["payload"]["timeout_seconds"], 420)
        self.assertEqual(captured["timeout"], 480)

    def test_pool_provider_allows_eight_images_and_expands_http_timeout(self):
        from backend import provider_chatgpt_pool

        image_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")

        class FakeResponse:
            status_code = 200
            text = '{"data":[]}'

            def json(self):
                return {"data": [{"b64_json": image_b64} for _ in range(8)]}

        captured = {}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None):
                captured["payload"] = json or {}
                captured["timeout"] = timeout
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            previews = Path(tmp) / "previews"
            with patch.object(
                provider_chatgpt_pool,
                "get_chatgpt_pool_config",
                return_value={
                    "enabled": True,
                    "auth_key": "sk-local-test",
                    "base_url": "http://127.0.0.1:18080",
                    "generation_model": "gpt-image-2",
                    "timeout_seconds": 420,
                },
            ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()), patch.object(
                provider_chatgpt_pool, "daily_output_dir", return_value=archive
            ), patch.object(provider_chatgpt_pool, "GPT_OUTPUT_DIR", previews):
                result = provider_chatgpt_pool.generate_image_gpt_pool("draw something", image_count=99)

        self.assertEqual(captured["payload"]["n"], 8)
        self.assertEqual(captured["timeout"], 3420)
        self.assertEqual(result["image_count"], 8)
        self.assertEqual(result["requested_image_count"], 8)

    def test_pool_provider_stream_saves_first_image_before_partial_errors(self):
        from backend import provider_chatgpt_pool

        image_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode("ascii")

        class FakeResponse:
            status_code = 200
            text = ""
            headers = {"content-type": "text/event-stream"}

            def iter_lines(self, decode_unicode=False):
                events = [
                    {"type": "started", "requested": 2, "worker_count": 2},
                    {"type": "image", "index": 0, "item": {"b64_json": image_b64, "revised_prompt": "rev"}},
                    {"type": "error", "index": 1, "error": "image 2 timed out"},
                    {"type": "final", "data": [{"b64_json": image_b64}], "partial_errors": [{"index": 1, "error": "image 2 timed out"}]},
                ]
                for event in events:
                    line = "data: " + json.dumps(event)
                    yield line if decode_unicode else line.encode("utf-8")

        captured = {}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None, stream=False):
                captured["payload"] = json or {}
                captured["stream"] = stream
                return FakeResponse()

        callbacks = []

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            previews = Path(tmp) / "previews"
            with patch.object(
                provider_chatgpt_pool,
                "get_chatgpt_pool_config",
                return_value={
                    "enabled": True,
                    "auth_key": "sk-local-test",
                    "base_url": "http://127.0.0.1:18080",
                    "generation_model": "gpt-image-2",
                    "timeout_seconds": 420,
                },
            ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()), patch.object(
                provider_chatgpt_pool, "daily_output_dir", return_value=archive
            ), patch.object(provider_chatgpt_pool, "GPT_OUTPUT_DIR", previews):
                result = provider_chatgpt_pool.generate_image_gpt_pool(
                    "draw something",
                    image_count=2,
                    on_image_saved=lambda partial, saved, total: callbacks.append((partial, saved, total)),
                )
                saved_path_exists = Path(result["image_path"]).exists()

        self.assertTrue(captured["stream"])
        self.assertTrue(captured["payload"]["stream"])
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["requested_image_count"], 2)
        self.assertIn("partial_errors", result)
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(callbacks[0][1:], (1, 2))
        self.assertEqual(len(callbacks[0][0]["image_paths"]), 1)
        self.assertTrue(saved_path_exists)

    def test_pool_provider_does_not_retry_json_after_stream_generation_error(self):
        from backend import provider_chatgpt_pool

        class FakeResponse:
            status_code = 200
            text = ""
            headers = {"content-type": "text/event-stream"}

            def iter_lines(self, decode_unicode=False):
                events = [
                    {"type": "started", "requested": 1, "worker_count": 1},
                    {"type": "final", "error": "ChatGPT conversation finished without image output"},
                ]
                for event in events:
                    line = "data: " + json.dumps(event)
                    yield line if decode_unicode else line.encode("utf-8")

        calls = []

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None, stream=False):
                calls.append({"stream": stream, "payload": json or {}})
                return FakeResponse()

        with patch.object(
            provider_chatgpt_pool,
            "get_chatgpt_pool_config",
            return_value={
                "enabled": True,
                "auth_key": "sk-local-test",
                "base_url": "http://127.0.0.1:18080",
                "generation_model": "gpt-image-2",
                "timeout_seconds": 420,
            },
        ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()):
            result = provider_chatgpt_pool.generate_image_gpt_pool("draw something")

        self.assertFalse(result["success"])
        self.assertIn("without image output", result["error"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["stream"])

    def test_pool_provider_calls_image_edits_route_and_saves_result(self):
        from backend import provider_chatgpt_pool

        image_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\nedited").decode("ascii")

        class FakeResponse:
            status_code = 200
            text = '{"data":[]}'

            def json(self):
                return {"data": [{"b64_json": image_b64, "revised_prompt": "edited"}]}

        captured = {}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None):
                captured["url"] = url
                captured["payload"] = json or {}
                captured["timeout"] = timeout
                return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"
            previews = Path(tmp) / "previews"
            with patch.object(
                provider_chatgpt_pool,
                "get_chatgpt_pool_config",
                return_value={
                    "enabled": True,
                    "auth_key": "sk-local-test",
                    "base_url": "http://127.0.0.1:18080",
                    "generation_model": "gpt-image-2",
                    "timeout_seconds": 420,
                },
            ), patch.object(provider_chatgpt_pool.requests, "Session", return_value=FakeSession()), patch.object(
                provider_chatgpt_pool, "daily_output_dir", return_value=archive
            ), patch.object(provider_chatgpt_pool, "GPT_OUTPUT_DIR", previews):
                result = provider_chatgpt_pool.edit_image_gpt_pool(
                    "change color",
                    ["source-b64"],
                    ratio="1:1",
                    resolution="1k",
                    quality="medium",
                    mask="mask-b64",
                )
                saved_path_exists = Path(result["image_path"]).exists()

        self.assertTrue(captured["url"].endswith("/v1/images/edits"))
        self.assertEqual(captured["payload"]["image"], ["source-b64"])
        self.assertEqual(captured["payload"]["mask"], "mask-b64")
        self.assertEqual(captured["payload"]["quality"], "medium")
        self.assertEqual(captured["timeout"], 480)
        self.assertEqual(result["image_count"], 1)
        self.assertEqual(result["gpt_provider_route"], "chatgpt_pool")
        self.assertTrue(saved_path_exists)

    def test_gpt_edit_route_uses_account_pool_when_selected(self):
        from backend import database
        from backend import server

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.db"
            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                server.create_task(
                    "gpt_edit_pool_test",
                    "换成红色背景",
                    {"gpt_provider_route": "chatgpt_pool"},
                    status="queued",
                    task_type="gpt-edit",
                )
                with patch.object(
                    server,
                    "edit_image_gpt_pool",
                    return_value={
                        "success": True,
                        "image_path": "/tmp/gpt_pool_edit.png",
                        "image_paths": ["/tmp/gpt_pool_edit.png"],
                        "gpt_provider_route": "chatgpt_pool",
                    },
                ) as pool_edit, patch.object(server, "edit_image_gpt_codex") as codex_edit, patch.object(
                    server, "send_telegram_result", return_value=True
                ), patch.object(server, "send_status_notification"):
                    server.process_gpt_edit_task(
                        "gpt_edit_pool_test",
                        "换成红色背景",
                        ["source-b64"],
                        "1:1",
                        "1k",
                        quality="auto",
                        gpt_provider_route="chatgpt_pool",
                    )

                task = server.get_task("gpt_edit_pool_test")

        self.assertTrue(pool_edit.called)
        self.assertFalse(codex_edit.called)
        self.assertEqual(task["status"], "succeeded")
        self.assertEqual(task["params"]["gpt_provider_route"], "chatgpt_pool")
        self.assertIn("chatgpt_pool_edit", json.dumps(task["params"].get("route_trace"), ensure_ascii=False))

    def test_server_coerces_gpt_image_count_to_eight(self):
        from backend import server

        self.assertEqual(server._coerce_gpt_image_count({"image_count": 99}), 8)
        self.assertEqual(server._coerce_gpt_image_count({}, "生成八张海报"), 8)
        self.assertEqual(server._coerce_gpt_image_count({}, "生成十张海报"), 1)

    def test_pool_search_and_chat_404_explain_stale_sidecar(self):
        from backend import provider_chatgpt_pool

        class MissingRouteResponse:
            status_code = 404
            text = '{"detail":"Not Found"}'

            def json(self):
                return {"detail": "Not Found"}

        class FakeSession:
            trust_env = False

            def post(self, url, headers=None, json=None, timeout=None):
                return MissingRouteResponse()

        pool_config = {
            "enabled": True,
            "auth_key": "sk-local-test",
            "base_url": "http://127.0.0.1:18080",
            "timeout_seconds": 10,
        }
        with patch.object(provider_chatgpt_pool, "get_chatgpt_pool_config", return_value=pool_config), patch.object(
            provider_chatgpt_pool.requests, "Session", return_value=FakeSession()
        ):
            search_result = provider_chatgpt_pool.search_chatgpt_pool("联网查一下")
            chat_result = provider_chatgpt_pool.chat_chatgpt_pool([{"role": "user", "content": "润色一下"}])

        self.assertFalse(search_result["ok"])
        self.assertIn("未加载 /v1/search 接口", search_result["error"])
        self.assertFalse(chat_result["ok"])
        self.assertIn("未加载 /v1/chat/completions 接口", chat_result["error"])

    def test_editable_file_task_persists_manifest_and_task_result(self):
        from backend import database
        from backend import editable_file_service as svc
        from backend import server

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "tasks.db"
            editable_root = tmp_path / "GPT Images"
            primary_b64 = base64.b64encode(b"pptx").decode("ascii")
            zip_b64 = base64.b64encode(b"zip").decode("ascii")

            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                server.create_task(
                    "gpt_file_test",
                    "测试 PPT 方案",
                    {"task_type": "ppt", "gpt_provider_route": "chatgpt_pool"},
                    status="queued",
                    task_type="gpt-file",
                )
                with patch.object(svc, "EDITABLE_ROOT", editable_root), patch.object(
                    svc, "PPT_ROOT", editable_root / "PPT"
                ), patch.object(svc, "find_libreoffice", return_value=""), patch.object(
                    server,
                    "generate_editable_file_gpt_pool",
                    return_value={
                        "success": True,
                        "conversation_id": "conv-test",
                        "primary": {"filename": "test.pptx", "b64": primary_b64},
                        "zip": {"filename": "test.zip", "b64": zip_b64},
                    },
                ), patch.object(server, "send_telegram", return_value=True), patch.object(
                    server, "send_status_notification"
                ):
                    server.process_gpt_editable_file_task("gpt_file_test", "ppt", "测试 PPT 方案")

                task = server.get_task("gpt_file_test")
                manifest_path = Path(task["params"]["file_manifest"]["manifest_path"])

                self.assertEqual(task["status"], "succeeded")
                self.assertEqual(task["type"], "gpt-file")
                self.assertTrue(task["result_file"].startswith("PPT/"))
                self.assertEqual(len(task["result_files"]), 2)
                manifest = task["params"]["file_manifest"]
                self.assertEqual(manifest["artifact_type"], "ppt")
                self.assertEqual(manifest["conversation_id"], "conv-test")
                self.assertEqual(manifest["preview"]["status"], "missing_dependency")
                self.assertTrue(manifest_path.exists())

    def test_editable_file_task_respects_telegram_disabled(self):
        from backend import database
        from backend import editable_file_service as svc
        from backend import server

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "tasks.db"
            editable_root = tmp_path / "GPT Images"
            primary_b64 = base64.b64encode(b"pptx").decode("ascii")

            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                server.create_task(
                    "gpt_file_no_tg",
                    "测试 PPT 方案",
                    {"task_type": "ppt", "gpt_provider_route": "chatgpt_pool", "telegram_enabled": False},
                    status="queued",
                    task_type="gpt-file",
                )
                with patch.object(svc, "EDITABLE_ROOT", editable_root), patch.object(
                    svc, "PPT_ROOT", editable_root / "PPT"
                ), patch.object(svc, "find_libreoffice", return_value=""), patch.object(
                    server,
                    "generate_editable_file_gpt_pool",
                    return_value={
                        "success": True,
                        "conversation_id": "conv-test",
                        "primary": {"filename": "test.pptx", "b64": primary_b64},
                    },
                ), patch.object(server, "send_telegram") as send_mock, patch.object(
                    server, "send_status_notification"
                ):
                    server.process_gpt_editable_file_task("gpt_file_no_tg", "ppt", "测试 PPT 方案", telegram_enabled=False)

                task = server.get_task("gpt_file_no_tg")
                self.assertEqual(task["status"], "succeeded")
                send_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
