#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app_config import (
    DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    DEFAULT_GPT_TRANSPORT_MODE,
    GPT_TRANSPORT_MODES,
    get_gpt_provider_config,
)
from backend.server import _coerce_gpt_task_type, _sanitize_gpt_provider_patch


class GptTransportConfigTest(unittest.TestCase):
    def settings_env(self, settings_path: Path) -> dict[str, str]:
        return {
            "APP_SETTINGS_PATH": str(settings_path),
            "GPT_TRANSPORT_MODE": "",
            "GPT_PROVIDER_TRANSPORT_MODE": "",
            "GPT_PROVIDER_TOTAL_TIMEOUT": "",
        }

    def test_default_transport_mode_is_stream_then_nonstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, self.settings_env(settings_path), clear=False):
                cfg = get_gpt_provider_config()

        self.assertEqual(DEFAULT_GPT_TRANSPORT_MODE, "stream_then_nonstream")
        self.assertIn(cfg["transport_mode"], GPT_TRANSPORT_MODES)
        self.assertEqual(cfg["transport_mode"], "stream_then_nonstream")

    def test_transport_mode_can_be_loaded_from_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"gpt_provider": {"transport_mode": "nonstream"}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, self.settings_env(settings_path), clear=False):
                cfg = get_gpt_provider_config()

        self.assertEqual(cfg["transport_mode"], "nonstream")

    def test_invalid_transport_mode_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"gpt_provider": {"transport_mode": "bad"}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, self.settings_env(settings_path), clear=False):
                cfg = get_gpt_provider_config()

        self.assertEqual(cfg["transport_mode"], DEFAULT_GPT_TRANSPORT_MODE)

    def test_sanitize_gpt_provider_patch_accepts_transport_mode(self) -> None:
        patch_payload = _sanitize_gpt_provider_patch({"transport_mode": "stream"})

        self.assertEqual(patch_payload["transport_mode"], "stream")

    def test_default_provider_total_timeout_is_600_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text("{}", encoding="utf-8")
            with patch.dict(os.environ, self.settings_env(settings_path), clear=False):
                cfg = get_gpt_provider_config()

        self.assertEqual(DEFAULT_GPT_PROVIDER_TOTAL_TIMEOUT_SECONDS, 600)
        self.assertEqual(cfg["total_timeout_seconds"], 600)

    def test_provider_total_timeout_can_be_loaded_from_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / "settings.json"
            settings_path.write_text(
                json.dumps({"gpt_provider": {"total_timeout_seconds": 420}}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, self.settings_env(settings_path), clear=False):
                cfg = get_gpt_provider_config()

        self.assertEqual(cfg["total_timeout_seconds"], 420)

    def test_sanitize_gpt_provider_patch_accepts_total_timeout(self) -> None:
        patch_payload = _sanitize_gpt_provider_patch({"total_timeout_seconds": "300"})

        self.assertEqual(patch_payload["total_timeout_seconds"], 300)

    def test_gpt_task_type_normalization(self) -> None:
        self.assertEqual(_coerce_gpt_task_type("ppt"), "ppt")
        self.assertEqual(_coerce_gpt_task_type("photoshop"), "psd")
        self.assertEqual(_coerce_gpt_task_type("codex"), "image")

    def test_route_trace_appends_to_task_params(self) -> None:
        from backend import server

        state = {"params": {}}

        def fake_update(_task_id, **fields):
            if "params" in fields:
                state["params"] = json.loads(fields["params"])

        with patch.object(server, "get_task", return_value=state), patch.object(server, "update_task_fields", side_effect=fake_update):
            server._append_task_route_trace("task", "codex", "started", "start", timeout_seconds=600)
            server._append_task_route_trace("task", "codex", "succeeded", "done", elapsed_seconds=279)

        trace = state["params"]["route_trace"]
        self.assertEqual(trace[0]["route"], "codex")
        self.assertEqual(trace[0]["timeout_seconds"], 600)
        self.assertEqual(trace[1]["status"], "succeeded")
        self.assertEqual(trace[1]["elapsed_seconds"], 279)


if __name__ == "__main__":
    unittest.main()
