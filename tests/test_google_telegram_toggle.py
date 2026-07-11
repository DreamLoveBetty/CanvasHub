from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend import api_client
from backend import server


class GoogleTelegramToggleTest(unittest.TestCase):
    def test_google_generate_skips_telegram_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch.object(server, "get_task", return_value={"params": {}}), \
                patch.object(server, "update_task_fields"), \
                patch.object(server, "update_task_status"), \
                patch.object(server, "update_task") as update_task, \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "send_telegram") as send_telegram, \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir), \
                patch.object(server, "generate_image", return_value=(b"fake-png-bytes", {})):
                server.process_task(
                    "google_task_no_tg",
                    "a calm city skyline",
                    {
                        "ratio": "1:1",
                        "quality": "hd",
                        "model": "gemini-3.1-flash-image",
                        "telegram_enabled": False,
                    },
                )

            send_telegram.assert_not_called()
            self.assertTrue(update_task.called)
            self.assertEqual(update_task.call_args.args[1], "succeeded_no_telegram")

    def test_google_edit_skips_telegram_when_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch.object(server, "get_task", return_value={"params": {}}), \
                patch.object(server, "update_task_fields"), \
                patch.object(server, "update_task_status"), \
                patch.object(server, "update_task") as update_task, \
                patch.object(server, "send_status_notification"), \
                patch.object(server, "send_telegram") as send_telegram, \
                patch.object(server, "save_thumbnail"), \
                patch.object(server, "write_obsidian_prompt_sidecar"), \
                patch.object(server, "daily_output_dir", return_value=out_dir), \
                patch.object(api_client, "edit_image", return_value=(b"fake-edit-bytes", {})):
                server.process_edit_task(
                    "google_edit_no_tg",
                    "make it brighter",
                    ["reference-image"],
                    {
                        "ratio": "1:1",
                        "quality": "hd",
                        "model": "gemini-3.1-flash-image",
                        "telegram_enabled": False,
                    },
                )

            send_telegram.assert_not_called()
            self.assertTrue(update_task.called)
            self.assertEqual(update_task.call_args.args[1], "succeeded_no_telegram")

    def test_google_batch_params_carry_telegram_toggle(self) -> None:
        params = server._make_batch_task_params(
            "google",
            {
                "ratio": "1:1",
                "resolution": "2k",
                "model": "gemini-3.1-flash-image",
                "telegramEnabled": False,
                "archiveEnabled": False,
            },
            "batch prompt",
            "batch_1",
            0,
            2,
        )

        self.assertFalse(params["telegram_enabled"])
        self.assertFalse(params["archive_enabled"])

    def test_gpt_edit_skips_telegram_when_disabled(self) -> None:
        with patch.object(server, "get_task", return_value={"params": {"telegram_enabled": False}}), \
            patch.object(server, "update_task_fields"), \
            patch.object(server, "update_task_status"), \
            patch.object(server, "update_task") as update_task, \
            patch.object(server, "send_status_notification"), \
            patch.object(
                server,
                "resolve_route_model",
                return_value={
                    "route": "codex",
                    "model": "gpt-5.5",
                    "reasoning_effort": "medium",
                    "available": True,
                    "source": "test",
                    "model_role": "responses_main_model",
                    "image_engine": {"id": "gpt-image-2", "label": "GPT Image 2"},
                },
            ), \
            patch.object(
                server,
                "edit_image_gpt_codex",
                return_value={
                    "success": True,
                    "image_path": "/tmp/gpt-edit.png",
                    "image_paths": ["/tmp/gpt-edit.png"],
                },
            ), \
            patch.object(server, "send_telegram_result") as send_telegram_result:
            server.process_gpt_edit_task(
                "gpt_edit_no_tg",
                "make it brighter",
                ["reference-image"],
                "1:1",
                "1k",
                telegram_enabled=False,
            )

        send_telegram_result.assert_not_called()
        self.assertTrue(update_task.called)
        self.assertEqual(update_task.call_args.args[1], "succeeded")
        payload = update_task.call_args.kwargs
        self.assertIn("跳过 Telegram", payload.get("progress_text", ""))


if __name__ == "__main__":
    unittest.main()
