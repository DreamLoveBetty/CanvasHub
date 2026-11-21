#!/usr/bin/env python3

from __future__ import annotations

import unittest

from backend import provider_change2pro as change2pro
from backend.api_client import (
    _chat_completions_url,
    _extract_image_from_openai_chat,
    _format_http_error,
    _normalize_openai_chat_model,
    _openai_chat_payload,
    _classify_transport_error,
    _is_retryable_request_exception,
    _uses_openai_chat_endpoint,
)
import requests
from backend.generation_tracking import translate_generation_error
from sidecars.google_pool.errors import GoogleError
from sidecars.google_pool.upstream import GoogleUpstream


ONE_BY_ONE_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMB/6X6Z9sAAAAASUVORK5CYII="
)


class GoogleApiErrorFormattingTest(unittest.TestCase):
    def test_insufficient_quota_403_is_user_readable(self) -> None:
        body = (
            '{"error":{"message":"chat pre-consumed quota failed, '
            'user quota: $0.189356, need quota: $0.397200",'
            '"type":"new_api_error","param":"","code":"local:insufficient_quota"}}'
        )

        message, error_type = _format_http_error(403, body)

        self.assertIn("额度不足", message)
        self.assertIn("$0.189356", message)
        self.assertIn("$0.397200", message)
        self.assertEqual(error_type, "quota")

    def test_generic_http_error_keeps_status_and_message(self) -> None:
        body = '{"error":{"message":"forbidden model"}}'

        message, error_type = _format_http_error(403, body)

        self.assertEqual(message, "HTTP 错误 403：forbidden model")
        self.assertEqual(error_type, "http_403")

    def test_top_level_openai_compatible_error_keeps_message(self) -> None:
        body = '{"code":"API_KEY_REQUIRED","message":"API key is required"}'

        message, error_type = _format_http_error(401, body)

        self.assertEqual(message, "HTTP 错误 401：API key is required")
        self.assertEqual(error_type, "http_401")

    def test_change2pro_root_uses_documented_google_contract(self) -> None:
        self.assertTrue(change2pro.uses_documented_google_api("https://api.change2pro.com"))
        self.assertFalse(_uses_openai_chat_endpoint("https://api.change2pro.com"))
        self.assertEqual(
            change2pro.google_url(
                "https://api.change2pro.com",
                "gemini-3.1-flash-image",
                stream=False,
            ),
            "https://api.change2pro.com/v1beta/models/gemini-3.1-flash-image:generateContent",
        )
        self.assertTrue(_uses_openai_chat_endpoint("https://provider.example"))
        self.assertEqual(
            _chat_completions_url("https://provider.example/v1"),
            "https://provider.example/v1/chat/completions",
        )
        self.assertFalse(_uses_openai_chat_endpoint("https://provider.example/v1beta"))

    def test_openai_chat_image_extractor_accepts_data_uri_content(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": f"![image](data:image/png;base64,{ONE_BY_ONE_PNG_B64})"
                    }
                }
            ]
        }

        image = _extract_image_from_openai_chat(payload)

        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_openai_chat_image_extractor_accepts_b64_json(self) -> None:
        payload = {"choices": [{"message": {"images": [{"b64_json": ONE_BY_ONE_PNG_B64}]}}]}

        image = _extract_image_from_openai_chat(payload)

        self.assertTrue(image.startswith(b"\x89PNG"))

    def test_openai_chat_payload_matches_third_party_contract(self) -> None:
        payload = _openai_chat_payload(
            "",
            "hello",
            google_image_config={"image_size": "4K", "aspect_ratio": "16:9"},
        )

        self.assertEqual(payload["model"], "gemini-3.1-flash-image")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertEqual(
            payload["extra_body"],
            {
                "google": {
                    "image_config": {
                        "image_size": "4K",
                        "aspect_ratio": "16:9",
                    }
                }
            },
        )
        self.assertNotIn("modalities", payload)
        self.assertNotIn("image_size", payload)
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("size", payload)

    def test_openai_chat_model_keeps_explicit_pro_parameter(self) -> None:
        self.assertEqual(
            _normalize_openai_chat_model("google/gemini-3-pro-image-preview"),
            "gemini-3-pro-image",
        )

    def test_openai_chat_model_maps_preview_aliases_to_new_names(self) -> None:
        self.assertEqual(_normalize_openai_chat_model("gemini-3.1-flash-image-preview"), "gemini-3.1-flash-image")

    def test_ssl_eof_is_retryable_transport_error(self) -> None:
        err = requests.exceptions.SSLError("HTTPSConnectionPool ... SSLEOFError")

        self.assertEqual(_classify_transport_error(err, 0), "ssl_eof")
        self.assertTrue(_is_retryable_request_exception(err))

    def test_generation_error_translation_maps_gemini_prohibited_content(self) -> None:
        info = translate_generation_error(
            "HTTP 错误 500：request blocked by Gemini API: PROHIBITED_CONTENT",
            provider="google",
            route="google_gen",
            task_type="google-gen",
            stage="calling_api",
        )

        self.assertEqual(info["error_code"], "google.prohibited_content")
        self.assertEqual(info["error_category"], "safety")
        self.assertIn("Google 图像生成被安全策略拦截", info["display_error"])
        self.assertIn("受限内容", info["display_error"])

    def test_google_pool_rate_limit_names_the_google_pool(self) -> None:
        for provider, label in (("google_pool", "Google OAuth 账号池"), ("google_web", "Gemini Web 账号池")):
            info = translate_generation_error(
                "Google 流式接口错误：Google 图像生成失败（HTTP 429）",
                provider=provider,
                route=provider + "_edit",
                task_type="google-edit",
                stage="failed",
            )
            self.assertEqual(info["error_code"], provider + ".rate_limited")
            self.assertEqual(info["error_category"], "rate_limit")
            self.assertIn(label, info["display_error"])
            self.assertNotIn("ChatGPT", info["display_error"])

        info = translate_generation_error("HTTP 429 rate limit", provider="chatgpt_pool")
        self.assertEqual(info["display_error"], "ChatGPT 账号池账号被限流了")


    def test_google_pool_http_403_is_not_labeled_chatgpt(self) -> None:
        info = translate_generation_error(
            "Google 流式接口错误：Google 图像生成失败（HTTP 403）",
            provider="google_pool",
            route="google_pool_edit",
            task_type="google-edit",
            stage="failed",
        )
        self.assertEqual(info["error_code"], "google_pool.upstream_rejected")
        self.assertEqual(info["error_category"], "upstream")
        self.assertEqual(info["display_error"], "Google OAuth 账号池被上游拒绝（HTTP 403）")
        self.assertNotIn("ChatGPT", info["display_error"])

        with_reason = translate_generation_error(
            "Google 图像生成失败（HTTP 403，TOS_VIOLATION）",
            provider="google_pool",
            route="google_pool_edit",
            task_type="google-edit",
        )
        self.assertIn("Google OAuth 账号池被上游拒绝", with_reason["display_error"])
        self.assertIn("HTTP 403", with_reason["display_error"])
        self.assertIn("TOS_VIOLATION", with_reason["display_error"])
        self.assertNotIn("ChatGPT", with_reason["display_error"])

        leaked = translate_generation_error(
            "Google 图像生成失败（HTTP 403，ya29.fixture-secret-token）",
            provider="google_pool",
            route="google_pool_edit",
            task_type="google-edit",
        )
        self.assertEqual(leaked["display_error"], "Google OAuth 账号池被上游拒绝（HTTP 403）")
        self.assertNotIn("ya29.fixture-secret-token", leaked["display_error"])

    def test_chatgpt_pool_http_401_and_403_keep_sidecar_auth_copy(self) -> None:
        for raw in (
            "HTTP 401 unauthorized",
            "ChatGPT 账号池 sidecar unauthorized HTTP 401",
            "HTTP 403 forbidden",
        ):
            info = translate_generation_error(raw, provider="chatgpt_pool", route="chatgpt_pool")
            self.assertEqual(info["display_error"], "ChatGPT 账号池鉴权失败，请检查 sidecar 或重新登录")
            self.assertEqual(info["error_category"], "auth")

    def test_google_pool_403_reason_survives_sidecar_provider_tracking_chain(self) -> None:
        class _Bounded:
            def __init__(self, raw, status):
                self.status_code = status
                self._raw = raw
            def json(self):
                raise AssertionError("chain test must not use Response.json()")
            @property
            def content(self):
                raise AssertionError("chain test must not use Response.content")
            @property
            def text(self):
                raise AssertionError("chain test must not use Response.text")
            def iter_content(self, chunk_size=None):
                step = chunk_size or 16
                for i in range(0, len(self._raw), step):
                    yield self._raw[i:i + step]

        payload = {
            "error": {
                "code": 403,
                "message": "ya29.fixture-secret-token for user@example.com",
                "status": "PERMISSION_DENIED",
                "details": [{"reason": "TOS_VIOLATION", "metadata": {"email": "user@example.com"}}],
            }
        }
        import json as _json
        with self.assertRaises(GoogleError) as caught:
            GoogleUpstream.checked_json(_Bounded(_json.dumps(payload).encode(), 403), "Google 图像生成")
        public = caught.exception.public()
        wrapped = RuntimeError(public.get("error") or "Google账号池HTTP 403")
        stream_wrapped = f"Google 流式接口错误：{public['error']}"
        secrets = ("ya29.fixture-secret-token", "user@example.com")
        for raw in (str(wrapped), stream_wrapped, public["error"]):
            info = translate_generation_error(
                raw, provider="google_pool", route="google_pool_edit", task_type="google-edit"
            )
            self.assertIn("Google OAuth 账号池被上游拒绝", info["display_error"])
            self.assertIn("HTTP 403", info["display_error"])
            self.assertIn("TOS_VIOLATION", info["display_error"])
            self.assertNotIn("ChatGPT", info["display_error"])
            for secret in secrets:
                self.assertNotIn(secret, info["display_error"])
                self.assertNotIn(secret, info["raw_error"])
                self.assertNotIn(secret, raw)

    def test_gemini_web_no_image_is_classified_as_output(self) -> None:
        info = translate_generation_error(
            "Google 流式接口错误：Gemini Web 未返回图片，未重新提交",
            provider="google_web",
            route="google_web_edit",
            task_type="google-edit",
            stage="failed",
            exception_name="ValueError",
        )
        self.assertEqual(info["error_code"], "google_web.no_image")
        self.assertEqual(info["error_category"], "output")
        self.assertIn("未返回图片", info["display_error"])
        self.assertEqual(info["raw_error"], "Google 流式接口错误：Gemini Web 未返回图片，未重新提交")

    def test_gemini_web_invalid_image_message_stays_output(self) -> None:
        info = translate_generation_error(
            "Google 流式接口错误：Gemini Web 未返回有效图片，未重新提交",
            provider="google_web",
            route="google_web_edit",
            task_type="google-edit",
        )
        self.assertEqual(info["error_code"], "google_web.no_image")
        self.assertEqual(info["error_category"], "output")

    def test_generation_error_translation_maps_third_party_ssl_eof(self) -> None:
        info = translate_generation_error(
            "HTTPSConnectionPool(host='api.change2pro.com', port=443): Max retries exceeded "
            "with url: /v1/images/generations (Caused by SSLError(SSLEOFError(8, "
            "'[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol "
            "(_ssl.c:1081)')))",
            provider="third_party_image_api",
            route="third_party_image_api",
            task_type="gpt",
            stage="failed",
        )

        self.assertEqual(info["error_code"], "third_party_image_api.ssl_eof")
        self.assertEqual(info["error_category"], "transport")
        self.assertIn("第三方图片 API 连接中途断开", info["display_error"])
        self.assertNotIn("HTTPSConnectionPool", info["display_error"])
        self.assertNotIn("SSLEOFError", info["display_error"])


    def test_google_upstream_403_extractor_is_bounded_and_redacted(self) -> None:
        class _Bounded:
            def __init__(self, raw, status=403, chunk_size=32):
                self.status_code = status
                self._raw = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
                self.bytes_yielded = 0
                self.chunk_size = chunk_size

            def json(self):
                raise AssertionError("checked_json must not parse via Response.json()")

            @property
            def content(self):
                raise AssertionError("checked_json must not read Response.content wholesale")

            @property
            def text(self):
                raise AssertionError("checked_json must not read Response.text wholesale")

            def iter_content(self, chunk_size=None):
                step = chunk_size or self.chunk_size
                if step <= 0:
                    step = self.chunk_size
                data = self._raw
                for i in range(0, len(data), step):
                    part = bytes(data[i : i + step])
                    self.bytes_yielded += len(part)
                    yield part

        secrets = (
            "ya29.fixture-secret-token",
            "user@example.com",
            "projects/fixture-project-id",
            "Bearer fixture-header",
            "prompt: draw a cat",
            "<script>alert(1)</script>",
        )

        allowed = {
            "error": {
                "code": 403,
                "message": secrets[0],
                "status": "PERMISSION_DENIED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "TOS_VIOLATION",
                        "metadata": {"email": secrets[1]},
                    }
                ],
            }
        }
        with self.assertRaises(GoogleError) as caught:
            GoogleUpstream.checked_json(
                _Bounded(__import__("json").dumps(allowed).encode()), "Google 图像生成"
            )
        text = str(caught.exception)
        public = __import__("json").dumps(caught.exception.public())
        self.assertIn("HTTP 403", text)
        self.assertIn("TOS_VIOLATION", text)
        self.assertNotIn("PERMISSION_DENIED", text)  # details.reason wins over status
        for secret in secrets:
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, public)

        rejected_bodies = [
            b"not-json {",
            b"<html><body>403 forbidden ya29.fixture-secret-token</body></html>",
            __import__("json").dumps(
                {
                    "error": {
                        "message": secrets[0],
                        "reason": "not a valid reason!!",
                        "status": "user@example.com",
                    }
                }
            ).encode(),
            __import__("json").dumps(
                {
                    "error": {
                        "message": secrets[1],
                        "details": [
                            {"reason": "../../../etc/passwd"},
                            {"reason": "Bearer abc.def"},
                            {"reason": "TOS_VIOLATION; rm -rf /"},
                        ],
                    }
                }
            ).encode(),
            __import__("json").dumps({"error": "plain string ya29.fixture-secret-token"}).encode(),
        ]
        for raw in rejected_bodies:
            with self.assertRaises(GoogleError) as caught:
                GoogleUpstream.checked_json(_Bounded(raw), "Google 图像生成")
            text = str(caught.exception)
            self.assertIn("HTTP 403", text)
            self.assertNotIn("TOS_VIOLATION", text)
            self.assertNotIn("etc/passwd", text)
            self.assertNotIn("Bearer", text)
            self.assertNotIn("<script>", text)
            for secret in secrets:
                self.assertNotIn(secret, text)

        prefix = b'{"error":{"status":"PERMISSION_DENIED","message":"'
        huge = prefix + b"A" * (512 * 1024) + b'"}}'
        oversized = _Bounded(huge, chunk_size=2048)
        with self.assertRaises(GoogleError) as caught:
            GoogleUpstream.checked_json(oversized, "Google 图像生成")
        self.assertIn("HTTP 403", str(caught.exception))
        self.assertNotIn("A" * 200, str(caught.exception))
        self.assertLessEqual(oversized.bytes_yielded, 16 * 1024)
        self.assertGreater(oversized.bytes_yielded, 0)

if __name__ == "__main__":
    unittest.main()
