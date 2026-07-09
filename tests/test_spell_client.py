import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import spell_client


ROOT = Path(__file__).resolve().parents[1]


class SpellClientTest(unittest.TestCase):
    def test_spell_client_has_no_default_api_key(self):
        source = (ROOT / "backend" / "spell_client.py").read_text(encoding="utf-8")

        self.assertEqual(spell_client.DEFAULT_SPELL_API_KEY, "")
        self.assertNotRegex(source, r"sk-[A-Za-z0-9_-]{20,}")

    def test_spell_prompt_uses_codex_oauth_by_default(self):
        raw_json = {
            "主题中文提示词": {"整体风格": "电影感雨夜街道"},
            "prompts": {
                "positive_prompt": "cinematic rainy neon street",
                "negative_prompt": "blurry, low quality",
            },
        }
        original_env = {key: os.environ.get(key) for key in ("SPELL_PROVIDER", "SPELL_API_URL", "SPELL_API_BASE_URL", "SPELL_API_KEY", "SPELL_MODEL_NAME")}
        try:
            for key in original_env:
                os.environ.pop(key, None)
            with patch.object(spell_client, "get_prompt_skill_config", return_value={"model": "gpt-5.5", "reasoning_effort": "low"}), patch.object(
                spell_client,
                "get_gpt_provider_config",
                return_value={"image_main_model": "gpt-5.4"},
            ), patch.object(
                spell_client,
                "_call_prompt_provider_with_pool_fallback",
                return_value=(json.dumps(raw_json, ensure_ascii=False), "gpt_oauth", "gpt-5.5", "low", ""),
            ) as call:
                result = spell_client.generate_structured_spell_prompt("雨夜城市街道")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        call.assert_called_once()
        provider_id, user_prompt, system_prompt, model, reasoning_effort, label = call.call_args.args
        self.assertEqual(provider_id, "gpt_oauth")
        self.assertIn("雨夜城市街道", user_prompt)
        self.assertIn("提示词工程师", system_prompt)
        self.assertEqual(model, "gpt-5.5")
        self.assertEqual(reasoning_effort, "low")
        self.assertEqual(label, "咒术生成")
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "gpt_oauth")
        self.assertEqual(result["model"], "gpt-5.5")
        self.assertEqual(result["positive_prompt"], "cinematic rainy neon street")
        self.assertEqual(result["negative_prompt"], "blurry, low quality")


if __name__ == "__main__":
    unittest.main()
