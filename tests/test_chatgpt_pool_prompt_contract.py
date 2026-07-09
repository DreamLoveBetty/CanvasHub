#!/usr/bin/env python3

from __future__ import annotations

import unittest


class ChatgptPoolPromptContractTest(unittest.TestCase):
    def test_smart_pool_prompt_sends_user_prompt_without_hard_instruction_wrapper(self):
        from backend.provider_chatgpt_pool import _prepare_pool_prompt

        user_prompt = "从小说中选取一位成年女性角色，生成全身像壁纸。"
        prompt = _prepare_pool_prompt(user_prompt, "smart")

        self.assertEqual(prompt, user_prompt)
        self.assertNotIn("账号池生图硬指令", prompt)
        self.assertNotIn("用户图像提示词", prompt)
        self.assertNotIn("<<<", prompt)
        self.assertNotIn(">>>", prompt)

    def test_faithful_pool_prompt_sends_user_prompt_without_hard_instruction_wrapper(self):
        from backend.provider_chatgpt_pool import _prepare_pool_prompt

        user_prompt = "画一张横版电影海报。"
        prompt = _prepare_pool_prompt(user_prompt, "faithful")

        self.assertEqual(prompt, user_prompt)
        self.assertNotIn("账号池忠实生图硬指令", prompt)
        self.assertNotIn("用户图像提示词", prompt)
        self.assertNotIn("<<<", prompt)
        self.assertNotIn(">>>", prompt)

    def test_finished_without_image_output_is_classified_for_users(self):
        from backend.server import _classify_route_error, _format_gpt_pool_error

        message = "ChatGPT conversation finished without image output: conversation_id=abc"

        self.assertEqual(_classify_route_error("chatgpt_pool", message), "no_image_output")
        self.assertIn("没有返回图片", _format_gpt_pool_error(message))

    def test_pool_prompt_sanitizes_brittle_safety_negative_terms_for_web_tool(self):
        from backend.provider_chatgpt_pool import _prepare_pool_prompt

        prompt = _prepare_pool_prompt(
            "生成成年女性角色壁纸。非露骨、无裸露、无未成年人、无水印。"
            "负面约束：避免未成年人形象、露骨表达、裸露设计、身体局部凝视、过度性感化、文字乱码。",
            "smart",
        )

        self.assertNotIn("账号池生图硬指令", prompt)
        self.assertNotIn("用户图像提示词", prompt)
        self.assertNotIn("<<<", prompt)
        self.assertNotIn(">>>", prompt)
        self.assertIn("账号池 Web 图片工具兼容性正向约束", prompt)
        self.assertIn("服装完整覆盖", prompt)
        self.assertIn("角色外观明确成熟", prompt)
        self.assertIn("表达克制", prompt)
        self.assertNotIn("无裸露", prompt)
        self.assertNotIn("无未成年人", prompt)
        self.assertNotIn("露骨表达", prompt)
        self.assertNotIn("身体局部凝视", prompt)


if __name__ == "__main__":
    unittest.main()
