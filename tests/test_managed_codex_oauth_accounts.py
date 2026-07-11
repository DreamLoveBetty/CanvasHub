#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import managed_codex_oauth as managed


class ManagedCodexOAuthAccountsTest(unittest.TestCase):
    def test_multiple_oauth_sessions_are_pending_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = {
                "enabled": True,
                "auth_file": root / "auth.json",
                "accounts_dir": root / "accounts",
                "api_base": "https://chatgpt.com/backend-api/codex",
                "redirect_uri": "http://localhost:1455/auth/callback",
            }
            with patch.object(managed, "get_managed_codex_oauth_config", return_value=cfg), \
                 patch.object(managed, "_ensure_callback_server", return_value={"listening": True}):
                with managed._LOCK:
                    managed._PENDING.clear()
                    managed._COMPLETED.clear()
                try:
                    first = managed.start_oauth_login(open_browser=False)
                    second = managed.start_oauth_login(open_browser=False)
                    third = managed.start_oauth_login(open_browser=False)

                    self.assertNotEqual(first["session_id"], second["session_id"])
                    pending = managed.finish_oauth_callback(session_id=second["session_id"])
                    self.assertTrue(pending["ok"])
                    self.assertTrue(pending["pending"])
                    self.assertEqual(pending["status"], "waiting_callback")

                    def exchange(session, code):
                        return {
                            "ok": True,
                            "account_id": f"account-{code}",
                            "expires_at": "2099-01-01T00:00:00Z",
                        }

                    with patch.object(managed, "_exchange_code", side_effect=exchange) as exchange_code:
                        completed = managed.finish_oauth_callback(
                            code="one",
                            session_id=first["session_id"],
                        )
                        replay = managed.finish_oauth_callback(session_id=first["session_id"])
                        second_completed = managed.finish_oauth_callback(
                            code="two",
                            session_id=second["session_id"],
                        )
                        callback_completed = managed.finish_oauth_callback(
                            callback_url=(
                                "http://localhost:1455/auth/callback"
                                f"?code=three&state={third['session_id']}"
                            ),
                            session_id=first["session_id"],
                        )

                    self.assertFalse(completed["pending"])
                    self.assertEqual(replay["account_id"], "account-one")
                    self.assertEqual(second_completed["account_id"], "account-two")
                    self.assertEqual(callback_completed["account_id"], "account-three")
                    self.assertEqual(exchange_code.call_count, 3)
                    with managed._LOCK:
                        self.assertEqual(managed._PENDING, {})
                finally:
                    with managed._LOCK:
                        managed._PENDING.clear()
                        managed._COMPLETED.clear()

    def test_import_status_select_disable_and_provider_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_file = root / "auth.json"
            accounts_dir = root / "accounts"
            cfg = {
                "enabled": True,
                "auth_file": auth_file,
                "accounts_dir": accounts_dir,
                "api_base": "https://chatgpt.com/backend-api/codex",
                "redirect_uri": "http://localhost:1455/auth/callback",
            }
            public_cfg = {
                "enabled": True,
                "auth_file": str(auth_file),
                "accounts_dir": str(accounts_dir),
                "api_base": cfg["api_base"],
                "redirect_uri": cfg["redirect_uri"],
            }
            first = {
                "tokens": {
                    "access_token": "at-one",
                    "refresh_token": "rt-one",
                    "id_token": "",
                    "account_id": "account-one",
                    "expired": "2099-01-01T00:00:00Z",
                },
                "account": {"email": "one@example.com", "chatgpt_plan_type": "plus"},
            }
            second = {
                "tokens": {
                    "access_token": "at-two",
                    "refresh_token": "rt-two",
                    "id_token": "",
                    "account_id": "account-two",
                    "expired": "2099-01-02T00:00:00Z",
                },
                "account": {"email": "two@example.com", "chatgpt_plan_type": "team"},
            }
            with patch.object(managed, "get_managed_codex_oauth_config", return_value=cfg), \
                 patch.object(managed, "get_managed_codex_oauth_public_config", return_value=public_cfg):
                imported = managed.import_managed_auth_accounts({"accounts": [first, second]})
                status = managed.get_auth_status()

                self.assertEqual(imported["imported"], 2)
                self.assertEqual(status["accounts"]["stats"]["total"], 2)
                self.assertTrue(status["configured"])
                self.assertEqual(status["account"]["email"], "one@example.com")
                self.assertEqual(status["accounts"]["stats"]["refreshable"], 2)
                self.assertNotIn("at-one", str(status))
                first_id = status["selected_account_id"]
                second_id = [item["account_id"] for item in status["accounts"]["items"] if item["email"] == "two@example.com"][0]

                env = managed.get_provider_env()
                self.assertTrue(env["CODEX_API_AUTH_FILE"].endswith(f"{first_id}.json"))
                self.assertEqual(env["CODEX_API_AUTH_STRICT"], "1")

                managed.update_managed_auth_account(second_id, select=True)
                selected = managed.get_auth_status()
                self.assertEqual(selected["account"]["email"], "two@example.com")

                managed.update_managed_auth_account(second_id, disabled=True)
                fallback = managed.get_auth_status()
                self.assertEqual(fallback["account"]["email"], "one@example.com")

                managed.delete_managed_auth(first_id)
                after_delete = managed.get_auth_status()
                self.assertEqual(after_delete["accounts"]["stats"]["total"], 1)

    def test_invalidated_refresh_token_requires_relogin_and_is_not_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auth_file = root / "auth.json"
            accounts_dir = root / "accounts"
            cfg = {
                "enabled": True,
                "auth_file": auth_file,
                "accounts_dir": accounts_dir,
                "api_base": "https://chatgpt.com/backend-api/codex",
                "redirect_uri": "http://localhost:1455/auth/callback",
            }
            public_cfg = {
                "enabled": True,
                "auth_file": str(auth_file),
                "accounts_dir": str(accounts_dir),
                "api_base": cfg["api_base"],
                "redirect_uri": cfg["redirect_uri"],
            }
            invalidated = {
                "tokens": {
                    "access_token": "at-invalid",
                    "refresh_token": "rt-invalid",
                    "id_token": "",
                    "account_id": "account-invalid",
                    "expired": "2099-01-01T00:00:00Z",
                },
                "account": {"email": "invalid@example.com", "chatgpt_plan_type": "plus"},
                "last_refresh_error": "刷新失败：HTTP 401 refresh_token_invalidated Your session has ended. Please log in again.",
            }
            with patch.object(managed, "get_managed_codex_oauth_config", return_value=cfg), \
                 patch.object(managed, "get_managed_codex_oauth_public_config", return_value=public_cfg):
                managed.import_managed_auth_accounts({"accounts": [invalidated]})
                status = managed.get_auth_status()

                self.assertFalse(status["configured"])
                self.assertEqual(status["error"], "managed Codex OAuth 需要重新登录")
                self.assertEqual(status["accounts"]["stats"]["available"], 0)
                self.assertEqual(status["accounts"]["stats"]["requires_relogin"], 1)
                self.assertEqual(status["accounts"]["items"][0]["status"], "需要重新登录")
                self.assertTrue(status["accounts"]["items"][0]["requires_relogin"])
                with self.assertRaisesRegex(RuntimeError, "需要重新登录"):
                    managed.get_provider_env()


if __name__ == "__main__":
    unittest.main()
