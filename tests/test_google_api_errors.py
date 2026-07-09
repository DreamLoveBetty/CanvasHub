#!/usr/bin/env python3

from __future__ import annotations

import unittest

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

    def test_openai_chat_endpoint_detection_for_change2pro_root(self) -> None:
        self.assertTrue(_uses_openai_chat_endpoint("https://api.change2pro.com"))
        self.assertEqual(
            _chat_completions_url("https://api.change2pro.com"),
            "https://api.change2pro.com/v1/chat/completions",
        )
        self.assertEqual(
            _chat_completions_url("https://api.change2pro.com/v1"),
            "https://api.change2pro.com/v1/chat/completions",
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


if __name__ == "__main__":
    unittest.main()
