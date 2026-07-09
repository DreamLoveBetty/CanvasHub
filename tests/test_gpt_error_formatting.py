#!/usr/bin/env python3

from __future__ import annotations

import unittest

from backend.provider_gpt_codex import _is_transient_provider_error
from backend.server import _classify_route_error, _format_gpt_failure_error, _format_gpt_provider_error


class GptErrorFormattingTest(unittest.TestCase):
    def test_chunked_stream_error_is_user_readable(self) -> None:
        message = _format_gpt_provider_error("ChunkedEncodingError: Response ended prematurely")

        self.assertIn("连接中途断开", message)
        self.assertNotIn("ChunkedEncodingError", message)
        self.assertNotIn("Response ended prematurely", message)

    def test_combined_provider_and_pool_error_hides_raw_stack(self) -> None:
        raw = (
            "本地 provider 失败：ChunkedEncodingError: Response ended prematurely"
            " | 账号池托底失败：Error: ChatGPT 账号池 sidecar 未在线\n"
        )

        message = _format_gpt_failure_error(raw)

        self.assertIn("本地 GPT provider 连接中途断开", message)
        self.assertIn("ChatGPT 账号池 sidecar 未在线", message)
        self.assertNotIn("ChunkedEncodingError", message)
        self.assertNotIn("gpt_cdp_bridge", message)

    def test_chunked_stream_error_is_retryable(self) -> None:
        self.assertTrue(_is_transient_provider_error("ChunkedEncodingError: Response ended prematurely"))

    def test_missing_image_output_is_user_readable(self) -> None:
        message = _format_gpt_provider_error("CodexAPIError: upstream did not return image output")

        self.assertIn("没有返回图片数据", message)
        self.assertNotIn("CodexAPIError", message)

    def test_text_instead_of_image_points_to_prompt_boundary(self) -> None:
        message = _format_gpt_provider_error(
            "CodexAPIError: upstream did not return image output; "
            "output_text=I cannot generate this image because it may violate safety policy."
        )

        self.assertIn("返回了文字而不是图片", message)
        self.assertIn("修改提示词", message)

    def test_structured_server_error_points_to_upstream(self) -> None:
        message = _format_gpt_provider_error(
            "CodexAPIError: upstream response.failed: response.failed: status=failed: "
            "code=server_error: request_id=resp_test"
        )

        self.assertIn("上游临时错误", message)
        self.assertIn("resp_test", message)

    def test_disconnect_with_last_generating_event_points_to_stream_transport(self) -> None:
        message = _format_gpt_provider_error(
            "CodexAPIError: stream disconnected before completion; "
            "last_event=response.image_generation_call.generating; events=7; "
            "transport_error=ChunkedEncodingError: Response ended prematurely"
        )

        self.assertIn("连接中途断开", message)
        self.assertIn("已进入图片生成阶段", message)

    def test_route_error_classification_keeps_trace_actionable(self) -> None:
        self.assertEqual(_classify_route_error("chatgpt_pool", "HTTP 429 rate limit"), "rate_limited")
        self.assertEqual(_classify_route_error("chatgpt_pool_editable", "download url not found for artifact"), "artifact_download")
        self.assertEqual(_classify_route_error("chatgpt_pool", "ProxyError: Unable to connect to proxy"), "proxy")
        self.assertEqual(_classify_route_error("codex", "timeout waiting for provider"), "timeout")

    def test_account_pool_quota_error_keeps_reset_time_visible(self) -> None:
        message = _format_gpt_failure_error(
            "本地 provider 失败：CodexAPIError: Token refresh failed with status 401"
            " | 账号池托底失败：HTTP 502: ChatGPT account pool image quota exhausted: "
            "limited@example.com: 你已达到图片创建上限；恢复时间 2026-06-22T05:56:44+00:00；剩余额度 0"
        )

        self.assertIn("ChatGPT 账号池图片生成额度已用完", message)
        self.assertIn("2026-06-22", message)
        self.assertNotIn("生成等待超时", message)


if __name__ == "__main__":
    unittest.main()
