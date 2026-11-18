import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.server import _sanitize_system_settings_patch
from backend.app_config import BASE_DIR, get_server_config, get_yunwu_api_base_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Inherited public-mode / password env has been shown to skip save-path validation
# (`_server_config_from_settings_snapshot` prefers process env over the patch).
_PUBLIC_MODE_ISOLATION_ENV = {
    "MINIAPP_PUBLIC_MODE": "",
    "PUBLIC_MODE": "",
    "MINIAPP_ACCESS_PASSWORD": "",
    "MINIAPP_AUTH_PASSWORD": "",
}


def _storage_config_from_isolated_import(extra_env, unset=()):
    """Load `get_storage_config` in a child process that only imports app_config.

    APP_DATA_DIR / DESKTOP_DATA_MODE are fixed at import time, so a parent process
    that already imported backend.server (or set CANVASHUB_DATA_DIR for recover()
    isolation) cannot observe both source-tree and desktop-data layouts itself.
    The child never imports backend.server and never points at production data.
    """
    script = r"""
import json, os, sys
from pathlib import Path
spec = json.loads(sys.stdin.read())
for key in spec["unset"]:
    os.environ.pop(key, None)
os.environ.update(spec["env"])
sys.path.insert(0, spec["project_root"])
os.chdir(spec["project_root"])
from backend.app_config import APP_DATA_DIR, BASE_DIR, DESKTOP_DATA_MODE, get_storage_config
cfg = get_storage_config()
json.dump({
    "base_dir": str(BASE_DIR),
    "app_data_dir": str(APP_DATA_DIR),
    "desktop_data_mode": bool(DESKTOP_DATA_MODE),
    "image_archive_dir": str(cfg["image_archive_dir"]),
    "source_image_dir": str(cfg["source_image_dir"]),
}, sys.stdout)
"""
    env = {key: value for key, value in os.environ.items() if key not in set(unset)}
    env.update(extra_env)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    # The child must not inherit a data-dir unless the test set one.
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps({"env": extra_env, "unset": list(unset), "project_root": str(PROJECT_ROOT)}),
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"isolated storage import failed ({proc.returncode}): {proc.stderr[-2000:]}"
        )
    return json.loads(proc.stdout)


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
            cfg = _storage_config_from_isolated_import(
                {
                    "APP_SETTINGS_PATH": str(settings_path),
                    "IMAGE_ARCHIVE_DIR": "",
                    "SOURCE_IMAGE_DIR": "",
                },
                unset=(
                    "CANVASHUB_DATA_DIR",
                    "CANVASHUB_RESOURCE_DIR",
                    "IMAGE_ARCHIVE_DIR",
                    "SOURCE_IMAGE_DIR",
                    "APP_SETTINGS_PATH",
                ),
            )

        self.assertEqual(Path(cfg["base_dir"]), BASE_DIR)
        self.assertFalse(cfg["desktop_data_mode"])
        self.assertEqual(Path(cfg["app_data_dir"]), BASE_DIR)
        self.assertEqual(Path(cfg["image_archive_dir"]), BASE_DIR / "data" / "archive")
        self.assertEqual(Path(cfg["source_image_dir"]), BASE_DIR / "data" / "source_images")

    def test_storage_defaults_follow_desktop_data_dir_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = root / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            data_dir = root / "desktop-data"
            data_dir.mkdir()
            cfg = _storage_config_from_isolated_import(
                {
                    "CANVASHUB_DATA_DIR": str(data_dir),
                    "APP_SETTINGS_PATH": str(settings_path),
                    "IMAGE_ARCHIVE_DIR": "",
                    "SOURCE_IMAGE_DIR": "",
                },
                unset=(
                    "CANVASHUB_RESOURCE_DIR",
                    "IMAGE_ARCHIVE_DIR",
                    "SOURCE_IMAGE_DIR",
                    "APP_SETTINGS_PATH",
                ),
            )

        self.assertTrue(cfg["desktop_data_mode"])
        self.assertEqual(Path(cfg["app_data_dir"]), data_dir.resolve())
        self.assertEqual(Path(cfg["image_archive_dir"]), data_dir.resolve() / "archive")
        self.assertEqual(Path(cfg["source_image_dir"]), data_dir.resolve() / "source_images")
        self.assertNotEqual(Path(cfg["image_archive_dir"]), BASE_DIR / "data" / "archive")
        self.assertNotEqual(Path(cfg["source_image_dir"]), BASE_DIR / "data" / "source_images")

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
            env = {"APP_SETTINGS_PATH": str(settings_path), **_PUBLIC_MODE_ISOLATION_ENV}
            with patch.dict("os.environ", env, clear=False):
                with self.assertRaisesRegex(ValueError, "公网模式必须先设置访问密码"):
                    _sanitize_system_settings_patch(
                        {"server": {"public_mode": True, "host": "0.0.0.0"}}
                    )

    def test_public_mode_can_be_saved_with_access_password(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            env = {"APP_SETTINGS_PATH": str(settings_path), **_PUBLIC_MODE_ISOLATION_ENV}
            with patch.dict("os.environ", env, clear=False):
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
