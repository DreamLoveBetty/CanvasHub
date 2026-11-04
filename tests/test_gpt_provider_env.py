#!/usr/bin/env python3
"""Local Codex provider env is resolved per call and never pinned into the server process."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import provider_gpt_codex

PROVIDER_ENV_KEYS = (
    "GPT_PROVIDER_AUTH_FILE",
    "GPT_PROVIDER_AUTH_DIR",
    "CODEX_API_AUTH_FILE",
    "CODEX_API_AUTH_DIR",
    "CODEX_API_AUTH_STRICT",
    "CODEX_API_BASE",
    "GPT_IMAGE_MAIN_MODEL",
    "GPT_PROVIDER_MAIN_MODEL",
    "GPT_REASONING_EFFORT",
    "GPT_PROVIDER_REASONING_EFFORT",
    "GPT_TRANSPORT_MODE",
    "GPT_PROVIDER_TRANSPORT_MODE",
)


class FakeProcess:
    def __init__(self, target, args, daemon):
        self.args = args

    def start(self) -> None:
        self.args[0].put({"ok": True, "result": []})

    def is_alive(self) -> bool:
        return False

    def join(self, timeout=None) -> None:
        return None


class FakeContext:
    def __init__(self) -> None:
        self.processes: list[FakeProcess] = []

    def Queue(self, maxsize=0):
        return queue.Queue(maxsize)

    def Process(self, target, args, daemon):
        process = FakeProcess(target, args, daemon)
        self.processes.append(process)
        return process


class GptProviderEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.settings_path = Path(self.tmp.name) / "settings.json"
        env = {key: "" for key in PROVIDER_ENV_KEYS}
        env["APP_SETTINGS_PATH"] = str(self.settings_path)
        env_patch = patch.dict(os.environ, env, clear=False)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        managed_patch = patch.object(provider_gpt_codex, "_managed_codex_provider_env", return_value=None)
        self.managed_env = managed_patch.start()
        self.addCleanup(managed_patch.stop)

    def write_settings(self, gpt_provider: dict) -> None:
        self.settings_path.write_text(json.dumps({"gpt_provider": gpt_provider}), encoding="utf-8")

    def write_auth(self, name: str) -> Path:
        path = Path(self.tmp.name) / name
        path.write_text(json.dumps({"tokens": {"access_token": "a", "refresh_token": "r"}}), encoding="utf-8")
        return path

    def provider_env_snapshot(self) -> dict:
        return {key: os.environ.get(key) for key in PROVIDER_ENV_KEYS}

    def run_provider(self, provider_env: dict | None = None) -> dict:
        ctx = FakeContext()
        with patch.object(provider_gpt_codex, "_provider_subprocess_context", return_value=ctx):
            provider_gpt_codex._run_provider_with_total_timeout("t", "generate", {}, timeout_seconds=5, provider_env=provider_env)
        return ctx.processes[0].args[3]

    def test_settings_change_applies_to_next_call_without_touching_process_env(self) -> None:
        before = self.provider_env_snapshot()
        self.write_settings({"transport_mode": "nonstream", "image_main_model": "gpt-5.5"})
        first = self.run_provider()
        self.write_settings({"transport_mode": "stream", "image_main_model": "gpt-5.6-luna"})
        second = self.run_provider()

        self.assertEqual(first["GPT_TRANSPORT_MODE"], "nonstream")
        self.assertEqual(second["GPT_TRANSPORT_MODE"], "stream")
        self.assertEqual(second["GPT_IMAGE_MAIN_MODEL"], "gpt-5.6-luna")
        self.assertEqual(self.provider_env_snapshot(), before)

    def test_deploy_env_is_left_for_the_child_to_inherit(self) -> None:
        self.write_settings({"api_base": "https://settings.example/codex"})
        with patch.dict(os.environ, {"CODEX_API_BASE": "https://deploy.example/codex"}):
            child_env = self.run_provider()

        self.assertNotIn("CODEX_API_BASE", child_env)

    def test_managed_and_route_env_override_settings_in_child_only(self) -> None:
        settings_auth = self.write_auth("settings-auth.json")
        self.write_settings({"auth_file": str(settings_auth)})
        self.managed_env.return_value = {
            "CODEX_API_AUTH_FILE": "/managed/auth.json",
            "GPT_PROVIDER_AUTH_FILE": "",
            "CODEX_API_AUTH_STRICT": "1",
        }
        with patch.dict(os.environ, {"GPT_PROVIDER_AUTH_DIR": "/deploy/auth-dir"}):
            child_env = self.run_provider(provider_env={"CODEX_API_AUTH_FILE": "/route/auth.json"})
            self.assertEqual(os.environ["GPT_PROVIDER_AUTH_DIR"], "/deploy/auth-dir")
            self.assertEqual(os.environ.get("CODEX_API_AUTH_STRICT"), "")

        self.assertEqual(child_env["CODEX_API_AUTH_FILE"], "/route/auth.json")
        self.assertEqual(child_env["CODEX_API_AUTH_STRICT"], "1")
        self.assertEqual(child_env["GPT_PROVIDER_AUTH_FILE"], "")

    def test_auth_status_follows_settings_and_leaves_process_env_alone(self) -> None:
        before = self.provider_env_snapshot()
        first_auth = self.write_auth("first.json")
        second_auth = self.write_auth("second.json")

        self.write_settings({"auth_file": str(first_auth)})
        first = provider_gpt_codex.get_gpt_provider_auth_status()
        self.write_settings({"auth_file": str(second_auth)})
        second = provider_gpt_codex.get_gpt_provider_auth_status()

        self.assertEqual(first["selected_path"], str(first_auth))
        self.assertEqual(second["selected_path"], str(second_auth))
        self.assertEqual(second["auth_file"], str(second_auth))
        self.assertEqual(self.provider_env_snapshot(), before)


if __name__ == "__main__":
    unittest.main()
