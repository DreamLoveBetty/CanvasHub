import re
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import app_config, pinterest_auth
from backend.server import _sanitize_system_settings_patch


PROFILE_URL = "https://www.pinterest.com/example/"


def account_identity(username="example", display_name="Example User"):
    return {
        "username": username,
        "display_name": display_name,
        "profile_url": f"https://www.pinterest.com/{username}/",
    }


def auth_document(cookie_value="valid"):
    return {
        "version": 1,
        "provider": "pinterest_browser",
        "profile_url": PROFILE_URL,
        "source": "cookie_import",
        "auth": {"status": "authenticated", "last_verified_at": ""},
        "storage_state": {
            "cookies": [
                {
                    "name": "_pinterest_sess",
                    "value": cookie_value,
                    "domain": ".pinterest.com",
                    "path": "/",
                    "expires": -1,
                }
            ],
            "origins": [],
        },
    }


class PinterestAuthPathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.app_data = self.root / "app-data"
        self.settings_path = self.app_data / "settings.json"
        self.fixed_auth = self.app_data / "auth" / "pinterest" / "browser_auth.json"
        self.app_data.mkdir(parents=True)
        self.settings_path.write_text("{}", encoding="utf-8")

        self.env_patch = patch.dict(
            os.environ,
            {"APP_SETTINGS_PATH": str(self.settings_path)},
            clear=False,
        )
        self.app_data_patch = patch.object(app_config, "APP_DATA_DIR", self.app_data)
        self.fixed_auth_patch = patch.object(
            app_config,
            "DEFAULT_PINTEREST_AUTH_FILE",
            self.fixed_auth,
        )
        self.auth_app_data_patch = patch.object(pinterest_auth, "APP_DATA_DIR", self.app_data)
        self.env_patch.start()
        self.app_data_patch.start()
        self.fixed_auth_patch.start()
        self.auth_app_data_patch.start()
        pinterest_auth._PENDING.clear()

    def tearDown(self):
        pinterest_auth._PENDING.clear()
        self.auth_app_data_patch.stop()
        self.fixed_auth_patch.stop()
        self.app_data_patch.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def write_settings(self, pinterest):
        self.settings_path.write_text(
            json.dumps({"pinterest": pinterest}),
            encoding="utf-8",
        )

    def test_absolute_legacy_path_cannot_redirect_runtime_write_or_delete(self):
        victim = self.root / "victim.txt"
        victim.write_text("keep-me", encoding="utf-8")
        self.write_settings({"auth_file": str(victim), "profile_url": PROFILE_URL})

        pinterest_auth.import_cookie_header("_pinterest_sess=account-a", PROFILE_URL)

        self.assertEqual("keep-me", victim.read_text(encoding="utf-8"))
        self.assertTrue(self.fixed_auth.is_file())
        self.assertIn("account-a", pinterest_auth.load_saved_cookie_header(PROFILE_URL))
        self.assertNotIn("auth_file", json.loads(self.settings_path.read_text())["pinterest"])

        pinterest_auth.delete_saved_auth()

        self.assertFalse(self.fixed_auth.exists())
        self.assertEqual("keep-me", victim.read_text(encoding="utf-8"))

    def test_parent_traversal_path_cannot_redirect_runtime_write(self):
        victim = self.root / "victim.json"
        victim.write_text("keep-me-too", encoding="utf-8")
        self.write_settings(
            {
                "auth_file": "../victim.json",
                "profile_url": PROFILE_URL,
            }
        )

        pinterest_auth.import_cookie_header("_pinterest_sess=account-b", PROFILE_URL)

        self.assertEqual("keep-me-too", victim.read_text(encoding="utf-8"))
        self.assertIn("account-b", pinterest_auth.load_saved_cookie_header(PROFILE_URL))

    def test_valid_legacy_auth_is_copied_and_never_removed(self):
        legacy = self.root / "legacy-auth.json"
        legacy.write_text(json.dumps(auth_document("legacy")), encoding="utf-8")
        original_bytes = legacy.read_bytes()
        self.write_settings({"auth_file": str(legacy), "profile_url": PROFILE_URL})

        migrated = pinterest_auth.ensure_pinterest_auth_storage()

        self.assertEqual(self.fixed_auth.resolve(), migrated)
        self.assertEqual(original_bytes, legacy.read_bytes())
        self.assertIn("legacy", pinterest_auth.load_saved_cookie_header(PROFILE_URL))
        self.assertNotIn("auth_file", json.loads(self.settings_path.read_text())["pinterest"])

        pinterest_auth.delete_saved_auth()

        self.assertFalse(self.fixed_auth.exists())
        self.assertEqual(original_bytes, legacy.read_bytes())

    def test_existing_canonical_auth_wins_over_legacy(self):
        self.fixed_auth.parent.mkdir(parents=True)
        self.fixed_auth.write_text(json.dumps(auth_document("current")), encoding="utf-8")
        legacy = self.root / "legacy-auth.json"
        legacy.write_text(json.dumps(auth_document("legacy")), encoding="utf-8")
        self.write_settings({"auth_file": str(legacy), "profile_url": PROFILE_URL})

        pinterest_auth.ensure_pinterest_auth_storage()

        self.assertIn("current", pinterest_auth.load_saved_cookie_header(PROFILE_URL))
        self.assertNotIn("legacy", pinterest_auth.load_saved_cookie_header(PROFILE_URL))

    def test_invalid_legacy_document_is_not_migrated(self):
        legacy = self.root / "legacy-auth.json"
        legacy.write_text(
            json.dumps({**auth_document(), "provider": "not-pinterest"}),
            encoding="utf-8",
        )
        original_bytes = legacy.read_bytes()
        self.write_settings({"auth_file": str(legacy)})

        pinterest_auth.ensure_pinterest_auth_storage()

        self.assertFalse(self.fixed_auth.exists())
        self.assertEqual(original_bytes, legacy.read_bytes())
        self.assertNotIn("auth_file", json.loads(self.settings_path.read_text())["pinterest"])

    def test_fixed_auth_symlink_is_rejected_without_touching_target(self):
        victim = self.root / "victim.json"
        victim.write_text(json.dumps(auth_document("victim")), encoding="utf-8")
        self.fixed_auth.parent.mkdir(parents=True)
        self.fixed_auth.symlink_to(victim)

        with self.assertRaises(RuntimeError):
            pinterest_auth.import_cookie_header("_pinterest_sess=new", PROFILE_URL)
        with self.assertRaises(RuntimeError):
            pinterest_auth.delete_saved_auth()

        self.assertIn("victim", victim.read_text(encoding="utf-8"))

    def test_fixed_auth_directory_symlink_is_rejected_without_touching_target(self):
        outside_auth = self.root / "outside-auth"
        outside_auth.mkdir()
        victim = outside_auth / "browser_auth.json"
        victim.write_text(json.dumps(auth_document("victim")), encoding="utf-8")
        self.fixed_auth.parent.parent.mkdir(parents=True)
        self.fixed_auth.parent.symlink_to(outside_auth, target_is_directory=True)

        with self.assertRaises(RuntimeError):
            pinterest_auth.import_cookie_header("_pinterest_sess=new", PROFILE_URL)
        with self.assertRaises(RuntimeError):
            pinterest_auth.delete_saved_auth()

        self.assertIn("victim", victim.read_text(encoding="utf-8"))

    def test_logout_refuses_to_delete_unmarked_fixed_file(self):
        self.fixed_auth.parent.mkdir(parents=True)
        self.fixed_auth.write_text("unrelated-data", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            pinterest_auth.delete_saved_auth()

        self.assertEqual("unrelated-data", self.fixed_auth.read_text(encoding="utf-8"))

    def test_browser_session_auth_file_field_is_ignored(self):
        victim = self.root / "victim.json"
        victim.write_text("keep-browser-victim", encoding="utf-8")
        pinterest_auth._PENDING["session-1"] = {
            "session_id": "session-1",
            "profile_url": PROFILE_URL,
            "profile_dir": str(self.root / "profile"),
            "debug_port": 9222,
            "auth_file": str(victim),
            "process": None,
            "expires_at": 9999999999,
        }
        cdp_cookies = {
            "cookies": [
                {
                    "name": "unrelated",
                    "value": "must-not-be-saved",
                    "domain": ".evilpinterest.com",
                    "path": "/",
                    "expires": -1,
                },
                {
                    "name": "_pinterest_sess",
                    "value": "browser-account",
                    "domain": ".pinterest.com",
                    "path": "/",
                    "expires": -1,
                }
            ]
        }

        with (
            patch.object(pinterest_auth, "_cdp_page_call", return_value=cdp_cookies),
            patch.object(
                pinterest_auth,
                "inspect_cookie_header",
                return_value={
                    "authenticated": True,
                    "account": account_identity("account-b", "Account B"),
                },
            ),
            patch.object(pinterest_auth, "_close_and_cleanup_session"),
        ):
            result = pinterest_auth.complete_browser_login("session-1")

        self.assertTrue(result["authenticated"])
        self.assertEqual("account-b", result["auth_username"])
        self.assertEqual(
            "https://www.pinterest.com/account-b/",
            result["auth_profile_url"],
        )
        self.assertEqual("keep-browser-victim", victim.read_text(encoding="utf-8"))
        self.assertIn("browser-account", pinterest_auth.load_saved_cookie_header(PROFILE_URL))
        self.assertNotIn(
            "must-not-be-saved",
            self.fixed_auth.read_text(encoding="utf-8"),
        )
        self.assertNotIn("session-1", pinterest_auth._PENDING)

    def test_switch_account_reuses_canonical_file(self):
        pinterest_auth.import_cookie_header("_pinterest_sess=account-a", PROFILE_URL)
        first_path = pinterest_auth._auth_file()

        pinterest_auth.import_cookie_header("_pinterest_sess=account-b", PROFILE_URL)

        self.assertEqual(first_path, pinterest_auth._auth_file())
        self.assertIn("account-b", pinterest_auth.load_saved_cookie_header(PROFILE_URL))
        self.assertNotIn("account-a", pinterest_auth.load_saved_cookie_header(PROFILE_URL))

    def test_verify_saved_auth_persists_dynamic_account_identity(self):
        pinterest_auth.import_cookie_header("_pinterest_sess=dynamic", PROFILE_URL)
        with patch.object(
            pinterest_auth,
            "inspect_cookie_header",
            return_value={
                "authenticated": True,
                "account": account_identity("dynamic_user", "Dynamic User"),
            },
        ):
            result = pinterest_auth.verify_saved_auth()

        self.assertTrue(result["authenticated"])
        self.assertEqual("dynamic_user", result["auth_username"])
        saved = json.loads(self.fixed_auth.read_text(encoding="utf-8"))
        self.assertEqual(
            {
                "username": "dynamic_user",
                "display_name": "Dynamic User",
                "profile_url": "https://www.pinterest.com/dynamic_user/",
            },
            saved["account"],
        )

    def test_failed_browser_switch_preserves_current_account(self):
        pinterest_auth.import_cookie_header("_pinterest_sess=account-a", PROFILE_URL)
        original_bytes = self.fixed_auth.read_bytes()
        pinterest_auth._PENDING["session-2"] = {
            "session_id": "session-2",
            "profile_url": PROFILE_URL,
            "profile_dir": str(self.root / "profile"),
            "debug_port": 9223,
            "process": None,
            "expires_at": 9999999999,
        }
        cdp_cookies = {
            "cookies": [
                {
                    "name": "_pinterest_sess",
                    "value": "account-b",
                    "domain": ".pinterest.com",
                    "path": "/",
                    "expires": -1,
                }
            ]
        }

        with (
            patch.object(pinterest_auth, "_cdp_page_call", return_value=cdp_cookies),
            patch.object(
                pinterest_auth,
                "inspect_cookie_header",
                return_value={"authenticated": False, "account": {}},
            ),
            patch.object(pinterest_auth, "_close_and_cleanup_session"),
        ):
            result = pinterest_auth.complete_browser_login("session-2")

        self.assertTrue(result["pending"])
        self.assertEqual(original_bytes, self.fixed_auth.read_bytes())
        self.assertIn("session-2", pinterest_auth._PENDING)

    def test_browser_switch_without_resolved_identity_preserves_current_account(self):
        pinterest_auth.import_cookie_header("_pinterest_sess=account-a", PROFILE_URL)
        original_bytes = self.fixed_auth.read_bytes()
        pinterest_auth._PENDING["session-identity"] = {
            "session_id": "session-identity",
            "profile_url": "https://www.pinterest.com/",
            "profile_dir": str(self.root / "profile"),
            "debug_port": 9224,
            "process": None,
            "expires_at": 9999999999,
        }
        cdp_cookies = {
            "cookies": [
                {
                    "name": "_pinterest_sess",
                    "value": "account-b",
                    "domain": ".pinterest.com",
                    "path": "/",
                    "expires": -1,
                }
            ]
        }

        with (
            patch.object(pinterest_auth, "_cdp_page_call", return_value=cdp_cookies),
            patch.object(
                pinterest_auth,
                "inspect_cookie_header",
                return_value={"authenticated": True, "account": {}},
            ),
            patch.object(pinterest_auth, "_close_and_cleanup_session"),
        ):
            result = pinterest_auth.complete_browser_login("session-identity")

        self.assertTrue(result["pending"])
        self.assertEqual("waiting_identity", result["status"])
        self.assertEqual(original_bytes, self.fixed_auth.read_bytes())
        self.assertIn("session-identity", pinterest_auth._PENDING)

    def test_settings_patch_drops_existing_and_submitted_auth_paths(self):
        self.write_settings({"auth_file": str(self.root / "old.json"), "enabled": True})

        updated = _sanitize_system_settings_patch(
            {
                "pinterest": {
                    "auth_file": str(self.root / "new.json"),
                    "enabled": False,
                }
            }
        )

        self.assertNotIn("auth_file", updated["pinterest"])
        self.assertFalse(updated["pinterest"]["enabled"])

    def test_frontend_has_no_editable_pinterest_auth_path(self):
        source = (
            Path(__file__).parents[1] / "frontend" / "scripts" / "desktop-settings.js"
        ).read_text(encoding="utf-8")

        self.assertNotIn("pinterest.auth_file", source)
        # No concrete Pinterest profile may be hard-coded; only the "username" placeholder.
        profiles = set(re.findall(r"pinterest\.com/([A-Za-z0-9_.-]+)", source))
        self.assertLessEqual(profiles, {"username"}, "a concrete Pinterest profile is hard-coded")
        self.assertNotIn('data-system-setting-field="pinterest.profile_url"', source)
        self.assertIn("'pinterest.sync_profile_url'", source)
        self.assertIn("config.auth_username", source)
        self.assertIn("切换账号", source)

    def test_settings_document_extracts_only_public_account_identity(self):
        document = """
        <script id="__PWS_DATA__" type="application/json">
        {
          "context": {
            "user": {
              "username": "dynamic_user",
              "full_name": "Dynamic User",
              "email": "must-not-be-returned@example.com",
              "id": "123"
            }
          }
        }
        </script>
        """

        result = pinterest_auth._account_from_settings_document(
            document,
            "https://jp.pinterest.com/settings/",
        )

        self.assertEqual(
            {
                "username": "dynamic_user",
                "display_name": "Dynamic User",
                "profile_url": "https://jp.pinterest.com/dynamic_user/",
            },
            result,
        )
        self.assertNotIn("email", result)
        self.assertNotIn("id", result)

    def test_verified_identity_overrides_legacy_profile_url(self):
        self.write_settings({"profile_url": PROFILE_URL})
        document = auth_document("dynamic")
        document["account"] = account_identity("authorized_user", "Authorized User")
        document["profile_url"] = document["account"]["profile_url"]
        self.fixed_auth.parent.mkdir(parents=True)
        self.fixed_auth.write_text(json.dumps(document), encoding="utf-8")

        config = app_config.get_pinterest_config()

        self.assertEqual("authorized_user", config["auth_username"])
        self.assertEqual(
            "https://www.pinterest.com/authorized_user/",
            config["profile_url"],
        )


if __name__ == "__main__":
    unittest.main()
