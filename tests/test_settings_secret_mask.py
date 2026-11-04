import json
import os
import re
import unittest
from pathlib import Path
from unittest import mock

from backend import app_config

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_JS = (ROOT / "frontend/scripts/desktop-settings.js").read_text(encoding="utf-8")
LORA_JS = (ROOT / "frontend/scripts/desktop-lora-settings.js").read_text(encoding="utf-8")


class SecretLengthConfigTests(unittest.TestCase):
    def test_public_configs_carry_the_length_and_never_the_value(self):
        secret = "sk-synthetic-secret-0123456789"
        settings = {
            "third_party_image_api": {"api_key": secret},
            "cyimg": {"api_key": secret},
            "chatgpt_pool": {"auth_key": secret},
        }
        with mock.patch.object(app_config, "load_app_settings", return_value=settings), \
                mock.patch.dict("os.environ", {}, clear=False):
            for name in ("THIRD_PARTY_IMAGE_API_KEY", "THIRD_PARTY_GPT_IMAGE_API_KEY", "CYIMG_API_KEY", "CHATGPT_POOL_AUTH_KEY"):
                os.environ.pop(name, None)
            pool = app_config.get_chatgpt_pool_public_config()
            third_party = app_config.get_third_party_image_config()
            cyimg = app_config.get_cyimg_config()
        self.assertEqual(pool["auth_key_length"], len(secret))
        self.assertEqual(third_party["api_key_length"], len(secret))
        self.assertEqual(cyimg["api_key_length"], len(secret))
        self.assertNotIn(secret, json.dumps(pool))


class SecretMaskFrontendContractTests(unittest.TestCase):
    def test_mask_is_a_placeholder_never_a_field_value(self):
        renderer = re.search(r"function secretMaskAttrs[\s\S]+?\n  }\n", SETTINGS_JS)[0]
        self.assertIn("'*'.repeat(length)", renderer)
        self.assertIn('placeholder="', renderer)
        self.assertRegex(SETTINGS_JS, r'type="password"[^\n]+secretMaskAttrs[^\n]+value=""')
        self.assertIn('placeholder="${mask}"', LORA_JS)

    def test_configured_secret_without_a_length_uses_the_default_mask(self):
        self.assertIn("const DEFAULT_SECRET_MASK_LENGTH = 8;", SETTINGS_JS)
        self.assertIn("lengthKnown ? known : DEFAULT_SECRET_MASK_LENGTH", SETTINGS_JS)
        self.assertIn("'*'.repeat(length>0?length:8)", LORA_JS)

    def test_unedited_password_fields_stay_out_of_the_save_payload(self):
        self.assertIn("if (input.type === 'password' && !String(value || '').trim()) return;", SETTINGS_JS)

    def test_clear_action_keeps_its_confirmation_and_is_not_inside_a_label(self):
        self.assertIn("window.confirm(message)", SETTINGS_JS)
        self.assertIn("确认清空已保存的 Civitai API Key", LORA_JS)
        self.assertIn('<div class="desk-settings-switch-row">${row}${action}</div>', SETTINGS_JS)

    def test_no_reveal_path_exists(self):
        self.assertNotIn("reveal-secret", SETTINGS_JS)
        self.assertNotIn("reveal-secret", (ROOT / "backend/server.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
