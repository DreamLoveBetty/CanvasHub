"""The Google pool OAuth client comes from the environment or a local file, never the code."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidecars.google_pool import config

ROOT = Path(__file__).resolve().parents[1]


class GooglePoolClientConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        (self.data / "google_pool").mkdir()
        self.env = {"CANVASHUB_DATA_DIR": str(self.data)}

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, extra=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GOOGLE_POOL_")}
        env.update(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env, clear=True):
            return config.load_settings(callback_port=18080)

    def write(self, payload):
        (self.data / "google_pool" / config.OAUTH_CLIENT_FILE).write_text(
            payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
        )

    def test_no_client_is_built_into_the_code(self):
        source = (ROOT / "sidecars" / "google_pool" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("GOCSPX-", source)
        self.assertNotIn(".apps.googleusercontent.com", source)
        self.assertFalse(hasattr(config, "DEFAULT_CLIENT_SECRET"))

    def test_missing_configuration_is_reported_not_raised(self):
        settings = self.load()
        self.assertEqual((settings.client_id, settings.client_secret), ("", ""))

    def test_local_file_supplies_the_client(self):
        self.write({"client_id": "fixture-id", "client_secret": "fixture-secret"})
        settings = self.load()
        self.assertEqual((settings.client_id, settings.client_secret), ("fixture-id", "fixture-secret"))
        self.assertEqual(settings.db_path, self.data / "google_pool" / "accounts.db")

    def test_environment_wins_over_the_file(self):
        self.write({"client_id": "file-id", "client_secret": "file-secret"})
        settings = self.load({"GOOGLE_POOL_CLIENT_ID": "env-id", "GOOGLE_POOL_CLIENT_SECRET": "env-secret"})
        self.assertEqual((settings.client_id, settings.client_secret), ("env-id", "env-secret"))

    def test_half_configured_environment_still_raises(self):
        with self.assertRaises(ValueError):
            self.load({"GOOGLE_POOL_CLIENT_ID": "env-id"})

    def test_broken_or_partial_file_degrades_to_not_configured(self):
        for payload in ("{not json", json.dumps(["a"]), {"client_id": "only-id"}):
            with self.subTest(payload=payload):
                self.write(payload)
                with self.assertLogs(config.logger, level="WARNING"):
                    settings = self.load()
                self.assertEqual((settings.client_id, settings.client_secret), ("", ""))

    def test_local_file_is_ignored_by_git(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/data/", gitignore.splitlines())


if __name__ == "__main__":
    unittest.main()
