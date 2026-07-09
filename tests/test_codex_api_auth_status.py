#!/usr/bin/env python3

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CODEX_SCRIPTS = ROOT / "backend" / "codex_image_runtime" / "scripts"
if str(CODEX_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CODEX_SCRIPTS))


class CodexApiAuthStatusTest(unittest.TestCase):
    def test_inspect_auth_status_treats_invalidated_refresh_token_as_relogin(self):
        codex_api = importlib.import_module("codex_api")
        with tempfile.TemporaryDirectory() as tmp:
            auth_file = Path(tmp) / "auth.json"
            auth_file.write_text(
                json.dumps(
                    {
                        "tokens": {
                            "access_token": "at",
                            "refresh_token": "rt",
                            "id_token": "",
                            "account_id": "acct",
                            "expired": "2099-01-01T00:00:00Z",
                        },
                        "last_refresh_error": "HTTP 401 refresh_token_invalidated Your session has ended. Please log in again.",
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"CODEX_API_AUTH_FILE": str(auth_file), "CODEX_API_AUTH_STRICT": "1"}, clear=False):
                status = codex_api.inspect_auth_status()

        self.assertFalse(status["configured"])
        self.assertTrue(status["requires_relogin"])
        self.assertEqual(status["error"], "Codex auth requires re-login")
        self.assertTrue(status["candidates"][0]["requires_relogin"])
        self.assertEqual(status["candidates"][0]["status"], "需要重新登录")


if __name__ == "__main__":
    unittest.main()
