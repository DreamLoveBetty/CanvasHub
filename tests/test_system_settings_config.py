import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.server import _sanitize_system_settings_patch
from backend.app_config import BASE_DIR, get_server_config, get_storage_config, get_yunwu_api_base_url


class SystemSettingsConfigTest(unittest.TestCase):
    def test_empty_secret_inputs_do_not_overwrite_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "miniapp_access_password": "old-password",
                        "yunwu_api_key": "old-legacy-nano",
                        "yunwu_api_base_url": "https://old.example/v1beta",
                        "telegram": {"bot_token": "old-token", "chat_id": "1"},
                        "chatgpt_pool": {"auth_key": "old-pool-key"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "miniapp_access_password": "",
                        "yunwu_api_key": "",
                        "yunwu_api_base_url": "https://new.example/v1beta/",
                        "telegram": {"bot_token": "", "chat_id": "2"},
                        "chatgpt_pool": {"auth_key": "", "base_url": "http://127.0.0.1:18080"},
                    }
                )

        self.assertEqual(updated["miniapp_access_password"], "old-password")
        self.assertEqual(updated["yunwu_api_key"], "old-legacy-nano")
        self.assertEqual(updated["yunwu_api_base_url"], "https://new.example/v1beta/")
        self.assertEqual(updated["telegram"]["bot_token"], "old-token")
        self.assertEqual(updated["telegram"]["chat_id"], "2")
        self.assertEqual(updated["chatgpt_pool"]["auth_key"], "old-pool-key")
        self.assertEqual(updated["chatgpt_pool"]["base_url"], "http://127.0.0.1:18080")

    def test_yunwu_base_url_can_be_cleared_without_clearing_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "yunwu_api_key": "old-legacy-nano",
                        "yunwu_api_base_url": "https://old.example/v1beta",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "yunwu_api_key": "",
                        "yunwu_api_base_url": "",
                    }
                )

        self.assertEqual(updated["yunwu_api_key"], "old-legacy-nano")
        self.assertEqual(updated["yunwu_api_base_url"], "")

    def test_yunwu_base_url_root_is_preserved_for_openai_compatible_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"yunwu_api_base_url": "https://api.change2pro.com"}),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                self.assertEqual(get_yunwu_api_base_url(), "https://api.change2pro.com")

    def test_yunwu_base_url_keeps_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"yunwu_api_base_url": "https://api.change2pro.com/custom-gemini"}),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                self.assertEqual(get_yunwu_api_base_url(), "https://api.change2pro.com/custom-gemini")

    def test_nano_banana_section_overrides_legacy_yunwu_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "yunwu_api_base_url": "https://legacy.example/v1beta",
                        "nano_banana_api": {"base_url": "https://neutral.example/v1beta"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                self.assertEqual(get_yunwu_api_base_url(), "https://neutral.example/v1beta")

    def test_nano_banana_settings_are_saved_to_neutral_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "nano_banana_api": {
                            "api_key": "sk-neutral",
                            "base_url": "https://api.example/v1beta",
                        }
                    }
                )

        self.assertEqual(updated["nano_banana_api"]["api_key"], "sk-neutral")
        self.assertEqual(updated["nano_banana_api"]["base_url"], "https://api.example/v1beta")
        self.assertNotIn("yunwu_api_key", updated)

    def test_nano_banana_clear_removes_legacy_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "nano_banana_api": {
                            "api_key": "sk-neutral",
                            "base_url": "https://neutral.example/v1beta",
                        },
                        "nano_banana_api_key": "sk-top-neutral",
                        "nano_banana_api_base_url": "https://top-neutral.example/v1beta",
                        "yunwu_api_key": "sk-legacy",
                        "yunwu_api_base_url": "https://legacy.example/v1beta",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "nano_banana_api": {
                            "clear_api_key": True,
                            "base_url": "",
                        }
                    }
                )

        self.assertNotIn("api_key", updated["nano_banana_api"])
        self.assertEqual(updated["nano_banana_api"]["base_url"], "")
        self.assertNotIn("nano_banana_api_key", updated)
        self.assertNotIn("nano_banana_api_base_url", updated)
        self.assertNotIn("yunwu_api_key", updated)
        self.assertNotIn("yunwu_api_base_url", updated)

    def test_explicit_clear_removes_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps(
                    {
                        "miniapp_access_password": "old-password",
                        "yunwu_api_key": "old-legacy-nano",
                        "telegram": {"bot_token": "old-token", "chat_id": "1"},
                        "chatgpt_pool": {"auth_key": "old-pool-key"},
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "clear_miniapp_access_password": True,
                        "clear_yunwu_api_key": True,
                        "telegram": {"clear_bot_token": True},
                        "chatgpt_pool": {"clear_auth_key": True},
                    }
                )

        self.assertNotIn("miniapp_access_password", updated)
        self.assertNotIn("yunwu_api_key", updated)
        self.assertNotIn("bot_token", updated["telegram"])
        self.assertNotIn("auth_key", updated["chatgpt_pool"])

    def test_storage_defaults_are_project_local_data_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            env = {
                "APP_SETTINGS_PATH": str(settings_path),
                "IMAGE_ARCHIVE_DIR": "",
                "SOURCE_IMAGE_DIR": "",
            }
            with patch.dict("os.environ", env, clear=False):
                cfg = get_storage_config()

        self.assertEqual(cfg["image_archive_dir"], BASE_DIR / "data" / "archive")
        self.assertEqual(cfg["source_image_dir"], BASE_DIR / "data" / "source_images")

    def test_server_defaults_to_localhost_even_if_host_env_is_present_without_public_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            env = {
                "APP_SETTINGS_PATH": str(settings_path),
                "HOST": "0.0.0.0",
                "PUBLIC_MODE": "",
                "MINIAPP_PUBLIC_MODE": "",
            }
            with patch.dict("os.environ", env, clear=False):
                cfg = get_server_config()

        self.assertFalse(cfg["public_mode"])
        self.assertEqual(cfg["host"], "127.0.0.1")

    def test_public_mode_requires_access_password_on_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                with self.assertRaisesRegex(ValueError, "公网模式必须先设置访问密码"):
                    _sanitize_system_settings_patch(
                        {"server": {"public_mode": True, "host": "0.0.0.0"}}
                    )

    def test_public_mode_can_be_saved_with_access_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict("os.environ", {"APP_SETTINGS_PATH": str(settings_path)}, clear=False):
                updated = _sanitize_system_settings_patch(
                    {
                        "miniapp_access_password": "secret",
                        "server": {"public_mode": True, "host": "0.0.0.0", "port": 18464},
                    }
                )

        self.assertEqual(updated["miniapp_access_password"], "secret")
        self.assertTrue(updated["server"]["public_mode"])
        self.assertEqual(updated["server"]["host"], "0.0.0.0")
        self.assertEqual(updated["server"]["port"], 18464)


if __name__ == "__main__":
    unittest.main()
