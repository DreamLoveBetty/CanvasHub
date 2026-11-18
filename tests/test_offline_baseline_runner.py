"""Modest checks for the official offline regression entry. No server import."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from tests.offline_baseline import (
    CREDENTIAL_ENV_NAMES,
    POLLUTING_ENV_NAMES,
    PROJECT_MARKER,
    assert_sandbox_isolated,
    build_sandbox_env,
    is_project_venv_interpreter,
    project_venv_python,
    scrub_inherited_env,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class OfflineBaselineHelperTests(unittest.TestCase):
    def test_sandbox_env_stays_under_tests_tmp_and_misses_production_paths(self):
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT / "tests" / "tmp") as tmp:
            workdir = Path(tmp)
            env = build_sandbox_env(PROJECT_ROOT, workdir)
            data_dir = Path(env["CANVASHUB_DATA_DIR"]).resolve()
            settings = Path(env["APP_SETTINGS_PATH"]).resolve()
            tasks = Path(env["TASKS_DB_PATH"]).resolve()
            assert_sandbox_isolated(PROJECT_ROOT, workdir)
            self.assertTrue(data_dir.is_relative_to((PROJECT_ROOT / "tests" / "tmp").resolve()))
            self.assertNotEqual(settings, (PROJECT_ROOT / "settings.json").resolve())
            self.assertNotEqual(tasks, (PROJECT_ROOT / "tasks.db").resolve())
            self.assertNotEqual(tasks, (PROJECT_ROOT / "data" / "tasks.db").resolve())
            self.assertFalse(
                Path(env["CANVASHUB_DATA_DIR"]).resolve()
                == (PROJECT_ROOT / "data").resolve()
            )
            self.assertEqual(settings.read_text(encoding="utf-8"), "{}")
            self.assertEqual(env["CHATGPT_POOL_ENABLED"], "false")
            self.assertEqual(env["COMFY_BASE_URL"], "http://127.0.0.1:1")
            self.assertNotIn("KMP_DUPLICATE_LIB_OK", env)
            self.assertEqual(env[PROJECT_MARKER], str(workdir))

    def test_sandbox_refuses_a_path_outside_tests_tmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                assert_sandbox_isolated(PROJECT_ROOT, Path(tmp))

    def test_scrub_removes_public_mode_and_credentials_without_needing_values(self):
        inherited = {
            "PATH": "/usr/bin",
            "MINIAPP_PUBLIC_MODE": "false",
            "PUBLIC_MODE": "1",
            "MINIAPP_ACCESS_PASSWORD": "should-not-be-kept",
            "TELEGRAM_BOT_TOKEN": "should-not-be-kept",
            "KMP_DUPLICATE_LIB_OK": "TRUE",
            "PORT": "18463",
        }
        cleaned = scrub_inherited_env(inherited)
        self.assertEqual(cleaned["PATH"], "/usr/bin")
        for key in (
            "MINIAPP_PUBLIC_MODE",
            "PUBLIC_MODE",
            "MINIAPP_ACCESS_PASSWORD",
            "TELEGRAM_BOT_TOKEN",
            "KMP_DUPLICATE_LIB_OK",
            "PORT",
        ):
            self.assertNotIn(key, cleaned)
        self.assertIn("MINIAPP_PUBLIC_MODE", POLLUTING_ENV_NAMES)
        self.assertIn("MINIAPP_ACCESS_PASSWORD", CREDENTIAL_ENV_NAMES)

    def test_project_venv_is_detected_when_present(self):
        venv = project_venv_python(PROJECT_ROOT)
        if venv is None:
            self.skipTest("project .venv is not present")
        self.assertTrue(venv.exists())
        self.assertTrue(is_project_venv_interpreter(PROJECT_ROOT, str(venv)))
        self.assertFalse(is_project_venv_interpreter(PROJECT_ROOT, "/usr/bin/python3"))


if __name__ == "__main__":
    unittest.main()
